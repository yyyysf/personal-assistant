"""每周 AI 复盘记录。"""

from datetime import date

from sqlalchemy import Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin


class WeeklyReview(Base, TimestampMixin):
    __tablename__ = "weekly_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    suggestions: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="llm")
