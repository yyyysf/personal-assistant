"""全局分类：分类是大分组，与实体自身的标签相互独立。"""

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db import Base, TimestampMixin


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("scope", "name", name="uq_category_scope_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(60))
