"""SQLite 幂等增量迁移：只做可空/带默认值的加列，保留既有数据。"""

import json

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from src.core.db import SessionLocal, engine
from src.core.logging import get_logger
from src.core.tags import all_task_tags, ensure_tags, normalize_single_tag
from src.models import Book, Category, LearningItem, Paper, Place, Task
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
        ("amap_poi_id", "VARCHAR(64) DEFAULT ''"),
        ("standard_address", "VARCHAR(255) DEFAULT ''"),
        ("point_status", "VARCHAR(10) DEFAULT 'want'"),
        ("point_category", "VARCHAR(20) DEFAULT ''"),
        ("source_note_url", "VARCHAR(600) DEFAULT ''"),
        ("sort_order", "INTEGER DEFAULT 0"),
    ],
    "journeys": [
        ("status", "VARCHAR(10) DEFAULT 'want'"),
        ("mood", "VARCHAR(20) DEFAULT 'normal'"),
        ("description", "TEXT DEFAULT ''"),
        ("cost_transport", "INTEGER DEFAULT 0"),
        ("cost_lodging", "INTEGER DEFAULT 0"),
        ("cost_food", "INTEGER DEFAULT 0"),
        ("cost_other", "INTEGER DEFAULT 0"),
        ("tags", "VARCHAR(200) DEFAULT ''"),
        ("photos", "TEXT DEFAULT '[]'"),
    ],
    "journey_places": [
        ("note", "VARCHAR(300) DEFAULT ''"),
    ],
}

CATEGORY_PRESETS = {
    "book": ["技术", "文学", "历史", "成长"],
    "place": ["景点", "美食", "住宿", "交通", "商场", "娱乐"],
}

LEGACY_POINT_CATEGORY = {
    "自然景点": "景点",
    "人文古迹": "景点",
    "美食探店": "美食",
    "娱乐": "娱乐",
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


def _drop_obsolete_task_columns() -> None:
    """删除旧版 tasks 表遗留的必填列，否则新模型插入会违反 NOT NULL。

    旧版 category 是分类字段，新版统一用 tags；删除前把值并入空标签，避免丢数据。
    """
    inspector = inspect(engine)
    if "tasks" not in inspector.get_table_names():
        return
    model_columns = {column.name for column in Task.__table__.columns}
    obsolete = [
        column["name"]
        for column in inspector.get_columns("tasks")
        if column["name"] not in model_columns and not column["nullable"]
    ]
    if not obsolete:
        return
    with engine.begin() as conn:
        for name in obsolete:
            if name == "category":
                conn.execute(
                    text(
                        'UPDATE "tasks" SET tags = category '
                        "WHERE (tags IS NULL OR tags = '') "
                        "AND category IS NOT NULL AND category != ''"
                    )
                )
            conn.execute(text(f'ALTER TABLE "tasks" DROP COLUMN "{name}"'))
            logger.info("迁移：删除 tasks 遗留必填列 %s", name)


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

        for place in db.scalars(select(Place)).all():
            if place.point_status not in {"want", "visited"}:
                place.point_status = "visited" if place.visited else "want"
            if not place.point_category:
                place.point_category = LEGACY_POINT_CATEGORY.get(place.category, place.category)
            place.visited = place.point_status == "visited"

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
    _drop_obsolete_task_columns()
    _backfill()
