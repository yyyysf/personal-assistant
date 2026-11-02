"""AI & 计算机前沿资讯日报模型。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin


class NewsItem(Base, TimestampMixin):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), default="RSS")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    link: Mapped[str] = mapped_column(String(800), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    digest_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)


class NewsDigest(Base, TimestampMixin):
    __tablename__ = "news_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
