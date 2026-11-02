"""AI & 计算机前沿资讯日报：RSS 聚合、LLM 简报、时间线与搜索。"""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.config import settings
from src.llm.assistant import translate_news_bilingual
from src.models import FeedSource, NewsDigest, NewsItem
from src.scheduler.fetchers import build_daily_digest, fetch_rss

router = APIRouter()
REFRESH = {"HX-Trigger": '{"list:refresh": true}'}
MODAL_DONE = {"HX-Trigger": '{"modal:close": true, "list:refresh": true}'}


def _stats(db: Session) -> dict:
    return {
        "total": db.scalar(select(func.count()).select_from(NewsItem)) or 0,
        "favorite": db.scalar(
            select(func.count()).select_from(NewsItem).where(NewsItem.favorite.is_(True))
        )
        or 0,
        "sources": db.scalar(select(func.count(func.distinct(NewsItem.source)))) or 0,
        "digests": db.scalar(select(func.count()).select_from(NewsDigest)) or 0,
    }


def _filter_items(stmt, source: str, favorite: str, date_from: str, date_to: str, q: str):
    if source:
        stmt = stmt.where(NewsItem.source == source)
    if favorite:
        stmt = stmt.where(NewsItem.favorite.is_(True))
    start_date = parse_date(date_from)
    end_date = parse_date(date_to)
    published = func.coalesce(NewsItem.published_at, NewsItem.fetched_at)
    if start_date:
        stmt = stmt.where(func.date(published) >= start_date.isoformat())
    if end_date:
        stmt = stmt.where(func.date(published) <= end_date.isoformat())
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                NewsItem.title.ilike(pattern),
                NewsItem.title_zh.ilike(pattern),
                NewsItem.summary.ilike(pattern),
                NewsItem.summary_zh.ilike(pattern),
                NewsItem.source.ilike(pattern),
            )
        )
    return stmt


def news_context(
    db: Session,
    source: str = "",
    favorite: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page: int = 1,
    digest_page: int = 1,
) -> dict:
    stmt = _filter_items(select(NewsItem), source, favorite, date_from, date_to, q)
    page_data = paginate(
        db,
        stmt.order_by(
            func.coalesce(NewsItem.published_at, NewsItem.fetched_at).desc(), NewsItem.id.desc()
        ),
        page,
    )

    grouped: dict[date, list[NewsItem]] = {}
    for item in page_data["items"]:
        key = (item.published_at or item.fetched_at).date()
        grouped.setdefault(key, []).append(item)
    timeline = [
        {"date": key, "entries": entries} for key, entries in sorted(grouped.items(), reverse=True)
    ]

    digest_page_data = paginate(
        db, select(NewsDigest).order_by(NewsDigest.digest_date.desc()), digest_page
    )
    latest_digest = db.scalar(select(NewsDigest).order_by(NewsDigest.digest_date.desc()).limit(1))

    return {
        "timeline": timeline,
        "page_data": page_data,
        "digest_page": digest_page_data,
        "latest_digest": latest_digest,
        "sources": db.scalars(select(NewsItem.source).distinct().order_by(NewsItem.source)).all(),
        "feed_sources": db.scalars(select(FeedSource).order_by(FeedSource.id)).all(),
        "stats": _stats(db),
        "filters": {
            "source": source,
            "favorite": favorite,
            "date_from": date_from,
            "date_to": date_to,
            "q": q,
        },
        "notice": "",
        "error": "",
    }


def _content_response(
    request: Request,
    db: Session,
    source: str = "",
    favorite: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page: int = 1,
    digest_page: int = 1,
    notice: str = "",
    error: str = "",
) -> HTMLResponse:
    context = news_context(
        db,
        source=source,
        favorite=favorite,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        digest_page=digest_page,
    )
    context["notice"] = notice
    context["error"] = error
    return render_partial(request, "partials/news_content.html", context)


