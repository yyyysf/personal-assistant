"""日程时间模块：项目、子项目、时间任务、截止事项与备忘录。"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#0071e3")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    subprojects: Mapped[list["Subproject"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Subproject.id",
    )


class Subproject(Base, TimestampMixin):
    __tablename__ = "subprojects"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_subproject_project_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)

    project: Mapped[Project] = relationship(back_populates="subprojects")


class TimeTask(Base, TimestampMixin):
    __tablename__ = "time_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    subproject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subprojects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    planned_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    is_planned: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    project: Mapped[Project | None] = relationship(lazy="selectin")
    subproject: Mapped[Subproject | None] = relationship(lazy="selectin")

    @property
    def is_done(self) -> bool:
        return not self.is_planned


class DueItem(Base, TimestampMixin):
    __tablename__ = "due_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )


class ScheduleMemo(Base, TimestampMixin):
    __tablename__ = "schedule_memos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
