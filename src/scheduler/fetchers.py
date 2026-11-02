"""论文与 RSS 抓取：网络失败只记录日志，不阻塞服务。"""

import re
from datetime import datetime
from typing import Any

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.logging import get_logger
from src.core.time_utils import today
from src.llm.assistant import (
    generate_daily_digest,
    suggest_tags,
    summarize_news,
    summarize_paper_bilingual,
)
from src.models import FeedSource, NewsDigest, NewsItem, Paper

logger = get_logger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = "MyPrivateAssistant/0.1 (personal research helper)"
LLM_SUMMARY_LIMIT = 8
MAX_RSS_PER_FEED = 12


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        parsed = datetime(*value[:6])
        return parsed
    except (TypeError, ValueError):
        return None


def fetch_arxiv(db: Session, max_results: int | None = None) -> dict:
    categories = settings.arxiv_category_list or ["cs.AI"]
    query = " OR ".join(f"cat:{category}" for category in categories)
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results or settings.arxiv_max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        response = httpx.get(
            ARXIV_API,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("arXiv 抓取失败：%s", exc)
        return {"ok": False, "message": f"arXiv 抓取失败：{exc}", "created": 0}

    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        return {"ok": False, "message": "arXiv 返回内容无法解析", "created": 0}

    existing_ids = set(db.scalars(select(Paper.arxiv_id)).all())
    created = 0
    llm_budget = LLM_SUMMARY_LIMIT
    for entry in feed.entries:
        raw_id = str(entry.get("id", ""))
        arxiv_id = raw_id.rsplit("/", 1)[-1].split("v")[0]
        if not arxiv_id or arxiv_id in existing_ids:
            continue
        title = _clean(entry.get("title", "未命名论文"))
        abstract = _clean(entry.get("summary", ""))
        authors = ", ".join(_clean(author.get("name", "")) for author in entry.get("authors", []))[
            :500
        ]
        published = _parse_dt(entry.get("published_parsed"))
        link = str(entry.get("link", raw_id))
        title_zh = ""
        if llm_budget > 0:
            title_zh, summary = summarize_paper_bilingual(title, abstract, authors)
            tags = suggest_tags(title, abstract)
            llm_budget -= 1
        else:
            summary = abstract[:300] + ("…" if len(abstract) > 300 else "")
            tags = "arXiv,cs.AI"

        db.add(
            Paper(
                arxiv_id=arxiv_id,
                title=title,
                title_zh=title_zh,
                authors=authors,
                abstract=abstract,
                summary=summary,
                url=link,
                published_at=published,
                fetched_at=datetime.now(),
                tags=tags[:200],
                published_date=published.date() if published else None,
            )
        )
        existing_ids.add(arxiv_id)
        created += 1

    db.commit()
    logger.info("arXiv 抓取完成：新增 %s 篇", created)
    return {
        "ok": True,
        "created": created,
        "fetched": len(feed.entries),
        "message": f"arXiv 抓取完成，新增 {created} 篇论文",
    }


def _comment_url(entry: Any) -> str:
    direct = entry.get("comments") or entry.get("comment_url")
    if direct:
        return str(direct)
    for link in entry.get("links", []) or []:
        if link.get("rel") in {"replies", "reply"}:
            return str(link.get("href", ""))
    return ""


def _feed_items(feed: Any, source: str) -> list[dict]:
    items = []
    for entry in feed.entries[:MAX_RSS_PER_FEED]:
        link = str(entry.get("link", ""))
        title = _clean(entry.get("title", ""))
        if not link or not title:
            continue
        content = entry.get("summary", "") or entry.get("description", "")
        items.append(
            {
                "source": source,
                "title": title[:500],
                "link": link[:800],
                "comment_url": _comment_url(entry)[:800],
                "raw_summary": _clean(content)[:1500],
                "published_at": _parse_dt(entry.get("published_parsed")),
            }
        )
    return items


def _feed_urls(db: Session) -> list[str]:
    db_urls = db.scalars(select(FeedSource.url).where(FeedSource.enabled.is_(True))).all()
    return list(dict.fromkeys([*settings.rss_feed_list, *db_urls]))


def fetch_rss(db: Session) -> dict:
    feeds = _feed_urls(db)
    if not feeds:
        return {"ok": False, "message": "未配置 RSS 订阅源", "created": 0}

    existing_links = set(db.scalars(select(NewsItem.link)).all())
    created = 0
    failures: list[str] = []

    for url in feeds:
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=25,
                follow_redirects=True,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            source = _clean(feed.feed.get("title", url))[:100]
            for item in _feed_items(feed, source):
                if item["link"] in existing_links:
                    continue
                summary = item["raw_summary"][:300]
                db.add(
                    NewsItem(
                        source=item["source"],
                        title=item["title"],
                        link=item["link"],
                        summary=summary,
                        comment_url=item["comment_url"],
                        published_at=item["published_at"],
                        fetched_at=datetime.now(),
                        digest_date=today(),
                    )
                )
                existing_links.add(item["link"])
                created += 1
        except httpx.HTTPError as exc:
            logger.warning("RSS 抓取失败 [%s]：%s", url, exc)
            failures.append(url)

    db.commit()

    digest_message = ""
    if created:
        digest_message = build_daily_digest(db)

    message = f"RSS 聚合完成，新增 {created} 条资讯"
    if failures:
        message += f"，{len(failures)} 个源抓取失败"
    return {
        "ok": True,
        "created": created,
        "failures": failures,
        "message": message + (f"；{digest_message}" if digest_message else ""),
    }


def build_daily_digest(db: Session) -> str:
    start = datetime.combine(today(), datetime.min.time())
    items = db.scalars(
        select(NewsItem)
        .where(NewsItem.fetched_at >= start)
        .order_by(NewsItem.published_at.desc())
        .limit(8)
    ).all()
    if not items:
        return ""
    payload = [
        {
            "source": item.source,
            "title": item.display_title,
            "summary": item.display_summary,
        }
        for item in items
    ]
    content = generate_daily_digest(payload)
    title = f"{today().month} 月 {today().day} 日 AI 前沿简报"
    digest = db.scalar(select(NewsDigest).where(NewsDigest.digest_date == today()))
    if digest:
        digest.title = title
        digest.content = content
        digest.item_count = len(items)
    else:
        db.add(
            NewsDigest(
                digest_date=today(),
                title=title,
                content=content,
                item_count=len(items),
            )
        )
    db.commit()
    return "今日简报已更新"


def refresh_news_summary(db: Session, item: NewsItem) -> str:
    """按需为单条资讯生成 LLM 精简摘要。"""
    summary = summarize_news(item.title, item.source, item.summary)
    item.summary = summary
    db.commit()
    return summary
