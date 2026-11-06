"""任务模型：任务与日程时间共用同一条记录。"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin

DATE_MODES = ("deadline", "single", "range")


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    tags: Mapped[str] = mapped_column(String(200), default="")
    date_mode: Mapped[str] = mapped_column(String(20), default="deadline")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived: Mapped[bool] = mapped_column(default=False)
    client_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    source_time_task_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    @property
    def is_done(self) -> bool:
        return self.status == "done"

    @property
    def schedule_start(self) -> datetime | None:
        """时间轴展示用起点：优先真实计时，其次按日期模式推导。"""
        if self.start_at is not None:
            return self.start_at
        if self.date_mode == "single" and self.planned_date is not None:
            return datetime.combine(self.planned_date, time(9, 0))
        if self.date_mode == "deadline" and self.due_date is not None:
            return self.due_date - timedelta(hours=1)
        if self.date_mode == "range" and self.range_start is not None:
            return datetime.combine(self.range_start, time(9, 0))
        return None

    @property
    def schedule_end(self) -> datetime | None:
        start = self.schedule_start
        if start is None:
            return None
        if self.end_at is not None and self.end_at > start:
            return self.end_at
        if self.date_mode == "deadline" and self.due_date is not None:
            return self.due_date
        return start + timedelta(hours=1)

    @property
    def date_label(self) -> str:
        if self.date_mode == "range" and self.range_start and self.range_end:
            return f"{self.range_start:%m-%d} → {self.range_end:%m-%d}"
        if self.date_mode == "single" and self.planned_date:
            if self.start_at is not None:
                return self.start_at.strftime("%m-%d %H:%M 计划")
            return self.planned_date.strftime("%m-%d 计划")
        if self.due_date:
            return self.due_date.strftime("截止 %m-%d %H:%M")
        return ""
