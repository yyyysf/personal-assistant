"""SQLite 幂等增量迁移：只做可空/带默认值的加列，保留既有数据。"""

import json

from sqlalchemy import inspect, select, text

from src.core.db import SessionLocal, engine
from src.core.logging import get_logger
from src.models import Book, Category, LearningItem, Paper, Task

logger = get_logger(__name__)

# table -> [(column, DDL type and default)]
COLUMNS: dict[str, list[tuple[str, str]]] = {
    "tasks": [
        ("category", "VARCHAR(60) DEFAULT ''"),
        ("date_mode", "VARCHAR(20) DEFAULT 'deadline'"),
        ("planned_date", "DATE"),
        ("range_start", "DATE"),
        ("range_end", "DATE"),
        ("progress", "INTEGER DEFAULT 0"),
    ],
    "goals": [
        ("category", "VARCHAR(60) DEFAULT ''"),
        ("tags", "VARCHAR(200) DEFAULT ''"),
        ("completed_at", "DATETIME"),
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
    "task": ["科研", "学习", "生活"],
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

        existing = {(row.scope, row.name) for row in db.scalars(select(Category)).all()}
        for scope, names in CATEGORY_PRESETS.items():
            for name in names:
                if (scope, name) not in existing:
                    db.add(Category(scope=scope, name=name))
        db.commit()


def run_migrations() -> None:
    _add_missing_columns()
    _backfill()
