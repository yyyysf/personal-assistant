"""首页仪表盘统计：聚合各业务板块数据，供页面与 JSON API 共用。"""

import calendar
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.core.time_utils import (
    days_ago,
    now,
    streak_days,
    today,
    week_end_dt,
    week_start,
    week_start_dt,
)
from src.models import (
    Book,
    Journey,
    LearningItem,
    LearningLog,
    LearningTrack,
    NewsDigest,
    NewsItem,
    Paper,
    Place,
    ReadingNote,
    Task,
    WeeklyReview,
)

PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
STATUS_LABELS = {"todo": "待办", "doing": "进行中", "done": "已完成"}
CATEGORY_LABELS = {"video": "AI 视频学习", "music": "AI 音乐学习"}


def _count(db: Session, model: type, *criteria) -> int:
    stmt = select(func.count()).select_from(model)
    if criteria:
        stmt = stmt.where(*criteria)
    return int(db.scalar(stmt) or 0)


def activity_counts(db: Session, start: date, end: date) -> dict[date, int]:
    """统计时间区间内每天的任务 / 学习完成数量。"""
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end + timedelta(days=1), time.min)
    counts: dict[date, int] = {}

    task_dates = db.scalars(
        select(Task.completed_at).where(
            Task.completed_at.is_not(None),
            Task.completed_at >= start_dt,
            Task.completed_at < end_dt,
        )
    ).all()
    for completed_at in task_dates:
        if completed_at:
            counts[completed_at.date()] = counts.get(completed_at.date(), 0) + 1

    learning_dates = db.scalars(
        select(LearningItem.completed_at).where(
            LearningItem.completed_at.is_not(None),
            LearningItem.completed_at >= start_dt,
            LearningItem.completed_at < end_dt,
        )
    ).all()
    for completed_at in learning_dates:
        if completed_at:
            counts[completed_at.date()] = counts.get(completed_at.date(), 0) + 1

    for column in (Paper.read_at, Book.finished_at):
        stamps = db.scalars(
            select(column).where(
                column.is_not(None),
                column >= start_dt,
                column < end_dt,
            )
        ).all()
        for stamp in stamps:
            if stamp:
                counts[stamp.date()] = counts.get(stamp.date(), 0) + 1

    visit_dates = db.scalars(
        select(Place.visit_date).where(
            Place.visit_date.is_not(None),
            Place.visit_date.between(start, end),
        )
    ).all()
    for visit_date in visit_dates:
        if visit_date:
            counts[visit_date] = counts.get(visit_date, 0) + 1

    return counts


def streak(db: Session) -> int:
    start = days_ago(365)
    counts = activity_counts(db, start, today())
    return streak_days(set(counts.keys()))


def monthly_heatmap(db: Session, year: int, month: int) -> list[dict]:
    """当前月热力日历，周一为一周起点，补齐前后共 42 格。"""
    first_day = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)
    counts = activity_counts(db, first_day, last_day)

    grid_start = first_day - timedelta(days=first_day.weekday())
    cells: list[dict] = []
    for offset in range(42):
        cell_date = grid_start + timedelta(days=offset)
        cells.append(
            {
                "date": cell_date,
                "day": cell_date.day,
                "count": counts.get(cell_date, 0),
                "in_month": cell_date.month == month,
                "is_today": cell_date == today(),
                "is_future": cell_date > today(),
            }
        )
    return cells


def week_completion(db: Session) -> dict:
    start = week_start()
    start_dt = week_start_dt()
    end_dt = week_end_dt()

    considered = db.scalars(
        select(Task).where(
            Task.archived.is_(False),
            or_(
                Task.completed_at.between(start_dt, end_dt - timedelta(seconds=1)),
                Task.created_at.between(start_dt, end_dt - timedelta(seconds=1)),
                Task.due_date.between(start_dt, end_dt - timedelta(seconds=1)),
            ),
        )
    ).all()
    total = len(considered)
    done = sum(1 for task in considered if task.status == "done")
    rate = round(done * 100 / total) if total else 0
    return {"rate": rate, "done": done, "total": total, "week_start": start}


def learning_summary(db: Session) -> dict:
    """视频与音乐合并为一个学习视图，进度按全部学习项掌握度加权。"""
    tracks = db.scalars(select(LearningTrack).order_by(LearningTrack.id)).all()
    items = [item for track in tracks for item in track.items]
    total = len(items)
    progress = round(sum(item.mastery for item in items) / total) if total else 0
    today_items = [
        item for item in items if item.scheduled_date == today() and item.status != "done"
    ]
    open_items = sorted(
        [item for item in items if item.status != "done"],
        key=lambda item: (item.scheduled_date is None, item.scheduled_date or date.max, item.id),
    )
    return {
        "label": "业余学习",
        "progress": progress,
        "today_items": today_items,
        "open_items": open_items[:6],
        "done_count": sum(1 for item in items if item.status == "done"),
        "total_count": total,
        "tracks": [
            {
                "category": track.category,
                "label": track.title or CATEGORY_LABELS.get(track.category, track.category),
                "progress": track.progress,
                "done_count": sum(1 for item in track.items if item.status == "done"),
                "total_count": len(track.items),
            }
            for track in tracks
        ],
    }


