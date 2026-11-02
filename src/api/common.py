"""路由共用小工具。"""

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.models import LearningTrack

LEARNING_LABELS = {"video": "AI 视频学习", "music": "AI 音乐学习"}


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def parse_int(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ensure_track(db: Session, category: str) -> LearningTrack:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在，仅支持 video / music")
    track = db.query(LearningTrack).filter(LearningTrack.category == category).first()
    if track is None:
        track = LearningTrack(
            category=category,
            title=LEARNING_LABELS[category],
            description="",
            progress=0,
        )
        db.add(track)
        db.commit()
        db.refresh(track)
    return track


def recalculate_progress(track: LearningTrack) -> None:
    if not track.items:
        track.progress = 0
        return
    total = sum(item.mastery for item in track.items)
    track.progress = round(total / len(track.items))
