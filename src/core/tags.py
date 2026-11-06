"""标签工具：标准化、马卡龙自动配色、重命名与颜色映射。"""

import re
from collections import Counter
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import DEFAULT_TAG_COLOR, Tag, Task

MACARON_COLORS = [
    "#F4A8A8",
    "#F6C28B",
    "#F2D388",
    "#A8D8B9",
    "#9ED0D8",
    "#A9C7E8",
    "#B8B5E0",
    "#E0B3D4",
    "#D8B4A0",
    "#B5D6C6",
    "#E8C4B8",
    "#C9C9A8",
]
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TAG_MAX_LENGTH = 30
TAGS_MAX_LENGTH = 200


def clean_tag(name: str) -> str:
    return " ".join(name.split())[:TAG_MAX_LENGTH]


def normalize_tags(value: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw in (value or "").split(","):
        name = clean_tag(raw)
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            tags.append(name)
    return tags


def normalize_tag_string(value: str) -> str:
    result: list[str] = []
    for name in normalize_tags(value):
        candidate = ",".join(result + [name])
        if len(candidate) > TAGS_MAX_LENGTH:
            break
        result.append(name)
    return ",".join(result)


def normalize_single_tag(value: str) -> str:
    """每个任务只保留一个标签：取归一化后的第一个。"""
    tags = normalize_tags(value)
    return tags[0] if tags else ""


def normalize_color(value: str) -> str | None:
    color = (value or "").strip()
    return color.lower() if COLOR_RE.match(color) else None


def _pick_color(db: Session) -> str:
    used = Counter(color for color in db.scalars(select(Tag.color)).all() if color)
    best = min(MACARON_COLORS, key=lambda color: (used.get(color, 0), MACARON_COLORS.index(color)))
    return best


def ensure_tags(db: Session, names: Iterable[str] | str) -> list[Tag]:
    if isinstance(names, str):
        raw_names: Iterable[str] = names.split(",")
    else:
        raw_names = names
    existing = {tag.name.casefold(): tag for tag in db.scalars(select(Tag)).all()}
    created: list[Tag] = []
    for name in normalize_tags(",".join(raw_names)):
        key = name.casefold()
        if key in existing:
            continue
        tag = Tag(name=name, color=_pick_color(db))
        db.add(tag)
        db.flush()
        existing[key] = tag
        created.append(tag)
    return created


def tag_color_map(db: Session) -> dict[str, str]:
    return {tag.name.casefold(): tag.color for tag in db.scalars(select(Tag)).all()}


def task_tag_counts(db: Session) -> Counter:
    counts: Counter = Counter()
    for task in db.scalars(select(Task)).all():
        for tag in {name.casefold() for name in task.tag_list}:
            counts[tag] += 1
    return counts


def all_task_tags(db: Session) -> list[str]:
    """任务标签候选：已登记标签 + 任务上引用但尚未登记的标签。"""
    values = {tag.name for tag in db.scalars(select(Tag)).all()}
    for task in db.scalars(select(Task)).all():
        values.update(task.tag_list)
    return sorted(values, key=str.casefold)


def rename_tag(db: Session, tag: Tag, new_name: str) -> str:
    clean = clean_tag(new_name)
    if not clean:
        return "标签名称不能为空"
    key = clean.casefold()
    exists = any(
        item.id != tag.id and item.name.casefold() == key for item in db.scalars(select(Tag)).all()
    )
    if exists:
        return "该标签已存在"
    old_key = tag.name.casefold()
    for task in db.scalars(select(Task)).all():
        names = task.tag_list
        if not any(name.casefold() == old_key for name in names):
            continue
        updated: list[str] = []
        seen: set[str] = set()
        for name in names:
            replacement = clean if name.casefold() == old_key else name
            if replacement.casefold() in seen:
                continue
            seen.add(replacement.casefold())
            updated.append(replacement)
        task.tags = normalize_single_tag(",".join(updated))
    tag.name = clean
    return ""


def set_tag_color(tag: Tag, value: str) -> str:
    color = normalize_color(value)
    if color is None:
        return "请选择有效颜色"
    tag.color = color
    return ""


__all__ = [
    "DEFAULT_TAG_COLOR",
    "MACARON_COLORS",
    "all_task_tags",
    "clean_tag",
    "ensure_tags",
    "normalize_color",
    "normalize_single_tag",
    "normalize_tag_string",
    "normalize_tags",
    "rename_tag",
    "set_tag_color",
    "tag_color_map",
    "task_tag_counts",
]
