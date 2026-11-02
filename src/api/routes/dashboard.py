"""首页仪表盘页面与 AI 复盘 HTMX 动作。"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db, render, render_partial
from src.core.config import settings
from src.core.logging import get_logger
from src.core.stats import dashboard_context, latest_review
from src.mcp_host.manager import mcp_host
from src.scheduler.review import generate_and_store_review
from src.scheduler.runner import scheduler_status

router = APIRouter()
logger = get_logger(__name__)


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = dashboard_context(db)
    context["system"] = {
        "llm": settings.llm_configured,
        "zotero": settings.zotero_configured,
        "scheduler": scheduler_status(),
        "mcp": mcp_host.status(),
    }
    return render(request, "dashboard.html", context, active="dashboard")


@router.post("/dashboard/review", response_class=HTMLResponse)
def dashboard_review(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    error = ""
    try:
        review = generate_and_store_review(db)
    except Exception as exc:
        logger.exception("生成周复盘失败：%s", exc)
        review = latest_review(db)
        error = "生成复盘失败，请检查 DeepSeek 配置后重试。"
    return render_partial(
        request,
        "partials/review_card.html",
        {"review": review, "error": error},
    )
