"""ORM 对象到结构化 JSON 的序列化。"""

from typing import Any

from src.models import (
    Book,
    LearningItem,
    LearningLog,
    LearningTrack,
    NewsDigest,
    NewsItem,
    Paper,
    PaperNote,
    Place,
    ReadingNote,
    Task,
    TripPlan,
    WeeklyReview,
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "tags": task.tag_list,
        "date_mode": task.date_mode,
        "date_label": task.date_label,
        "due_date": _iso(task.due_date),
        "planned_date": _iso(task.planned_date),
        "range_start": _iso(task.range_start),
        "range_end": _iso(task.range_end),
        "start_at": _iso(task.start_at),
        "end_at": _iso(task.end_at),
        "duration_seconds": task.duration_seconds,
        "progress": task.progress,
        "completed_at": _iso(task.completed_at),
        "archived": task.archived,
        "created_at": _iso(task.created_at),
    }


def paper_note_to_dict(note: PaperNote) -> dict:
    return {
        "id": note.id,
        "paper_id": note.paper_id,
        "content": note.content,
        "source": note.source,
        "created_at": _iso(note.created_at),
    }


def paper_to_dict(paper: Paper, include_notes: bool = False) -> dict:
    payload = {
        "id": paper.id,
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "title_zh": paper.title_zh,
        "display_title": paper.display_title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "summary": paper.summary,
        "favorite": paper.favorite,
        "read_at": _iso(paper.read_at),
        "url": paper.url,
        "published_at": _iso(paper.published_at),
        "fetched_at": _iso(paper.fetched_at),
        "imported_to_zotero": paper.imported_to_zotero,
        "zotero_item_key": paper.zotero_item_key,
        "tags": [tag for tag in paper.tags.split(",") if tag.strip()],
        "read_status": paper.read_status,
    }
    if include_notes:
        payload["notes"] = [paper_note_to_dict(note) for note in paper.notes]
    return payload


def news_to_dict(item: NewsItem) -> dict:
    return {
        "id": item.id,
        "source": item.source,
        "title": item.title,
        "title_zh": item.title_zh,
        "display_title": item.display_title,
        "link": item.link,
        "summary": item.summary,
        "summary_zh": item.summary_zh,
        "display_summary": item.display_summary,
        "comment_url": item.comment_url,
        "favorite": item.favorite,
        "published_at": _iso(item.published_at),
        "fetched_at": _iso(item.fetched_at),
        "digest_date": _iso(item.digest_date),
    }


def digest_to_dict(digest: NewsDigest) -> dict:
    return {
        "id": digest.id,
        "digest_date": _iso(digest.digest_date),
        "title": digest.title,
        "content": digest.content,
        "item_count": digest.item_count,
        "created_at": _iso(digest.created_at),
    }


def reading_note_to_dict(note: ReadingNote) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "author": note.author,
        "url": note.url,
        "summary": note.summary,
        "cover_url": note.cover_url,
        "source": note.source,
        "created_at": _iso(note.created_at),
    }


def book_to_dict(book: Book) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "status": book.status,
        "category": book.category,
        "tags": book.tag_list,
        "finished_at": _iso(book.finished_at),
        "rating": book.rating,
        "notes": book.notes,
        "resource_url": book.resource_url,
        "recommended_by": book.recommended_by,
        "source_note_id": book.source_note_id,
        "created_at": _iso(book.created_at),
    }


def learning_item_to_dict(item: LearningItem) -> dict:
    return {
        "id": item.id,
        "track_id": item.track_id,
        "title": item.title,
        "description": item.description,
        "resource_url": item.resource_url,
        "resource_urls": item.resource_url_list,
        "status": item.status,
        "mastery": item.mastery,
        "scheduled_date": _iso(item.scheduled_date),
        "completed_at": _iso(item.completed_at),
        "created_at": _iso(item.created_at),
    }


def learning_log_to_dict(log: LearningLog) -> dict:
    return {
        "id": log.id,
        "track_id": log.track_id,
        "content": log.content,
        "mastery": log.mastery,
        "source": log.source,
        "created_at": _iso(log.created_at),
    }


def track_to_dict(track: LearningTrack) -> dict:
    return {
        "id": track.id,
        "category": track.category,
        "title": track.title,
        "description": track.description,
        "guide_urls": track.guide_url_list,
        "progress": track.progress,
        "items": [learning_item_to_dict(item) for item in track.items],
        "logs": [learning_log_to_dict(log) for log in track.logs],
    }


