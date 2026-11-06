"""SQLite 幂等增量迁移：只做可空/带默认值的加列，保留既有数据。"""

import json

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from src.core.db import SessionLocal, engine
from src.core.logging import get_logger
from src.core.tags import all_task_tags, ensure_tags, normalize_single_tag
from src.models import Book, Category, LearningItem, Paper, Task
from src.models.legacy import LegacyTimeTask

logger = get_logger(__name__)

# table -> [(column, DDL type and default)]
COLUMNS: dict[str, list[tuple[str, str]]] = {
    "tasks": [
        ("date_mode", "VARCHAR(20) DEFAULT 'deadline'"),
        ("planned_date", "DATE"),
        ("range_start", "DATE"),
        ("range_end", "DATE"),
        ("progress", "INTEGER DEFAULT 0"),
        ("start_at", "DATETIME"),
        ("end_at", "DATETIME"),
        ("duration_seconds", "INTEGER DEFAULT 0"),
        ("client_token", "VARCHAR(64)"),
        ("source_time_task_id", "INTEGER"),
    ],
    "papers": [
        ("title_zh", "VARCHAR(500) DEFAULT ''"),
        ("favorite", "BOOLEAN DEFAULT 0"),
        ("read_at", "DATETIME"),
    ],
    "books": [
        ("category", "VARCHAR(60) DEFAULT ''"),
        ("tags", "VARCHAR(200) DEFAULT ''"),
        ("finished_at", "DATETIME"),
    ],
    "news_items": [
        ("summary_zh", "TEXT DEFAULT ''"),
        ("title_zh", "VARCHAR(500) DEFAULT ''"),
        ("comment_url", "VARCHAR(800) DEFAULT ''"),
        ("favorite", "BOOLEAN DEFAULT 0"),
    ],
    "learning_tracks": [("guide_urls", "TEXT DEFAULT '[]'")],
    "learning_items": [("resource_urls", "TEXT DEFAULT '[]'")],
    "places": [
        ("date_mode", "VARCHAR(20) DEFAULT 'single'"),
        ("visit_end_date", "DATE"),
        ("rating", "INTEGER DEFAULT 0"),
        ("category", "VARCHAR(60) DEFAULT ''"),
        ("tags", "VARCHAR(200) DEFAULT ''"),
    ],
    "trip_plans": [
        ("category", "VARCHAR(60) DEFAULT ''"),
        ("tags", "VARCHAR(200) DEFAULT ''"),
    ],
}

CATEGORY_PRESETS = {
    "book": ["技术", "文学", "历史", "成长"],
    "place": ["自然景点", "人文古迹", "美食探店", "娱乐"],
    "trip": ["周末短途", "长途旅行", "城市漫步"],
}


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in COLUMNS.items():
            if table not in existing_tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in existing:
                    continue
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
                logger.info("迁移：%s 新增列 %s", table, name)


def _migrate_time_tasks(db: Session) -> None:
    """把旧日程时间模块的 time_tasks 数据搬进统一 Task，避免历史记录丢失。"""
    for legacy in db.scalars(select(LegacyTimeTask)).all():
        exists = db.scalar(select(Task).where(Task.source_time_task_id == legacy.id))
        if exists is not None:
            continue
        done = not legacy.is_planned
        planned = legacy.planned_date or (legacy.start_at.date() if legacy.start_at else None)
        token = legacy.client_token or None
        if token and db.scalar(select(Task).where(Task.client_token == token)) is not None:
            token = None
        db.add(
            Task(
                title=(legacy.title or "未命名任务")[:200],
                description=legacy.note or "",
                status="done" if done else "todo",
                date_mode="single" if planned else "deadline",
                planned_date=planned,
                start_at=legacy.start_at,
                end_at=legacy.end_at,
                duration_seconds=legacy.duration_seconds or 0,
                completed_at=legacy.completed_at if done else None,
                client_token=token,
                source_time_task_id=legacy.id,
                tags="",
            )
        )
    db.flush()
    logger.info("迁移：旧时间任务已并入统一任务表")


def _backfill() -> None:
    with SessionLocal() as db:
        for item in db.scalars(select(LearningItem)).all():
            has_urls = item.resource_urls and item.resource_urls != "[]"
            if not has_urls and item.resource_url:
                item.resource_urls = json.dumps([item.resource_url], ensure_ascii=False)
        for paper in db.scalars(select(Paper)).all():
            if paper.read_status == "read" and paper.read_at is None:
                paper.read_at = paper.fetched_at
        for book in db.scalars(select(Book)).all():
            if book.status == "finished" and book.finished_at is None:
                book.finished_at = book.created_at
        for task in db.scalars(select(Task)).all():
            if task.due_date and not task.date_mode:
                task.date_mode = "deadline"
            single = normalize_single_tag(task.tags)
            if single != (task.tags or ""):
                task.tags = single

        _migrate_time_tasks(db)
        ensure_tags(db, all_task_tags(db))

        existing = {(row.scope, row.name) for row in db.scalars(select(Category)).all()}
        for scope, names in CATEGORY_PRESETS.items():
            for name in names:
                if (scope, name) not in existing:
                    db.add(Category(scope=scope, name=name))
        db.commit()


def run_migrations() -> None:
    _add_missing_columns()
    _backfill()
