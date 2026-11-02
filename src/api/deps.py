"""FastAPI 公共依赖：模板环境、渲染与基础上下文。"""

import html
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from src.core.config import BASE_DIR, settings
from src.core.db import get_db
from src.core.time_utils import today

TEMPLATES_DIR = Path(BASE_DIR) / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _format_dt(value: datetime | None, fmt: str = "%m-%d %H:%M") -> str:
    return value.strftime(fmt) if value else "—"


def _format_date(value: date | None, fmt: str = "%Y-%m-%d") -> str:
    return value.strftime(fmt) if value else "—"


def _priority_label(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value)


def _simple_markdown(text: str) -> Markup:
    """先转义再做极简 Markdown 渲染，避免 LLM 输出注入 HTML。"""
    escaped = html.escape(text or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)

    parts: list[str] = []
    list_type: str | None = None
    for raw_line in escaped.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if list_type:
                parts.append(f"</{list_type}>")
                list_type = None
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            if list_type:
                parts.append(f"</{list_type}>")
                list_type = None
            level = min(len(heading.group(1)) + 2, 6)
            parts.append(f"<h{level}>{heading.group(2)}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        ordered = re.match(r"^\d+[.)]\s+(.*)$", line)
        if bullet or ordered:
            desired = "ul" if bullet else "ol"
            if list_type != desired:
                if list_type:
                    parts.append(f"</{list_type}>")
                parts.append(f"<{desired}>")
                list_type = desired
            content = (bullet or ordered).group(1)
            parts.append(f"<li>{content}</li>")
            continue
        if list_type:
            parts.append(f"</{list_type}>")
            list_type = None
        parts.append(f"<p>{line}</p>")
    if list_type:
        parts.append(f"</{list_type}>")
    return Markup("\n".join(parts))


templates.env.filters["dt"] = _format_dt
templates.env.filters["d"] = _format_date
templates.env.filters["priority"] = _priority_label
templates.env.filters["md"] = _simple_markdown
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["current_year"] = today().year

NAV_GROUPS = [
    {"key": "dashboard", "href": "/", "label": "首页仪表盘", "icon": "◉"},
    {"key": "todo", "href": "/todo", "label": "任务与目标", "icon": "✓"},
    {"key": "research", "href": "/research", "label": "科研论文", "icon": "◈"},
    {"key": "reading", "href": "/reading", "label": "书单阅读", "icon": "▤"},
    {"key": "news", "href": "/news", "label": "前沿资讯", "icon": "◎"},
    {
        "key": "learning",
        "label": "业余学习",
        "icon": "▷",
        "children": [
            {"key": "video", "href": "/learning/video", "label": "AI 视频学习", "icon": "▷"},
            {"key": "music", "href": "/learning/music", "label": "AI 音乐学习", "icon": "♪"},
        ],
    },
    {"key": "travel", "href": "/travel", "label": "旅游规划", "icon": "⌖"},
]
NAV_ITEMS = [item for group in NAV_GROUPS for item in (group.get("children") or [group])]


def _page_href(request: Request, param: str, value: Any) -> str:
    return str(request.url.include_query_params(**{param: value}))


def _query_href(request: Request, action: str, param: str, value: Any) -> str:
    items = [(key, val) for key, val in request.query_params.multi_items() if key != param]
    items.append((param, str(value)))
    return f"{action}?{urlencode(items)}"


templates.env.globals["page_href"] = _page_href
templates.env.globals["query_href"] = _query_href


def render(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    active: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    payload: dict[str, Any] = {
        "request": request,
        "active": active,
        "nav_items": NAV_ITEMS,
        "nav_groups": NAV_GROUPS,
        "today": today(),
        "llm_ready": settings.llm_configured,
        "zotero_ready": settings.zotero_configured,
    }
    if context:
        payload.update(context)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=payload,
        status_code=status_code,
    )


def render_partial(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context or {},
    )


__all__ = ["get_db", "render", "render_partial", "templates", "NAV_GROUPS", "NAV_ITEMS"]
