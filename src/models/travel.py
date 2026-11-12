"""旅游模型：高德 GCJ02 点位库、旅程游记、小红书候选地点。"""

import json
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin

POINT_STATUS_LABELS = {"want": "想去", "visited": "已去"}
POINT_STATUS_COLORS = {"want": "#FFC8DD", "visited": "#BDE0FE"}
POINT_CATEGORIES = ("景点", "美食", "住宿", "交通", "商场", "娱乐")
POINT_CATEGORY_COLORS = {
    "景点": "#6FBF9A",
    "美食": "#FF9868",
    "住宿": "#A98BF2",
    "交通": "#5FA8F5",
    "商场": "#F5C242",
    "娱乐": "#F07CB0",
}
POINT_CATEGORY_DEFAULT_COLOR = "#B8BDC6"
CANDIDATE_STATUS_LABELS = {"pending": "待确认", "imported": "已入库", "ignored": "已忽略"}
MOOD_LABELS = {
    "happy": "开心",
    "normal": "普通",
    "bad": "踩雷",
    "wow": "超惊喜",
    "tired": "疲惫",
}
MOOD_COLORS = {
    "happy": "#FFD6E8",
    "normal": "#E3E1F5",
    "bad": "#FFD8C2",
    "wow": "#CDF5FD",
    "tired": "#DDE7D8",
}
JOURNEY_STATUS_LABELS = {"want": "想去", "visited": "已去过"}
JOURNEY_STATUS_COLORS = {"want": "#FFC8DD", "visited": "#BDE0FE"}


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
    amap_poi_id: Mapped[str] = mapped_column(String(64), default="")
    standard_address: Mapped[str] = mapped_column(String(255), default="")
    point_status: Mapped[str] = mapped_column(String(10), default="want")
    point_category: Mapped[str] = mapped_column(String(20), default="")
    source_note_url: Mapped[str] = mapped_column(String(600), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

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

    @property
    def status_label(self) -> str:
        return POINT_STATUS_LABELS.get(self.point_status, self.point_status)

    @property
    def marker_color(self) -> str:
        return POINT_CATEGORY_COLORS.get(self.point_category, POINT_CATEGORY_DEFAULT_COLOR)


class TravelPlaceCandidate(Base, TimestampMixin):
    """小红书笔记中被动识别出的候选地点，需人工确认后才入库。"""

    __tablename__ = "travel_place_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    note_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    note_title: Mapped[str] = mapped_column(String(300), default="")
    note_url: Mapped[str] = mapped_column(String(600), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    place_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def status_label(self) -> str:
        return CANDIDATE_STATUS_LABELS.get(self.status, self.status)


class Journey(Base, TimestampMixin):
    """一趟旅行的游记，状态只有想去 / 已去过两种。"""

    __tablename__ = "journeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="want")
    mood: Mapped[str] = mapped_column(String(20), default="normal")
    description: Mapped[str] = mapped_column(Text, default="")
    cost_transport: Mapped[int] = mapped_column(Integer, default=0)
    cost_lodging: Mapped[int] = mapped_column(Integer, default=0)
    cost_food: Mapped[int] = mapped_column(Integer, default=0)
    cost_other: Mapped[int] = mapped_column(Integer, default=0)
    photos: Mapped[str] = mapped_column(Text, default="[]")

    @property
    def status_label(self) -> str:
        return JOURNEY_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return JOURNEY_STATUS_COLORS.get(self.status, JOURNEY_STATUS_COLORS["want"])

    @property
    def photo_list(self) -> list[str]:
        try:
            data = json.loads(self.photos or "[]")
        except (TypeError, ValueError):
            return []
        return [str(item) for item in data if str(item).strip()] if isinstance(data, list) else []

    @property
    def total_cost(self) -> int:
        return (
            (self.cost_transport or 0)
            + (self.cost_lodging or 0)
            + (self.cost_food or 0)
            + (self.cost_other or 0)
        )

    @property
    def date_label(self) -> str:
        if self.start_date and self.end_date:
            return f"{self.start_date:%Y-%m-%d} → {self.end_date:%Y-%m-%d}"
        if self.start_date:
            return self.start_date.strftime("%Y-%m-%d")
        if self.end_date:
            return self.end_date.strftime("%Y-%m-%d")
        return ""

    @property
    def mood_label(self) -> str:
        return MOOD_LABELS.get(self.mood, self.mood)

    @property
    def mood_color(self) -> str:
        return MOOD_COLORS.get(self.mood, MOOD_COLORS["normal"])


class JourneyPlace(Base, TimestampMixin):
    """旅程与点位的多对多关联，note 记录本次到访的单独备注。"""

    __tablename__ = "journey_places"
    __table_args__ = (UniqueConstraint("journey_id", "place_id", name="uq_journey_place"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journey_id: Mapped[int] = mapped_column(
        ForeignKey("journeys.id", ondelete="CASCADE"), index=True
    )
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
