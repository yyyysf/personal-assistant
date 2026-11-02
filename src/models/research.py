"""科研板块：arXiv 论文与阅读笔记。"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base, TimestampMixin


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    arxiv_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    authors: Mapped[str] = mapped_column(String(500), default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    imported_to_zotero: Mapped[bool] = mapped_column(Boolean, default=False)
    zotero_item_key: Mapped[str] = mapped_column(String(40), default="")
    tags: Mapped[str] = mapped_column(String(300), default="")
    read_status: Mapped[str] = mapped_column(String(20), default="unread")
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title_zh: Mapped[str] = mapped_column(String(500), default="")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    @property
    def display_title(self) -> str:
        return self.title_zh or self.title

    notes: Mapped[list["PaperNote"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class PaperNote(Base, TimestampMixin):
    __tablename__ = "paper_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")

    paper: Mapped[Paper] = relationship(back_populates="notes")
