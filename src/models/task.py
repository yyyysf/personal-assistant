"""日常任务与目标模型。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base, TimestampMixin


class Goal(Base, TimestampMixin):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    category: Mapped[str] = mapped_column(String(60), default="")
    tags: Mapped[str] = mapped_column(String(200), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tasks: Mapped[list["Task"]] = relationship(back_populates="goal")

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]


DATE_MODES = ("deadline", "single", "range")


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    tags: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    date_mode: Mapped[str] = mapped_column(String(20), default="deadline")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived: Mapped[bool] = mapped_column(default=False)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), nullable=True)

    goal: Mapped[Goal | None] = relationship(back_populates="tasks")

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    @property
    def date_label(self) -> str:
        if self.date_mode == "range" and self.range_start and self.range_end:
            return f"{self.range_start:%m-%d} → {self.range_end:%m-%d}"
        if self.date_mode == "single" and self.planned_date:
            return self.planned_date.strftime("%m-%d 计划")
        if self.due_date:
            return self.due_date.strftime("截止 %m-%d %H:%M")
        return ""
