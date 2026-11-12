"""API 请求体模型。"""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

PRIORITIES = {"high", "medium", "low"}
TASK_STATUSES = {"todo", "doing", "done"}
BOOK_STATUSES = {"want", "reading", "finished"}
CATEGORIES = {"video", "music"}
POINT_STATUSES = {"want", "visited"}
POINT_CATEGORIES = {"景点", "美食", "住宿", "交通", "商场", "娱乐"}


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: str = "medium"
    tags: str = ""
    status: str = "todo"
    due_date: datetime | None = None
    date_mode: str = "deadline"
    planned_date: date | None = None
    range_start: date | None = None
    range_end: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    @field_validator("priority")
    @classmethod
    def check_priority(cls, value: str) -> str:
        if value not in PRIORITIES:
            raise ValueError("priority 只能是 high / medium / low")
        return value

    @field_validator("status")
    @classmethod
    def check_status(cls, value: str) -> str:
        if value not in TASK_STATUSES:
            raise ValueError("status 只能是 todo / doing / done")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: str | None = None
    tags: str | None = None
    status: str | None = None
    due_date: datetime | None = None
    date_mode: str | None = None
    planned_date: date | None = None
    range_start: date | None = None
    range_end: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    archived: bool | None = None


class PaperNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = ""
    status: str = "want"
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str = ""
    resource_url: str = ""
    recommended_by: str = ""

    @field_validator("status")
    @classmethod
    def check_status(cls, value: str) -> str:
        if value not in BOOK_STATUSES:
            raise ValueError("status 只能是 want / reading / finished")
        return value


class BookUpdate(BaseModel):
    status: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None
    resource_url: str | None = None


class LearningItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    resource_url: str = ""
    scheduled_date: date | None = None


class LearningItemUpdate(BaseModel):
    status: str | None = None
    mastery: int | None = Field(default=None, ge=0, le=100)


class LearningLogCreate(BaseModel):
    content: str = Field(min_length=1, max_length=3000)
    mastery: int = Field(default=0, ge=0, le=100)


class PlaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = ""
    city: str = ""
    lat: float = Field(default=0.0, ge=-90, le=90)
    lng: float = Field(default=0.0, ge=-180, le=180)
    visited: bool = False
    point_status: str = "want"
    point_category: str = ""
    standard_address: str = ""
    amap_poi_id: str = ""
    source_note_url: str = ""
    tags: str = ""
    visit_date: date | None = None
    notes: str = ""

    @field_validator("point_status")
    @classmethod
    def check_point_status(cls, value: str) -> str:
        if value not in POINT_STATUSES:
            raise ValueError("point_status 只能是 want / visited")
        return value

    @field_validator("point_category")
    @classmethod
    def check_point_category(cls, value: str) -> str:
        if value and value not in POINT_CATEGORIES:
            raise ValueError("point_category 不在内置分类中")
        return value


class PlaceUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    visited: bool | None = None
    point_status: str | None = None
    point_category: str | None = None
    standard_address: str | None = None
    amap_poi_id: str | None = None
    source_note_url: str | None = None
    tags: str | None = None
    visit_date: date | None = None


class CategoryCreate(BaseModel):
    scope: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=60)


class CategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class FeedSourceCreate(BaseModel):
    name: str = Field(default="", max_length=120)
    url: str = Field(min_length=1, max_length=800)
    enabled: bool = True


class FeedSourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=800)
    enabled: bool | None = None