def ring_data(db: Session) -> list[dict]:
    tasks_total = _count(db, Task, Task.archived.is_(False))
    tasks_done = _count(db, Task, Task.archived.is_(False), Task.status == "done")
    papers_total = _count(db, Paper)
    papers_read = _count(db, Paper, Paper.read_status == "read")
    books_total = _count(db, Book)
    books_done = _count(db, Book, Book.status == "finished")
    places_total = _count(db, Place)
    places_visited = _count(db, Place, Place.point_status == "visited")
    learning = learning_summary(db)

    def pct(done: int, total: int) -> int:
        return round(done * 100 / total) if total else 0

    return [
        {
            "key": "todo",
            "label": "任务完成",
            "value": pct(tasks_done, tasks_total),
            "detail": f"{tasks_done}/{tasks_total}",
        },
        {
            "key": "research",
            "label": "论文阅读",
            "value": pct(papers_read, papers_total),
            "detail": f"{papers_read}/{papers_total}",
        },
        {
            "key": "learning",
            "label": "业余学习",
            "value": learning["progress"],
            "detail": f"{learning['done_count']}/{learning['total_count']} 项完成",
        },
        {
            "key": "reading",
            "label": "书单阅读",
            "value": pct(books_done, books_total),
            "detail": f"{books_done}/{books_total}",
        },
        {
            "key": "travel",
            "label": "旅行足迹",
            "value": pct(places_visited, places_total),
            "detail": f"{places_visited}/{places_total}",
        },
    ]


def track_summary(db: Session, category: str) -> dict:
    track = db.scalar(select(LearningTrack).where(LearningTrack.category == category))
    if not track:
        return {
            "category": category,
            "label": CATEGORY_LABELS.get(category, category),
            "progress": 0,
            "today_items": [],
            "open_items": [],
            "done_count": 0,
            "total_count": 0,
            "logs": [],
        }
    items = sorted(track.items, key=lambda item: (item.status == "done", item.id))
    today_items = [item for item in items if item.scheduled_date == today()]
    open_items = [item for item in items if item.status != "done"][:5]
    return {
        "category": category,
        "label": track.title or CATEGORY_LABELS.get(category, category),
        "progress": track.progress,
        "today_items": today_items,
        "open_items": open_items,
        "done_count": sum(1 for item in items if item.status == "done"),
        "total_count": len(items),
        "logs": sorted(track.logs, key=lambda log: log.created_at, reverse=True)[:5],
    }


def today_tasks(db: Session, limit: int = 6) -> list[Task]:
    start_dt = datetime.combine(today(), time.min)
    end_dt = start_dt + timedelta(days=1)
    rows = db.scalars(
        select(Task)
        .where(
            Task.archived.is_(False),
            Task.status != "done",
            or_(
                Task.due_date.between(start_dt, end_dt - timedelta(seconds=1)),
                Task.created_at >= start_dt,
                Task.due_date.is_(None),
            ),
        )
        .order_by(Task.due_date.is_(None), Task.due_date, Task.id.desc())
        .limit(limit)
    ).all()
    return list(rows)


def today_papers(db: Session, limit: int = 5) -> list[Paper]:
    start_dt = datetime.combine(today(), time.min)
    rows = db.scalars(
        select(Paper)
        .where(Paper.fetched_at >= start_dt)
        .order_by(Paper.fetched_at.desc())
        .limit(limit)
    ).all()
    return list(rows)


def latest_review(db: Session) -> WeeklyReview | None:
    return db.scalar(select(WeeklyReview).order_by(WeeklyReview.created_at.desc()).limit(1))


