"""MCP Host 管理器。

第一阶段负责：多服务配置加载、stdio 进程生命周期、远程 SSE 连通性探测。
工具调用层将在后续迭代接入 MCP SDK（stdio 用 ClientSession，线上用 SSE）。
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)


class MCPHostError(RuntimeError):
    pass


class MCPHostManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = Path(config_path or settings.mcp_config_path)
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._last_error: dict[str, str] = {}
        self._started_at: dict[str, datetime] = {}
        self._remote_ok: dict[str, bool] = {}
        self._servers: dict[str, dict[str, Any]] = {}
        self.load_config()

    def load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning("MCP 配置不存在：%s", self.config_path)
            self._servers = {}
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers = payload.get("servers", {})
            if not isinstance(servers, dict):
                raise MCPHostError("servers 必须是对象")
            self._servers = servers
        except (json.JSONDecodeError, MCPHostError) as exc:
            logger.error("MCP 配置解析失败：%s", exc)
            self._servers = {}

    def _public_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        transport = config.get("transport", "stdio")
        return {
            "name": name,
            "transport": transport,
            "enabled": bool(config.get("enabled", False)),
            "description": config.get("description", ""),
            "command": config.get("command", "") if transport == "stdio" else "",
            "args": config.get("args", []) if transport == "stdio" else [],
            "url": config.get("url", "") if transport != "stdio" else "",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            servers = []
            for name, config in self._servers.items():
                info = self._public_config(name, config)
                process = self._processes.get(name)
                running = bool(process and process.poll() is None)
                info.update(
                    {
                        "running": running,
                        "pid": process.pid if running and process else None,
                        "remote_reachable": self._remote_ok.get(name),
                        "started_at": (
                            self._started_at[name].isoformat()
                            if running and name in self._started_at
                            else None
                        ),
                        "last_error": self._last_error.get(name, ""),
                    }
                )
                servers.append(info)
            return {
                "mode": settings.mcp_mode,
                "config_path": str(self.config_path),
                "configured": len(servers),
                "enabled": sum(1 for item in servers if item["enabled"]),
                "running": sum(1 for item in servers if item["running"]),
                "servers": servers,
                "note": (
                    "第一阶段完成配置与 stdio 进程生命周期管理；"
                    "MCP 工具调用协议接入将在后续迭代完成。"
                ),
            }

    def start(self, name: str) -> dict[str, Any]:
        config = self._servers.get(name)
        if not config:
            raise MCPHostError(f"未找到 MCP 服务：{name}")
        if not config.get("enabled", False):
            raise MCPHostError(f"MCP 服务 {name} 未启用，请先在 servers.json 中设置 enabled=true")

        transport = config.get("transport", "stdio")
        if transport == "stdio":
            return self._start_stdio(name, config)
        return self._probe_remote(name, config)

    def _start_stdio(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            process = self._processes.get(name)
            if process and process.poll() is None:
                return {"ok": True, "message": f"{name} 已在运行（PID {process.pid}）"}
            command = config.get("command", "")
            if not command:
                raise MCPHostError(f"{name} 未配置 command")
            resolved = shutil.which(command)
            if not resolved:
                self._last_error[name] = f"命令不存在：{command}"
                raise MCPHostError(f"命令不存在：{command}，请先安装对应 MCP 服务")

            env = os.environ.copy()
            env.update({str(key): str(value) for key, value in config.get("env", {}).items()})
            kwargs: dict[str, Any] = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            try:
                child = subprocess.Popen(  # noqa: S603 - 命令来自本地受控配置
                    [resolved, *config.get("args", [])],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    **kwargs,
                )
            except OSError as exc:
                self._last_error[name] = str(exc)
                raise MCPHostError(f"启动 {name} 失败：{exc}") from exc

            self._processes[name] = child
            self._started_at[name] = datetime.now()
            self._last_error.pop(name, None)
            logger.info("MCP stdio 服务已启动：%s (PID %s)", name, child.pid)
            return {"ok": True, "message": f"{name} 已启动（PID {child.pid}）", "pid": child.pid}

    def _probe_remote(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        url = config.get("url", "")
        if not url:
            raise MCPHostError(f"{name} 未配置 url")
        try:
            response = httpx.get(url, timeout=5)
            reachable = response.status_code < 500
        except httpx.HTTPError as exc:
            self._remote_ok[name] = False
            self._last_error[name] = str(exc)
            raise MCPHostError(f"远程 MCP 服务不可达：{exc}") from exc
        self._remote_ok[name] = reachable
        self._last_error.pop(name, None)
        return {
            "ok": reachable,
            "message": f"{name} 连通性探测{'成功' if reachable else '失败'}",
            "reachable": reachable,
        }

    def stop(self, name: str) -> dict[str, Any]:
        with self._lock:
            process = self._processes.get(name)
            if not process or process.poll() is not None:
                self._processes.pop(name, None)
                self._remote_ok.pop(name, None)
                return {"ok": True, "message": f"{name} 未在运行"}
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            self._processes.pop(name, None)
            self._started_at.pop(name, None)
            logger.info("MCP 服务已停止：%s", name)
            return {"ok": True, "message": f"{name} 已停止"}

    def stop_all(self) -> None:
        for name in list(self._processes):
            try:
                self.stop(name)
            except Exception as exc:  # 关闭阶段尽力而为
                logger.warning("停止 MCP %s 失败：%s", name, exc)


mcp_host = MCPHostManager()
