"""标签：任务与日程时间共用的分类与马卡龙颜色。"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin

DEFAULT_TAG_COLOR = "#A9C7E8"


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    color: Mapped[str] = mapped_column(String(7), default=DEFAULT_TAG_COLOR)
