"""旅游规划与地图标记模型。"""

import json
from datetime import date

from sqlalchemy import Boolean, Date, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin


class Place(Base, TimestampMixin):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(100), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lng: Mapped[float] = mapped_column(Float, default=0.0)
    visited: Mapped[bool] = mapped_column(Boolean, default=False)
    date_mode: Mapped[str] = mapped_column(String(20), default="single")
    visit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    visit_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(60), default="")
    tags: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    photos: Mapped[str] = mapped_column(Text, default="[]")

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    @property
    def photo_list(self) -> list[str]:
        try:
            data = json.loads(self.photos or "[]")
        except (TypeError, ValueError):
            return []
        return [str(item) for item in data if str(item).strip()] if isinstance(data, list) else []

    @property
    def date_label(self) -> str:
        if self.date_mode == "range" and self.visit_date and self.visit_end_date:
            return f"{self.visit_date:%Y-%m-%d} → {self.visit_end_date:%Y-%m-%d}"
        if self.visit_date:
            return self.visit_date.strftime("%Y-%m-%d")
        return ""


class TripPlan(Base, TimestampMixin):
    __tablename__ = "trip_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    category: Mapped[str] = mapped_column(String(60), default="")
    tags: Mapped[str] = mapped_column(String(200), default="")
    itinerary: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]