def place_to_dict(place: Place) -> dict:
    return {
        "id": place.id,
        "name": place.name,
        "country": place.country,
        "city": place.city,
        "lat": place.lat,
        "lng": place.lng,
        "visited": place.visited,
        "date_mode": place.date_mode,
        "date_label": place.date_label,
        "visit_date": _iso(place.visit_date),
        "visit_end_date": _iso(place.visit_end_date),
        "rating": place.rating,
        "category": place.category,
        "tags": place.tag_list,
        "photos": place.photo_list,
        "notes": place.notes,
        "created_at": _iso(place.created_at),
    }


def trip_to_dict(trip: TripPlan) -> dict:
    return {
        "id": trip.id,
        "title": trip.title,
        "start_date": _iso(trip.start_date),
        "end_date": _iso(trip.end_date),
        "status": trip.status,
        "category": trip.category,
        "tags": trip.tag_list,
        "itinerary": trip.itinerary,
        "notes": trip.notes,
        "created_at": _iso(trip.created_at),
    }


def review_to_dict(review: WeeklyReview) -> dict:
    return {
        "id": review.id,
        "week_start": _iso(review.week_start),
        "content": review.content,
        "suggestions": review.suggestions,
        "source": review.source,
        "created_at": _iso(review.created_at),
    }


def _track_summary_to_dict(summary: dict | None) -> dict:
    summary = summary or {}
    return {
        "category": summary.get("category"),
        "label": summary.get("label"),
        "progress": summary.get("progress", 0),
        "today_items": [learning_item_to_dict(item) for item in summary.get("today_items") or []],
        "open_items": [learning_item_to_dict(item) for item in summary.get("open_items") or []],
        "done_count": summary.get("done_count", 0),
        "total_count": summary.get("total_count", 0),
        "logs": [learning_log_to_dict(log) for log in summary.get("logs") or []],
    }


def dashboard_to_dict(context: dict) -> dict:
    """把仪表盘上下文中的 ORM 对象与日期统一转换为 JSON 可序列化结构。"""
    completion = context.get("completion") or {}
    focus = context.get("focus") or {}
    research = context.get("research") or {}
    reading = context.get("reading") or {}
    news = context.get("news") or {}
    travel = context.get("travel") or {}
    todo = context.get("todo") or {}
    todo_stats = dict(todo.get("stats") or {})
    review = context.get("review")

    return {
        "stats": context.get("stats", {}),
        "completion": {
            "rate": completion.get("rate", 0),
            "done": completion.get("done", 0),
            "total": completion.get("total", 0),
            "week_start": _iso(completion.get("week_start")),
        },
        "heatmap": [
            {**cell, "date": _iso(cell.get("date"))} for cell in context.get("heatmap", [])
        ],
        "month_label": context.get("month_label", ""),
        "rings": context.get("rings", []),
        "focus": {
            "tasks": [task_to_dict(task) for task in focus.get("tasks") or []],
            "papers": [paper_to_dict(paper) for paper in focus.get("papers") or []],
            "video": _track_summary_to_dict(focus.get("video")),
            "music": _track_summary_to_dict(focus.get("music")),
        },
        "research": {
            "papers": [paper_to_dict(paper) for paper in research.get("papers") or []],
            "stats": research.get("stats", {}),
        },
        "video": _track_summary_to_dict(context.get("video")),
        "music": _track_summary_to_dict(context.get("music")),
        "reading": {
            "books": [book_to_dict(book) for book in reading.get("books") or []],
            "notes": [reading_note_to_dict(note) for note in reading.get("notes") or []],
            "stats": reading.get("stats", {}),
        },
        "news": {
            "items": [news_to_dict(item) for item in news.get("items") or []],
            "digest": digest_to_dict(news["digest"]) if news.get("digest") else None,
            "total": news.get("total", 0),
        },
        "travel": {
            "places": [place_to_dict(place) for place in travel.get("places") or []],
            "trips": [trip_to_dict(trip) for trip in travel.get("trips") or []],
            "stats": travel.get("stats", {}),
        },
        "todo": {
            "today": [task_to_dict(task) for task in todo.get("today") or []],
            "stats": todo_stats,
        },
        "review": review_to_dict(review) if review else None,
        "generated_at": _iso(context.get("generated_at")),
        "labels": context.get("labels", {}),
    }
