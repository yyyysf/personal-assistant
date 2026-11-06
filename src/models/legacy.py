"""历史表映射：仅用于把旧 time_tasks 数据迁移到统一 Task，不参与业务。"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base


class LegacyTimeTask(Base):
    __tablename__ = "time_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    is_planned: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