def _get_item(db: Session, item_id: int) -> NewsItem:
    item = db.get(NewsItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资讯不存在")
    return item


def _ensure_chinese(db: Session, item: NewsItem) -> None:
    if item.title_zh and item.summary_zh:
        return
    title_zh, summary_zh = translate_news_bilingual(item.title, item.source, item.summary)
    if not title_zh and not summary_zh:
        return
    item.title_zh = (title_zh or item.title_zh)[:500]
    item.summary_zh = summary_zh or item.summary_zh
    db.commit()


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request,
    source: str = "",
    favorite: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page: int = 1,
    digest_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = news_context(
        db,
        source=source,
        favorite=favorite,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        digest_page=digest_page,
    )
    return render(request, "news.html", context, active="news")


@router.get("/news/content", response_class=HTMLResponse)
def news_content(
    request: Request,
    source: str = "",
    favorite: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page: int = 1,
    digest_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(
        request,
        db,
        source=source,
        favorite=favorite,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        digest_page=digest_page,
    )


@router.post("/news/fetch", response_class=HTMLResponse)
def news_fetch(
    request: Request,
    source: str = Form(""),
    favorite: str = Form(""),
    date_from: str = Form(""),
    date_to: str = Form(""),
    q: str = Form(""),
    page: int = Form(1),
    digest_page: int = Form(1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    result = fetch_rss(db)
    return _content_response(
        request,
        db,
        source=source,
        favorite=favorite,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        digest_page=digest_page,
        notice=result.get("message", "") if result.get("ok") else "",
        error="" if result.get("ok") else result.get("message", "抓取失败"),
    )


@router.post("/news/digest", response_class=HTMLResponse)
def news_digest(
    request: Request,
    source: str = Form(""),
    favorite: str = Form(""),
    date_from: str = Form(""),
    date_to: str = Form(""),
    q: str = Form(""),
    page: int = Form(1),
    digest_page: int = Form(1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    message = build_daily_digest(db)
    return _content_response(
        request,
        db,
        source=source,
        favorite=favorite,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        digest_page=digest_page,
        notice=message or "今日暂无可生成简报的资讯",
    )


@router.get("/news/items/{item_id}/detail", response_class=HTMLResponse)
def news_item_detail(item_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    item = _get_item(db, item_id)
    _ensure_chinese(db, item)
    return render_partial(request, "partials/modals/news_detail.html", {"item": item})


@router.post("/news/items/{item_id}/summarize", response_class=HTMLResponse)
def news_summarize(item_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    item = _get_item(db, item_id)
    title_zh, summary_zh = translate_news_bilingual(item.title, item.source, item.summary)
    if title_zh or summary_zh:
        item.title_zh = (title_zh or item.title_zh)[:500]
        item.summary_zh = summary_zh or item.summary_zh
        db.commit()
    db.refresh(item)
    return render_partial(request, "partials/modals/news_detail.html", {"item": item})


@router.post("/news/items/{item_id}/favorite", response_class=HTMLResponse)
def news_toggle_favorite(item_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    item = _get_item(db, item_id)
    item.favorite = not item.favorite
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/news/items/{item_id}/delete", response_class=HTMLResponse)
def news_delete(item_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    item = _get_item(db, item_id)
    db.delete(item)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/news/digests/{digest_id}/detail", response_class=HTMLResponse)
def news_digest_detail(
    digest_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    digest = db.get(NewsDigest, digest_id)
    if digest is None:
        raise HTTPException(status_code=404, detail="简报不存在")
    return render_partial(request, "partials/modals/news_digest_detail.html", {"digest": digest})


def _sources_context(db: Session, error: str = "") -> dict:
    return {
        "feed_sources": db.scalars(select(FeedSource).order_by(FeedSource.id)).all(),
        "env_feeds": settings.rss_feed_list,
        "error": error,
    }


@router.get("/news/sources", response_class=HTMLResponse)
def news_sources(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/news_sources.html", _sources_context(db))


def _clean_source(name: str, url: str, enabled: bool) -> tuple[str, str, bool]:
    return name.strip()[:120], url.strip()[:800], enabled


def _source_error(db: Session, url: str, exclude_id: int | None = None) -> str:
    if not url:
        return "订阅地址不能为空"
    if not url.lower().startswith(("http://", "https://")):
        return "订阅地址需要以 http:// 或 https:// 开头"
    stmt = select(FeedSource).where(FeedSource.url == url)
    if exclude_id is not None:
        stmt = stmt.where(FeedSource.id != exclude_id)
    if db.scalar(stmt.limit(1)) is not None:
        return "这个订阅地址已经存在"
    return ""


@router.post("/news/sources/new", response_class=HTMLResponse)
def news_source_create(
    request: Request,
    name: str = Form(""),
    url: str = Form(""),
    enabled: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    name, url, enabled_flag = _clean_source(name, url, bool(enabled))
    error = _source_error(db, url)
    if error:
        return render_partial(
            request, "partials/modals/news_sources.html", _sources_context(db, error)
        )
    db.add(FeedSource(name=name or url, url=url, enabled=enabled_flag))
    db.commit()
    return render_partial(request, "partials/modals/news_sources.html", _sources_context(db))


@router.post("/news/sources/{source_id}/edit", response_class=HTMLResponse)
def news_source_update(
    source_id: int,
    request: Request,
    name: str = Form(""),
    url: str = Form(""),
    enabled: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    source = db.get(FeedSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="订阅源不存在")
    name, url, enabled_flag = _clean_source(name, url, bool(enabled))
    error = _source_error(db, url, exclude_id=source.id)
    if error:
        return render_partial(
            request, "partials/modals/news_sources.html", _sources_context(db, error)
        )
    source.name = name or url
    source.url = url
    source.enabled = enabled_flag
    db.commit()
    return render_partial(request, "partials/modals/news_sources.html", _sources_context(db))


@router.post("/news/sources/{source_id}/delete", response_class=HTMLResponse)
def news_source_delete(
    source_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    source = db.get(FeedSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="订阅源不存在")
    db.delete(source)
    db.commit()
    return render_partial(request, "partials/modals/news_sources.html", _sources_context(db))
