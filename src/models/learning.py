"""动态学习路线：AI 视频 / AI 音乐两个子模块共享同一套模型。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base, TimestampMixin


class LearningTrack(Base, TimestampMixin):
    __tablename__ = "learning_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)

    items: Mapped[list["LearningItem"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )
    logs: Mapped[list["LearningLog"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class LearningItem(Base, TimestampMixin):
    __tablename__ = "learning_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("learning_tracks.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    resource_url: Mapped[str] = mapped_column(String(600), default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    mastery: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    track: Mapped[LearningTrack] = relationship(back_populates="items")


class LearningLog(Base, TimestampMixin):
    """学习记忆：记录掌握程度与心得，供 LLM 动态调整路线。"""

    __tablename__ = "learning_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("learning_tracks.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    mastery: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(30), default="manual")

    track: Mapped[LearningTrack] = relationship(back_populates="logs")
