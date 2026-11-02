"""AI & 计算机前沿资讯日报模型。"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin


class NewsItem(Base, TimestampMixin):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), default="RSS")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    link: Mapped[str] = mapped_column(String(800), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_zh: Mapped[str] = mapped_column(Text, default="")
    title_zh: Mapped[str] = mapped_column(String(500), default="")
    comment_url: Mapped[str] = mapped_column(String(800), default="")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    digest_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    @property
    def display_title(self) -> str:
        return self.title_zh or self.title

    @property
    def display_summary(self) -> str:
        return self.summary_zh or self.summary


class FeedSource(Base, TimestampMixin):
    __tablename__ = "feed_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(String(800), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NewsDigest(Base, TimestampMixin):
    __tablename__ = "news_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
