"""小红书收藏与书单模型（第一阶段为半自动 JSON 导入）。"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base, TimestampMixin


class ReadingNote(Base, TimestampMixin):
    __tablename__ = "reading_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), default="未命名笔记")
    author: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(String(600), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str] = mapped_column(String(600), default="")
    source: Mapped[str] = mapped_column(String(40), default="xiaohongshu")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")

    books: Mapped[list["Book"]] = relationship(back_populates="source_note")


class Book(Base, TimestampMixin):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    author: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="want")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    resource_url: Mapped[str] = mapped_column(String(600), default="")
    recommended_by: Mapped[str] = mapped_column(String(200), default="")
    source_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("reading_notes.id"), nullable=True
    )

    source_note: Mapped[ReadingNote | None] = relationship(back_populates="books")
