"""分类与标签辅助：scope 到实体映射、标签聚合、分类重命名与删除同步。"""

from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from src.models import Book, Category, Goal, Paper, Place, Task, TripPlan

CATEGORY_MODEL = {
    "task": Task,
    "goal": Goal,
    "book": Book,
    "place": Place,
    "trip": TripPlan,
}

TAG_MODEL = {
    "task": Task,
    "goal": Goal,
    "book": Book,
    "paper": Paper,
    "place": Place,
    "trip": TripPlan,
}

SCOPE_LABELS = {
    "task": "任务",
    "goal": "目标",
    "book": "书籍",
    "paper": "论文",
    "place": "足迹",
    "trip": "行程",
}


def category_names(db: Session, scope: str) -> list[str]:
    if scope not in CATEGORY_MODEL:
        return []
    rows = db.scalars(select(Category).where(Category.scope == scope).order_by(Category.id))
    return [row.name for row in rows]


def all_tags(db: Session, scope: str) -> list[str]:
    model = TAG_MODEL.get(scope)
    if model is None:
        return []
    values = db.scalars(select(model.tags)).all()
    return sorted({tag.strip() for raw in values for tag in (raw or "").split(",") if tag.strip()})


def rename_category(db: Session, scope: str, old_name: str, new_name: str) -> None:
    model = CATEGORY_MODEL.get(scope)
    if model is None or not new_name.strip() or old_name == new_name:
        return
    rows = db.scalars(select(model).where(model.category == old_name)).all()
    for row in rows:
        row.category = new_name


def clear_category(db: Session, scope: str, name: str) -> None:
    model = CATEGORY_MODEL.get(scope)
    if model is None:
        return
    rows = db.scalars(select(model).where(model.category == name)).all()
    for row in rows:
        row.category = ""


def tag_filter(column, tag: str):
    """按逗号边界匹配标签，避免 AI 命中 OpenAI。"""
    return (literal(",") + column + literal(",")).like(f"%,{tag.strip()},%")
