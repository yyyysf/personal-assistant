"""AI & 计算机前沿资讯日报：RSS 聚合、LLM 简报、时间线与搜索。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db, render, render_partial
from src.models import NewsDigest, NewsItem
from src.scheduler.fetchers import build_daily_digest, fetch_rss, refresh_news_summary

router = APIRouter()


def news_context(db: Session, q: str = "", month: str = "") -> dict:
    stmt = select(NewsItem)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(NewsItem.title.ilike(pattern) | NewsItem.summary.ilike(pattern))
    if month.strip():
        try:
            year_str, month_str = month.split("-", 1)
            start = date(int(year_str), int(month_str), 1)
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
            stmt = stmt.where(NewsItem.digest_date >= start, NewsItem.digest_date < end)
        except (ValueError, TypeError):
            month = ""
    items = db.scalars(stmt.order_by(NewsItem.fetched_at.desc()).limit(200)).all()

    grouped: dict[date, list[NewsItem]] = {}
    for item in items:
        key = (item.published_at or item.fetched_at).date()
        grouped.setdefault(key, []).append(item)
    timeline = [
        {"date": key, "entries": sorted(value, key=lambda row: row.fetched_at, reverse=True)}
        for key, value in sorted(grouped.items(), reverse=True)
    ]
    digests = db.scalars(select(NewsDigest).order_by(NewsDigest.digest_date.desc()).limit(12)).all()
    latest = digests[0] if digests else None
    return {
        "timeline": timeline,
        "digests": digests,
        "latest_digest": latest,
        "q": q,
        "month": month,
        "total": len(items),
        "notice": "",
        "error": "",
    }


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request,
    q: str = Query(""),
    month: str = Query(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return render(request, "news.html", news_context(db, q, month), active="news")


@router.post("/news/fetch", response_class=HTMLResponse)
def news_fetch(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    result = fetch_rss(db)
    context = news_context(db)
    if result.get("ok"):
        context["notice"] = result.get("message", "")
    else:
        context["error"] = result.get("message", "抓取失败")
    return render_partial(request, "partials/news_content.html", context)


@router.post("/news/digest", response_class=HTMLResponse)
def news_digest(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    message = build_daily_digest(db)
    context = news_context(db)
    context["notice"] = message or "今日暂无可生成简报的资讯"
    return render_partial(request, "partials/news_content.html", context)


@router.post("/news/items/{item_id}/summarize", response_class=HTMLResponse)
def news_summarize(item_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    item = db.get(NewsItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资讯不存在")
    refresh_news_summary(db, item)
    db.refresh(item)
    return render_partial(request, "partials/news_item.html", {"item": item})