def weekly_review_payload(db: Session) -> dict:
    """汇总本周所有记录，交给 LLM 生成复盘。"""
    start_dt = week_start_dt()
    end_dt = week_end_dt()
    tasks_done = db.scalars(
        select(Task).where(
            Task.completed_at.is_not(None),
            Task.completed_at >= start_dt,
            Task.completed_at < end_dt,
        )
    ).all()
    tasks_pending = db.scalars(
        select(Task).where(Task.status != "done", Task.archived.is_(False))
    ).all()
    learning_done = db.scalars(
        select(LearningItem).where(
            LearningItem.completed_at.is_not(None),
            LearningItem.completed_at >= start_dt,
            LearningItem.completed_at < end_dt,
        )
    ).all()
    logs = db.scalars(
        select(LearningLog)
        .where(LearningLog.created_at >= start_dt)
        .order_by(LearningLog.created_at.desc())
    ).all()
    papers_read = db.scalars(
        select(Paper).where(Paper.read_status == "read").order_by(Paper.fetched_at.desc()).limit(8)
    ).all()
    books = db.scalars(
        select(Book)
        .where(Book.status.in_(["reading", "finished"]))
        .order_by(Book.created_at.desc())
    ).all()
    news_week = _count(db, NewsItem, NewsItem.fetched_at >= start_dt)
    completion = week_completion(db)

    return {
        "week_start": week_start(),
        "completion": completion,
        "tasks_done": [
            {"title": task.title, "priority": PRIORITY_LABELS.get(task.priority, task.priority)}
            for task in tasks_done
        ],
        "tasks_pending": [
            {"title": task.title, "status": STATUS_LABELS.get(task.status, task.status)}
            for task in tasks_pending[:10]
        ],
        "learning_done": [item.title for item in learning_done],
        "learning_logs": [log.content for log in logs[:10]],
        "papers": [paper.title for paper in papers_read],
        "books": [f"{book.title}（{book.status}）" for book in books],
        "news_count": news_week,
        "streak": streak(db),
    }


def dashboard_context(db: Session) -> dict:
    """一次性组装首页所需全部数据。"""
    completion = week_completion(db)
    current = today()
    today_dt_start = datetime.combine(current, time.min)
    today_done = activity_counts(db, current, current).get(current, 0)
    learning = learning_summary(db)

    papers = today_papers(db)
    research_stats = {
        "today": _count(db, Paper, Paper.fetched_at >= today_dt_start),
        "total": _count(db, Paper),
        "read": _count(db, Paper, Paper.read_status == "read"),
        "imported": _count(db, Paper, Paper.imported_to_zotero.is_(True)),
    }
    book_stats = {
        "total": _count(db, Book),
        "want": _count(db, Book, Book.status == "want"),
        "reading": _count(db, Book, Book.status == "reading"),
        "finished": _count(db, Book, Book.status == "finished"),
    }
    news_today = db.scalars(
        select(NewsItem)
        .where(NewsItem.fetched_at >= today_dt_start)
        .order_by(NewsItem.published_at.desc())
        .limit(5)
    ).all()
    travel_cost = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    Journey.cost_transport
                    + Journey.cost_lodging
                    + Journey.cost_food
                    + Journey.cost_other
                ),
                0,
            )
        )
    )
    travel_stats = {
        "places": _count(db, Place),
        "want": _count(db, Place, Place.point_status == "want"),
        "visited": _count(db, Place, Place.point_status == "visited"),
        "journeys": _count(db, Journey),
        "journey_want": _count(db, Journey, Journey.status == "want"),
        "journey_visited": _count(db, Journey, Journey.status == "visited"),
        "cost_total": int(travel_cost or 0),
    }
    todo_stats = {
        "open": _count(db, Task, Task.archived.is_(False), Task.status != "done"),
        "done_total": _count(db, Task, Task.status == "done"),
        "archived": _count(db, Task, Task.archived.is_(True)),
    }
    return {
        "stats": {
            "completion_rate": completion["rate"],
            "done_total": todo_stats["done_total"],
            "today_done": today_done,
            "streak": streak(db),
        },
        "completion": completion,
        "heatmap": monthly_heatmap(db, current.year, current.month),
        "month_label": f"{current.year} 年 {current.month} 月",
        "rings": ring_data(db),
        "focus": {
            "tasks": today_tasks(db),
            "papers": papers[:3],
            "video": track_summary(db, "video"),
            "music": track_summary(db, "music"),
            "learning": learning,
        },
        "research": {
            "papers": papers,
            "stats": research_stats,
        },
        "learning": learning,
        "video": track_summary(db, "video"),
        "music": track_summary(db, "music"),
        "reading": {
            "books": db.scalars(select(Book).order_by(Book.created_at.desc()).limit(5)).all(),
            "notes": db.scalars(
                select(ReadingNote).order_by(ReadingNote.created_at.desc()).limit(4)
            ).all(),
            "stats": book_stats,
        },
        "news": {
            "items": list(news_today),
            "digest": db.scalar(
                select(NewsDigest).order_by(NewsDigest.digest_date.desc()).limit(1)
            ),
            "total": _count(db, NewsItem),
        },
        "travel": {
            "places": db.scalars(
                select(Place).order_by(Place.visited.desc(), Place.id.desc()).limit(6)
            ).all(),
            "journeys": db.scalars(select(Journey).order_by(Journey.id.desc()).limit(4)).all(),
            "stats": travel_stats,
        },
        "todo": {
            "today": today_tasks(db),
            "stats": todo_stats,
        },
        "review": latest_review(db),
        "generated_at": now(),
        "labels": {"priority": PRIORITY_LABELS, "status": STATUS_LABELS},
    }
