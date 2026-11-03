# Personal Assistant 服务部署手册
## 基础信息
- 服务器：Ubuntu 22.04 LTS，腾讯云，公网IP：124.222.183.195
- 登录用户：ubuntu
- 项目技术栈
  - 后端：Python + FastAPI + Pydantic
  - ORM：SQLAlchemy 2.0
  - 定时任务：APScheduler（内嵌进程，禁止多进程/多worker）
  - 模板：Jinja2
  - 前端交互：HTMX + Alpine.js + Leaflet
  - AI：DeepSeek V4-Flash OpenAI兼容接口
  - MCP：本地 stdio 模式 Host（zotero / feed / memory 等）
  - 依赖管理：uv
  - 数据库：SQLite（文件：assistant.db）
- 代码仓库：https://github.com/yyyysf/personal-assistant，私有仓库，main 分支，当前目标 commit：b7335fe
- 本地开发入口：uvicorn src.api.main:app --reload（项目无根目录 main.py）
- 服务监听（内部）：127.0.0.1:8000
- 对外入口：Nginx 80端口 HTTP
- 安全组策略：仅放行 22(SSH)、80(HTTP)；8000 不对外放行

## 部署目标
1. 拉取私有仓库代码到服务器
2. 安装 uv，使用 uv sync 还原依赖
3. 配置 .env 环境变量
4. systemd 托管服务，开机自启、失败自动重启，**单worker**
5. Nginx 反向代理 + 静态资源缓存优化
6. 验证页面访问、定时任务、MCP stdio 子进程正常拉起

## 前置准备（人工提前提供）
- GitHub Classic PAT（带 repo 权限）
- .env 配置内容：DEEPSEEK_API_KEY、服务密钥、MCP 相关配置等

## 完整执行步骤
> 所有命令以 ubuntu 用户执行，sudo 按需使用

### 1. 基础系统包安装
```bash
sudo apt update && sudo apt install -y git curl nginx
2. 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
uv --version
### 3. 克隆私有仓库

> 
> 替换 <GITHUB_PAT> 为提供的 PAT
git clone https://<GITHUB_PAT>@github.com/yyyysf/personal-assistant.git
cd personal-assistant
git checkout main
git log --oneline | head -5
# 核对 commit 包含 b7335fe
>
> 无 PAT 时的等效方案（本次部署采用）：本地执行
> `git bundle create assistant.bundle main`，
> 上传后 `git clone -b main assistant.bundle personal-assistant`，
> 再 `git remote set-url origin https://github.com/yyyysf/personal-assistant.git`。
> 注意：服务器后续 `git pull` 仍需 PAT 或 Deploy Key。
4. 虚拟环境 + 依赖安装
uv venv --python 3.12
source .venv/bin/activate
# 国内网络建议使用腾讯云内网镜像，避免大 wheel 超时
export UV_HTTP_TIMEOUT=180
uv sync --python 3.12 --no-dev --frozen \
  --index-url https://mirrors.cloud.tencent.com/pypi/simple
5. 环境配置
cp .env.example .env
# 填入 .env 内容（人工传入）
nano .env
6. 手动预启动测试（必须做，确认无报错）
.venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8000
检查项：

- FastAPI 启动成功
- APScheduler 调度加载正常，无重复调度警告
- MCP stdio 子进程可以正常拉起
Ctrl+C 停止测试服务后再往下执行
### 7. 创建 systemd 服务单元

写入 `/etc/systemd/system/assistant.service`
[Unit]
Description=Personal Assistant FastAPI Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/personal-assistant
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/personal-assistant/.venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
SuccessExitStatus=0

[Install]
WantedBy=multi-user.target
> 查看实时日志：`journalctl -u assistant -f`

### 8. Nginx 站点配置

写入 `/etc/nginx/sites-available/assistant`
server {
    listen 80 default_server;
    server_name _;

    # 旅游图片上传（单张 ≤5MB、每次最多 6 张）
    client_max_body_size 12m;
    # AI 摘要/翻译等长请求
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    location ~* \.(css|js|png|jpg|jpeg|gif|svg|webp|ico|woff2?)$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        expires 7d;
        add_header Cache-Control "public";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
启用站点、关闭默认站点
sudo ln -sfn /etc/nginx/sites-available/assistant /etc/nginx/sites-enabled/assistant
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
### 9. 验证部署

1. 浏览器访问 [http://124.222.183.195](http://124.222.183.195)
2. 验证页面渲染、HTMX 交互、地图 Leaflet 加载
3. 验证 AI 摘要接口调用 DeepSeek 正常
4. 验证 APScheduler 定时任务正常调度，无重复执行
5. 验证 MCP stdio 子进程正常启动

## 部署实录（2026-11-03）

- 实际代码版本：`b7335fe`（通过 git bundle 传输，未使用 PAT）
- 生产 `.env`：`APP_ENV=production`、`DEBUG=false`、`SEED_DEMO_DATA=false`、`MCP_MODE=stdio`、权限 600
- Python 3.12（uv 托管），依赖通过腾讯云 PyPI 镜像安装
- systemd：`assistant.service` 已 enable + active，单进程监听 127.0.0.1:8000
- Nginx：80 反代、静态资源缓存 7 天、`client_max_body_size 12m`
- 已验证：公网首页/API/静态资源 200；APScheduler 3 个任务运行中
- DeepSeek：Key 已配置并通过真实调用验证（模型 `deepseek-v4-flash`）
- Zotero：User ID `22122725` + API Key 已配置；`/keys` 校验 userID 匹配、write=true，文库读取正常（136 条）
- MCP：`servers.json` 中 5 个服务均 `enabled=false`，故无 stdio 子进程运行；启用前需先安装对应命令
- GitHub Deploy Key：只读，私钥在服务器 `~/.ssh/github_deploy`，remote 已切为 SSH，`git pull` 实测可用
- 待办：SQLite 定时备份 cron 未配置

## 后续运维命令

### 更新代码版本
cd ~/personal-assistant
git pull --ff-only
# 仅在依赖变更时执行；国内网络加腾讯云镜像
export PATH="$HOME/.local/bin:$PATH"
UV_HTTP_TIMEOUT=180 uv sync --python 3.12 --no-dev --frozen \
  --index-url https://mirrors.cloud.tencent.com/pypi/simple
sudo systemctl restart assistant
查看日志
journalctl -u assistant -f
停止 / 重启服务
sudo systemctl stop assistant
sudo systemctl restart assistant
## 硬性红线（绝对不能违反）

1. **禁止增加 --workers 参数**，只能单进程，防止 APScheduler 多实例重复跑任务
2. 服务永远监听 127.0.0.1，不直接 0.0.0.0:8000 对外暴露
3. SQLite 文件 `assistant.db` 重要，后续添加定时备份 cron
4. .env 文件不要提交 git，权限建议 chmod 600 .env
5. MCP 使用 stdio 模式，不要擅自改为 SSE，除非收到明确变更指令

## 可选后续任务（本次不执行）

- 域名绑定 + Certbot HTTPS
- SQLite 迁移 Postgres + PostGIS
- crontab 自动备份 sqlite 数据库