"""日程时间模块：时间轴日历、专注计时、截止事项、备忘录与统计。"""

import calendar
import json
import re
from datetime import date, datetime, time, timedelta
from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date, parse_dt, parse_int
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.time_utils import now, today, week_start
from src.models import DueItem, Project, ScheduleMemo, Subproject, TimeTask

router = APIRouter()

TABS = {"timeline", "timer", "stats"}
VIEWS = {"week", "day"}
STATS_RANGES = {"week", "month", "custom"}
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DEFAULT_COLOR = "#0071e3"
UNCATEGORIZED_COLOR = "#8e8e93"
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class TimerFinishPayload(BaseModel):
    task_id: int | None = None
    title: str = ""
    project_id: int | None = None
    subproject_id: int | None = None
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: int = 0
    note: str = ""
    client_token: str = ""


def _trigger(payload: dict) -> dict[str, str]:
    # HTTP header 只能承载 latin-1，中文需转义为 \uXXXX，htmx 仍按 JSON 解析。
    return {"HX-Trigger": json.dumps(payload, ensure_ascii=True)}


SCHEDULE_DONE = _trigger({"modal:close": True, "schedule:refresh": True})
SCHEDULE_REFRESH = _trigger({"schedule:refresh": True})


def _modal_error(request: Request, template: str, context: dict, message: str) -> HTMLResponse:
    context["error"] = message
    response = render_partial(request, template, context)
    response.headers["HX-Retarget"] = "#modal-body"
    return response


def _parse_time(value: str | None) -> time | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        if len(cleaned) <= 2:
            return time(int(cleaned), 0)
        parts = cleaned.split(":")
        return time(int(parts[0]), int(parts[1]))
    except (TypeError, ValueError, IndexError):
        return None


def _task_seconds(task: TimeTask) -> int:
    if task.duration_seconds and task.duration_seconds > 0:
        return int(task.duration_seconds)
    if task.start_at and task.end_at and task.end_at > task.start_at:
        return int((task.end_at - task.start_at).total_seconds())
    return 0


def _segments(tasks: list[TimeTask], day_start: datetime, day_end: datetime) -> list[dict]:
    segments: list[dict] = []
    for task in tasks:
        start_at = task.start_at
        if start_at is None:
            continue
        end_at = task.end_at
        if end_at is None or end_at <= start_at:
            minutes = max(30, _task_seconds(task) // 60)
            end_at = start_at + timedelta(minutes=minutes)
        visible_start = max(start_at, day_start)
        visible_end = min(end_at, day_end)
        if visible_end <= visible_start:
            continue
        start_min = (visible_start - day_start).total_seconds() / 60
        end_min = (visible_end - day_start).total_seconds() / 60
        segments.append(
            {
                "task": task,
                "start_min": start_min,
                "end_min": end_min,
                "top": round(start_min / 1440 * 100, 4),
                "height": round((end_min - start_min) / 1440 * 100, 4),
                "left": 0.0,
                "width": 100.0,
                "color": task.project.color if task.project else UNCATEGORIZED_COLOR,
                "time_label": f"{start_at:%H:%M}–{end_at:%H:%M}",
            }
        )
    return segments


def _layout(segments: list[dict]) -> None:
    """按重叠簇贪心分配泳道，避免任务块互相遮挡。"""
    if not segments:
        return
    ordered = sorted(segments, key=lambda seg: (seg["start_min"], seg["end_min"]))
    clusters: list[list[dict]] = []
    current: list[dict] = []
    cluster_end: float | None = None
    for seg in ordered:
        if current and cluster_end is not None and seg["start_min"] >= cluster_end:
            clusters.append(current)
            current = []
            cluster_end = None
        current.append(seg)
        cluster_end = max(cluster_end or seg["end_min"], seg["end_min"])
    if current:
        clusters.append(current)

    for cluster in clusters:
        lane_ends: list[float] = []
        for seg in cluster:
            assigned: int | None = None
            for index, lane_end in enumerate(lane_ends):
                if seg["start_min"] >= lane_end:
                    lane_ends[index] = seg["end_min"]
                    assigned = index
                    break
            if assigned is None:
                lane_ends.append(seg["end_min"])
                assigned = len(lane_ends) - 1
            seg["lane"] = assigned
        lane_count = len(lane_ends)
        for seg in cluster:
            seg["left"] = round(seg["lane"] * 100 / lane_count, 4)
            seg["width"] = round(100 / lane_count, 4)


def _timeline(db: Session, view: str, anchor: date) -> tuple[list[dict], date, date]:
    if view == "day":
        first = last = anchor
    else:
        first = anchor - timedelta(days=anchor.weekday())
        last = first + timedelta(days=6)
    window_start = datetime.combine(first, time.min)
    window_end = datetime.combine(last + timedelta(days=1), time.min)
    tasks = list(
        db.scalars(
            select(TimeTask)
            .where(
                TimeTask.start_at.is_not(None),
                TimeTask.start_at < window_end,
                or_(TimeTask.end_at.is_(None), TimeTask.end_at > window_start),
            )
            .order_by(TimeTask.start_at, TimeTask.id)
        ).all()
    )

    days: list[dict] = []
    current = first
    while current <= last:
        day_start = datetime.combine(current, time.min)
        day_end = day_start + timedelta(days=1)
        segments = _segments(tasks, day_start, day_end)
        _layout(segments)
        days.append(
            {
                "date": current,
                "weekday": WEEKDAY_LABELS[current.weekday()],
                "label": f"{current.month}/{current.day}",
                "is_today": current == today(),
                "segments": segments,
            }
        )
        current += timedelta(days=1)
    return days, first, last


def _due_rows(db: Session) -> list[dict]:
    items = db.scalars(select(DueItem).order_by(DueItem.done, DueItem.due_date, DueItem.id)).all()
    current_day = today()
    rows: list[dict] = []
    for item in items:
        days_left = (item.due_date - current_day).days
        if item.done:
            level, label = "done", "已完成"
        elif days_left < 0:
            level, label = "red", f"逾期 {-days_left} 天"
        elif days_left == 0:
            level, label = "red", "今天到期"
        elif days_left <= 3:
            level, label = "red", f"{days_left} 天后"
        elif days_left <= 7:
            level, label = "orange", f"{days_left} 天后"
        else:
            level, label = "yellow", f"{days_left} 天后"
        rows.append({"item": item, "days_left": days_left, "level": level, "label": label})
    return rows


def _stats_bounds(
    stats_range: str, anchor: date, date_from: str, date_to: str
) -> tuple[date, date]:
    if stats_range == "month":
        first = anchor.replace(day=1)
        last = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
    elif stats_range == "custom":
        start = parse_date(date_from)
        end = parse_date(date_to)
        if start is None or end is None or end < start:
            first = week_start(anchor)
            last = first + timedelta(days=6)
        else:
            first, last = start, end
    else:
        first = week_start(anchor)
        last = first + timedelta(days=6)
    if (last - first).days > 92:
        last = first + timedelta(days=92)
    return first, last


def _stats_payload(
    db: Session,
    stats_range: str,
    anchor: date,
    date_from: str,
    date_to: str,
    project_id: str,
) -> dict:
    first, last = _stats_bounds(stats_range, anchor, date_from, date_to)
    start_dt = datetime.combine(first, time.min)
    end_dt = datetime.combine(last + timedelta(days=1), time.min)
    statement = select(TimeTask).where(
        TimeTask.is_planned.is_(False),
        TimeTask.start_at.is_not(None),
        TimeTask.start_at >= start_dt,
        TimeTask.start_at < end_dt,
    )
    selected_project = parse_int(project_id)
    if selected_project:
        statement = statement.where(TimeTask.project_id == selected_project)
    records = db.scalars(statement.order_by(TimeTask.start_at)).all()

    day_list: list[date] = []
    current = first
    while current <= last:
        day_list.append(current)
        current += timedelta(days=1)
    daily = {day: 0 for day in day_list}

    project_totals: dict[int, dict] = {}
    table_totals: dict[tuple[int, int | None], dict] = {}
    for task in records:
        seconds = _task_seconds(task)
        start_at = task.start_at
        if start_at is not None and start_at.date() in daily:
            daily[start_at.date()] += seconds
        project = task.project
        project_key = project.id if project else 0
        project_entry = project_totals.setdefault(
            project_key,
            {
                "id": project_key,
                "name": project.name if project else "未分类",
                "color": project.color if project else UNCATEGORIZED_COLOR,
                "seconds": 0,
                "count": 0,
            },
        )
        project_entry["seconds"] += seconds
        project_entry["count"] += 1
        row_key = (project_key, task.subproject_id)
        row = table_totals.setdefault(
            row_key,
            {
                "project": project_entry["name"],
                "color": project_entry["color"],
                "subproject": task.subproject.name if task.subproject else "",
                "seconds": 0,
                "count": 0,
            },
        )
        row["seconds"] += seconds
        row["count"] += 1

    daily_seconds = [daily[day] for day in day_list]
    total_seconds = sum(daily_seconds)
    project_rows = sorted(project_totals.values(), key=lambda item: -item["seconds"])
    table_rows = sorted(table_totals.values(), key=lambda item: (-item["seconds"], item["project"]))
    for row in project_rows + table_rows:
        row["hours"] = round(row["seconds"] / 3600, 2)
    for row in project_rows:
        row["percent"] = round(row["seconds"] * 100 / total_seconds) if total_seconds else 0

    busiest_day = max(daily, key=lambda day: daily[day]) if total_seconds else None
    return {
        "range_key": stats_range if stats_range in STATS_RANGES else "week",
        "date_from": first.isoformat(),
        "date_to": last.isoformat(),
        "labels": [f"{day.month}/{day.day}" for day in day_list],
        "daily_seconds": daily_seconds,
        "daily_hours": [round(seconds / 3600, 2) for seconds in daily_seconds],
        "projects": project_rows,
        "table": table_rows,
        "total_seconds": total_seconds,
        "total_hours": round(total_seconds / 3600, 2),
        "record_count": len(records),
        "busiest_day": busiest_day,
        "busiest_seconds": daily[busiest_day] if busiest_day else 0,
        "chart_data": {
            "labels": [f"{day.month}/{day.day}" for day in day_list],
            "daily": [round(seconds / 3600, 2) for seconds in daily_seconds],
            "projects": [
                {"name": row["name"], "color": row["color"], "hours": row["hours"]}
                for row in project_rows
            ],
        },
    }


def _records_page(db: Session, page: int = 1) -> dict:
    statement = (
        select(TimeTask)
        .where(TimeTask.is_planned.is_(False))
        .order_by(TimeTask.start_at.desc(), TimeTask.id.desc())
    )
    return paginate(db, statement, page)


def _planned_tasks(db: Session) -> list[TimeTask]:
    return list(
        db.scalars(
            select(TimeTask)
            .where(TimeTask.is_planned.is_(True))
            .order_by(TimeTask.start_at.is_(None), TimeTask.start_at, TimeTask.id)
        ).all()
    )


def schedule_context(
    db: Session,
    tab: str = "timeline",
    view: str = "week",
    date_value: str = "",
    stats_range: str = "week",
    date_from: str = "",
    date_to: str = "",
    project_id: str = "",
    record_page: int = 1,
) -> dict:
    tab = tab if tab in TABS else "timeline"
    view = view if view in VIEWS else "week"
    stats_range = stats_range if stats_range in STATS_RANGES else "week"
    anchor = parse_date(date_value) or today()
    days, first, last = _timeline(db, view, anchor)
    if view == "day":
        prev_date = anchor - timedelta(days=1)
        next_date = anchor + timedelta(days=1)
    else:
        prev_date = first - timedelta(days=7)
        next_date = first + timedelta(days=7)
    current = now()
    now_pct = round((current.hour * 60 + current.minute) / 1440 * 100, 4)
    stats = _stats_payload(db, stats_range, anchor, date_from, date_to, project_id)
    return {
        "tab": tab,
        "view": view,
        "anchor": anchor,
        "days": days,
        "range_start": first,
        "range_end": last,
        "prev_date": prev_date,
        "next_date": next_date,
        "show_now": any(day["is_today"] for day in days),
        "now_pct": now_pct,
        "due_rows": _due_rows(db),
        "memos": db.scalars(
            select(ScheduleMemo).order_by(
                ScheduleMemo.pinned.desc(), ScheduleMemo.created_at.desc(), ScheduleMemo.id.desc()
            )
        ).all(),
        "projects": db.scalars(select(Project).order_by(Project.name)).all(),
        "timer_tasks": _planned_tasks(db),
        "records_page": _records_page(db, record_page),
        "stats": stats,
        "stats_filters": {
            "range": stats_range,
            "date_from": stats["date_from"],
            "date_to": stats["date_to"],
            "project_id": project_id,
        },
        "today": today(),
        "notice": "",
        "error": "",
    }


def _content_response(request: Request, db: Session, **kwargs) -> HTMLResponse:
    return render_partial(request, "partials/schedule_content.html", schedule_context(db, **kwargs))


# ---------- 页面与内容 ----------


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(
    request: Request,
    tab: str = "timeline",
    view: str = "week",
    date_value: str = Query("", alias="date"),
    stats_range: str = Query("week", alias="range"),
    date_from: str = "",
    date_to: str = "",
    project_id: str = "",
    record_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = schedule_context(
        db, tab, view, date_value, stats_range, date_from, date_to, project_id, record_page
    )
    return render(request, "schedule.html", context, active="schedule")


@router.get("/schedule/content", response_class=HTMLResponse)
def schedule_content(
    request: Request,
    tab: str = "timeline",
    view: str = "week",
    date_value: str = Query("", alias="date"),
    stats_range: str = Query("week", alias="range"),
    date_from: str = "",
    date_to: str = "",
    project_id: str = "",
    record_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(
        request,
        db,
        tab=tab,
        view=view,
        date_value=date_value,
        stats_range=stats_range,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        record_page=record_page,
    )


# ---------- 任务 CRUD ----------


def _task_form_values(task: TimeTask | None = None) -> dict:
    if task is None:
        return {
            "title": "",
            "project_id": "",
            "subproject_id": "",
            "new_project_name": "",
            "new_project_color": DEFAULT_COLOR,
            "new_subproject_name": "",
            "date": today().isoformat(),
            "start_time": "09:00",
            "end_time": "10:00",
            "note": "",
        }
    start_at = task.start_at or datetime.combine(task.planned_date or today(), time(9, 0))
    end_at = task.end_at or (start_at + timedelta(hours=1))
    return {
        "title": task.title,
        "project_id": str(task.project_id or ""),
        "subproject_id": str(task.subproject_id or ""),
        "new_project_name": "",
        "new_project_color": DEFAULT_COLOR,
        "new_subproject_name": "",
        "date": start_at.date().isoformat(),
        "start_time": start_at.strftime("%H:%M"),
        "end_time": end_at.strftime("%H:%M"),
        "note": task.note,
    }


def _task_form_context(
    db: Session,
    task: TimeTask | None = None,
    values: dict | None = None,
    error: str = "",
) -> dict:
    merged = values if values is not None else _task_form_values(task)
    project_id = parse_int(merged.get("project_id"))
    subprojects = (
        db.scalars(
            select(Subproject).where(Subproject.project_id == project_id).order_by(Subproject.name)
        ).all()
        if project_id
        else []
    )
    return {
        "task": task,
        "values": merged,
        "projects": db.scalars(select(Project).order_by(Project.name)).all(),
        "subprojects": subprojects,
        "error": error,
    }


def _resolve_references(db: Session, values: dict) -> tuple[Project | None, Subproject | None, str]:
    new_project_name = values["new_project_name"].strip()[:60]
    new_sub_name = values["new_subproject_name"].strip()[:60]
    project: Project | None = None
    if new_project_name:
        project = db.scalar(
            select(Project).where(func.lower(Project.name) == new_project_name.lower())
        )
    else:
        project_id = parse_int(values["project_id"])
        if project_id:
            project = db.get(Project, project_id)
            if project is None:
                return None, None, "所选项目不存在"

    subproject: Subproject | None = None
    if new_sub_name:
        if project is None and not new_project_name:
            return None, None, "新建子项目前请先选择或新建项目"
        if project is not None:
            subproject = db.scalar(
                select(Subproject).where(
                    Subproject.project_id == project.id,
                    func.lower(Subproject.name) == new_sub_name.lower(),
                )
            )
    else:
        subproject_id = parse_int(values["subproject_id"])
        if subproject_id:
            subproject = db.get(Subproject, subproject_id)
            if subproject is None:
                return project, None, "所选子项目不存在"
            if new_project_name:
                return project, None, "新建项目时不能引用其他项目的子项目"
            if project is not None and subproject.project_id != project.id:
                return project, None, "子项目不属于所选项目"
            if project is None:
                project = subproject.project
    return project, subproject, ""


def _ensure_references(
    db: Session, values: dict, project: Project | None, subproject: Subproject | None
) -> tuple[Project | None, Subproject | None]:
    new_project_name = values["new_project_name"].strip()[:60]
    if new_project_name and project is None:
        color = values["new_project_color"].strip()
        project = Project(
            name=new_project_name, color=color if COLOR_RE.match(color) else DEFAULT_COLOR
        )
        db.add(project)
        db.flush()
    new_sub_name = values["new_subproject_name"].strip()[:60]
    if new_sub_name and project is not None and subproject is None:
        subproject = Subproject(project_id=project.id, name=new_sub_name)
        db.add(subproject)
        db.flush()
    if subproject is not None and project is None:
        project = subproject.project
    return project, subproject


def _task_payload(db: Session, values: dict) -> tuple[dict | None, str]:
    title = values["title"].strip()[:200]
    if not title:
        return None, "任务标题不能为空"
    day = parse_date(values["date"])
    if day is None:
        return None, "请选择有效日期"
    start_time = _parse_time(values["start_time"])
    end_time = _parse_time(values["end_time"])
    if start_time is None or end_time is None:
        return None, "请填写有效的开始与结束时间"
    start_at = datetime.combine(day, start_time)
    end_at = datetime.combine(day, end_time)
    if end_at <= start_at:
        end_at += timedelta(days=1)

    project, subproject, error = _resolve_references(db, values)
    if error:
        return None, error
    project, subproject = _ensure_references(db, values, project, subproject)
    return {
        "title": title,
        "project_id": project.id if project else None,
        "subproject_id": subproject.id if subproject else None,
        "planned_date": day,
        "start_at": start_at,
        "end_at": end_at,
        "note": values["note"].strip(),
    }, ""


def _submitted_task(
    title: str,
    project_id: str,
    subproject_id: str,
    new_project_name: str,
    new_project_color: str,
    new_subproject_name: str,
    date_value: str,
    start_time: str,
    end_time: str,
    note: str,
) -> dict:
    return {
        "title": title,
        "project_id": project_id,
        "subproject_id": subproject_id,
        "new_project_name": new_project_name,
        "new_project_color": new_project_color,
        "new_subproject_name": new_subproject_name,
        "date": date_value,
        "start_time": start_time,
        "end_time": end_time,
        "note": note,
    }


@router.get("/schedule/tasks/new", response_class=HTMLResponse)
def schedule_task_new(
    request: Request,
    date_value: str = Query("", alias="date"),
    start: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    values = _task_form_values()
    parsed_day = parse_date(date_value)
    if parsed_day:
        values["date"] = parsed_day.isoformat()
    start_time = _parse_time(start)
    if start_time:
        values["start_time"] = start_time.strftime("%H:%M")
        minutes = min(start_time.hour * 60 + start_time.minute + 60, 23 * 60 + 59)
        values["end_time"] = f"{minutes // 60:02d}:{minutes % 60:02d}"
    return render_partial(
        request,
        "partials/modals/schedule_task_form.html",
        _task_form_context(db, None, values),
    )


@router.post("/schedule/tasks/new", response_class=HTMLResponse)
def schedule_task_create(
    request: Request,
    title: str = Form(""),
    project_id: str = Form(""),
    subproject_id: str = Form(""),
    new_project_name: str = Form(""),
    new_project_color: str = Form(DEFAULT_COLOR),
    new_subproject_name: str = Form(""),
    date_value: str = Form("", alias="date"),
    start_time: str = Form("09:00"),
    end_time: str = Form("10:00"),
    note: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    values = _submitted_task(
        title,
        project_id,
        subproject_id,
        new_project_name,
        new_project_color,
        new_subproject_name,
        date_value,
        start_time,
        end_time,
        note,
    )
    payload, error = _task_payload(db, values)
    if error:
        db.rollback()
        return _modal_error(
            request,
            "partials/modals/schedule_task_form.html",
            _task_form_context(db, None, values),
            error,
        )
    db.add(TimeTask(**payload))
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.get("/schedule/tasks/{task_id}/detail", response_class=HTMLResponse)
def schedule_task_detail(
    task_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    task = db.get(TimeTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="时间任务不存在")
    return render_partial(
        request,
        "partials/modals/schedule_task_detail.html",
        {"task": task, "duration_seconds": _task_seconds(task)},
    )


@router.get("/schedule/tasks/{task_id}/edit", response_class=HTMLResponse)
def schedule_task_edit_form(
    task_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    task = db.get(TimeTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="时间任务不存在")
    return render_partial(
        request,
        "partials/modals/schedule_task_form.html",
        _task_form_context(db, task),
    )


@router.post("/schedule/tasks/{task_id}/edit", response_class=HTMLResponse)
def schedule_task_update(
    task_id: int,
    request: Request,
    title: str = Form(""),
    project_id: str = Form(""),
    subproject_id: str = Form(""),
    new_project_name: str = Form(""),
    new_project_color: str = Form(DEFAULT_COLOR),
    new_subproject_name: str = Form(""),
    date_value: str = Form("", alias="date"),
    start_time: str = Form("09:00"),
    end_time: str = Form("10:00"),
    note: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(TimeTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="时间任务不存在")
    values = _submitted_task(
        title,
        project_id,
        subproject_id,
        new_project_name,
        new_project_color,
        new_subproject_name,
        date_value,
        start_time,
        end_time,
        note,
    )
    payload, error = _task_payload(db, values)
    if error:
        db.rollback()
        return _modal_error(
            request,
            "partials/modals/schedule_task_form.html",
            _task_form_context(db, task, values),
            error,
        )
    for field, value in payload.items():
        setattr(task, field, value)
    if not task.is_planned:
        task.duration_seconds = _task_seconds(task)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.post("/schedule/tasks/{task_id}/delete", response_class=HTMLResponse)
def schedule_task_delete(task_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(TimeTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="时间任务不存在")
    db.delete(task)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.get("/schedule/subprojects", response_class=HTMLResponse)
def schedule_subproject_options(
    project_id: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    selected = parse_int(project_id)
    options = ['<option value="">不选择</option>']
    if selected:
        subprojects = db.scalars(
            select(Subproject).where(Subproject.project_id == selected).order_by(Subproject.name)
        ).all()
        for subproject in subprojects:
            options.append(f'<option value="{subproject.id}">{escape(subproject.name)}</option>')
    return HTMLResponse("".join(options))


# ---------- 项目 / 子项目 ----------


def _projects_context(db: Session, error: str = "") -> dict:
    return {
        "projects": db.scalars(select(Project).order_by(Project.name)).all(),
        "error": error,
    }


def _project_form_context(
    project: Project | None = None,
    values: dict | None = None,
    error: str = "",
) -> dict:
    if values is None:
        values = {
            "name": project.name if project else "",
            "color": project.color if project else DEFAULT_COLOR,
        }
    return {"project": project, "values": values, "error": error}


@router.get("/schedule/projects", response_class=HTMLResponse)
def schedule_projects(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/schedule_projects.html", _projects_context(db))


@router.get("/schedule/projects/new", response_class=HTMLResponse)
def schedule_project_new(request: Request) -> HTMLResponse:
    return render_partial(
        request, "partials/modals/schedule_project_form.html", _project_form_context()
    )


@router.post("/schedule/projects/new", response_class=HTMLResponse)
def schedule_project_create(
    request: Request,
    name: str = Form(""),
    color: str = Form(DEFAULT_COLOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    clean_name = name.strip()[:60]
    values = {"name": name, "color": color}
    if not clean_name:
        return _modal_error(
            request,
            "partials/modals/schedule_project_form.html",
            _project_form_context(None, values),
            "项目名称不能为空",
        )
    exists = db.scalar(select(Project).where(func.lower(Project.name) == clean_name.lower()))
    if exists is not None:
        return _modal_error(
            request,
            "partials/modals/schedule_project_form.html",
            _project_form_context(None, values),
            "项目名称已存在",
        )
    db.add(
        Project(
            name=clean_name,
            color=color if COLOR_RE.match(color) else DEFAULT_COLOR,
        )
    )
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.get("/schedule/projects/{project_id}/edit", response_class=HTMLResponse)
def schedule_project_edit_form(
    project_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return render_partial(
        request, "partials/modals/schedule_project_form.html", _project_form_context(project)
    )


@router.post("/schedule/projects/{project_id}/edit", response_class=HTMLResponse)
def schedule_project_update(
    project_id: int,
    request: Request,
    name: str = Form(""),
    color: str = Form(DEFAULT_COLOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    clean_name = name.strip()[:60]
    values = {"name": name, "color": color}
    if not clean_name:
        return _modal_error(
            request,
            "partials/modals/schedule_project_form.html",
            _project_form_context(project, values),
            "项目名称不能为空",
        )
    exists = db.scalar(
        select(Project).where(
            func.lower(Project.name) == clean_name.lower(), Project.id != project.id
        )
    )
    if exists is not None:
        return _modal_error(
            request,
            "partials/modals/schedule_project_form.html",
            _project_form_context(project, values),
            "项目名称已存在",
        )
    project.name = clean_name
    project.color = color if COLOR_RE.match(color) else DEFAULT_COLOR
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.post("/schedule/projects/{project_id}/delete", response_class=HTMLResponse)
def schedule_project_delete(
    project_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    direct_tasks = int(
        db.scalar(
            select(func.count()).select_from(TimeTask).where(TimeTask.project_id == project_id)
        )
        or 0
    )
    subproject_ids = [sub.id for sub in project.subprojects]
    sub_tasks = 0
    if subproject_ids:
        sub_tasks = int(
            db.scalar(
                select(func.count())
                .select_from(TimeTask)
                .where(TimeTask.subproject_id.in_(subproject_ids))
            )
            or 0
        )
    if direct_tasks or sub_tasks:
        return _modal_error(
            request,
            "partials/modals/schedule_projects.html",
            _projects_context(db),
            "该项目下仍有时间任务，请先调整或删除任务",
        )
    for due in db.scalars(select(DueItem).where(DueItem.project_id == project_id)).all():
        due.project_id = None
    db.delete(project)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


# ---------- 截止事项 ----------


def _due_form_context(db: Session, values: dict | None = None, error: str = "") -> dict:
    if values is None:
        values = {
            "title": "",
            "due_date": today().isoformat(),
            "note": "",
            "project_id": "",
        }
    return {
        "values": values,
        "projects": db.scalars(select(Project).order_by(Project.name)).all(),
        "error": error,
    }


@router.get("/schedule/due/new", response_class=HTMLResponse)
def schedule_due_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/schedule_due_form.html", _due_form_context(db))


@router.post("/schedule/due/new", response_class=HTMLResponse)
def schedule_due_create(
    request: Request,
    title: str = Form(""),
    due_date: str = Form(""),
    note: str = Form(""),
    project_id: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    values = {"title": title, "due_date": due_date, "note": note, "project_id": project_id}
    clean_title = title.strip()[:200]
    parsed_day = parse_date(due_date)
    if not clean_title:
        return _modal_error(
            request,
            "partials/modals/schedule_due_form.html",
            _due_form_context(db, values),
            "截止事项名称不能为空",
        )
    if parsed_day is None:
        return _modal_error(
            request,
            "partials/modals/schedule_due_form.html",
            _due_form_context(db, values),
            "请选择有效的截止日期",
        )
    project = db.get(Project, parse_int(project_id)) if parse_int(project_id) else None
    db.add(
        DueItem(
            title=clean_title,
            due_date=parsed_day,
            note=note.strip(),
            project_id=project.id if project else None,
        )
    )
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.post("/schedule/due/{due_id}/toggle", response_class=HTMLResponse)
def schedule_due_toggle(due_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    item = db.get(DueItem, due_id)
    if item is None:
        raise HTTPException(status_code=404, detail="截止事项不存在")
    item.done = not item.done
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_REFRESH)


@router.post("/schedule/due/{due_id}/delete", response_class=HTMLResponse)
def schedule_due_delete(due_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    item = db.get(DueItem, due_id)
    if item is None:
        raise HTTPException(status_code=404, detail="截止事项不存在")
    db.delete(item)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_REFRESH)


# ---------- 备忘录 ----------


@router.post("/schedule/memos/new", response_class=HTMLResponse)
def schedule_memo_create(content: str = Form(""), db: Session = Depends(get_db)) -> HTMLResponse:
    clean = content.strip()
    if clean:
        db.add(ScheduleMemo(content=clean[:2000]))
        db.commit()
    return HTMLResponse("", headers=SCHEDULE_REFRESH)


@router.post("/schedule/memos/{memo_id}/pin", response_class=HTMLResponse)
def schedule_memo_pin(memo_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    memo = db.get(ScheduleMemo, memo_id)
    if memo is None:
        raise HTTPException(status_code=404, detail="备忘录不存在")
    memo.pinned = not memo.pinned
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_REFRESH)


@router.post("/schedule/memos/{memo_id}/delete", response_class=HTMLResponse)
def schedule_memo_delete(memo_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    memo = db.get(ScheduleMemo, memo_id)
    if memo is None:
        raise HTTPException(status_code=404, detail="备忘录不存在")
    db.delete(memo)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_REFRESH)


# ---------- 专注计时 ----------


def _record_data(task: TimeTask) -> dict:
    return {
        "id": task.id,
        "task_id": task.id,
        "title": task.title,
        "duration_seconds": task.duration_seconds,
        "start_at": task.start_at.isoformat() if task.start_at else None,
        "end_at": task.end_at.isoformat() if task.end_at else None,
    }


@router.post("/schedule/timer/finish")
def schedule_timer_finish(
    payload: TimerFinishPayload, db: Session = Depends(get_db)
) -> JSONResponse:
    token = payload.client_token.strip()[:64]
    if token:
        existing = db.scalar(select(TimeTask).where(TimeTask.client_token == token))
        if existing is not None:
            return JSONResponse({"ok": True, "message": "", "data": _record_data(existing)})

    ended_at = parse_dt(payload.ended_at) or now()
    started_at = parse_dt(payload.started_at) or (
        ended_at - timedelta(seconds=max(0, payload.duration_seconds))
    )
    if started_at > ended_at:
        started_at, ended_at = ended_at, started_at
    duration = payload.duration_seconds or int((ended_at - started_at).total_seconds())
    duration = max(0, int(duration))

    if payload.task_id:
        task = db.get(TimeTask, payload.task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="时间任务不存在")
        if not task.is_planned:
            raise HTTPException(status_code=409, detail="该任务已完成计时")
        task.start_at = started_at
        task.end_at = ended_at
        task.duration_seconds = duration
        task.planned_date = started_at.date()
        if payload.note.strip():
            task.note = payload.note.strip()
        task.is_planned = False
        task.completed_at = now()
        task.client_token = token or None
        db.commit()
        db.refresh(task)
        return JSONResponse({"ok": True, "message": "", "data": _record_data(task)})

    title = payload.title.strip()[:200]
    if not title:
        raise HTTPException(status_code=422, detail="临时任务名称不能为空")

    project: Project | None = None
    subproject: Subproject | None = None
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        if project is None:
            raise HTTPException(status_code=422, detail="所选项目不存在")
    if payload.subproject_id:
        subproject = db.get(Subproject, payload.subproject_id)
        if subproject is None:
            raise HTTPException(status_code=422, detail="所选子项目不存在")
        if project is not None and subproject.project_id != project.id:
            raise HTTPException(status_code=422, detail="子项目不属于所选项目")
        if project is None:
            project = subproject.project

    task = TimeTask(
        title=title,
        project_id=project.id if project else None,
        subproject_id=subproject.id if subproject else None,
        planned_date=started_at.date(),
        start_at=started_at,
        end_at=ended_at,
        note=payload.note.strip(),
        is_planned=False,
        duration_seconds=duration,
        completed_at=now(),
        client_token=token or None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return JSONResponse({"ok": True, "message": "", "data": _record_data(task)})


@router.get("/schedule/timer/records", response_class=HTMLResponse)
def schedule_timer_records(
    request: Request, record_page: int = 1, db: Session = Depends(get_db)
) -> HTMLResponse:
    return render_partial(
        request,
        "partials/schedule_records.html",
        {"records_page": _records_page(db, record_page), "today": today()},
    )


def _record_form_values(record: TimeTask) -> dict:
    start_at = record.start_at or now()
    end_at = record.end_at or (start_at + timedelta(minutes=max(1, record.duration_seconds // 60)))
    return {
        "title": record.title,
        "project_id": str(record.project_id or ""),
        "date": start_at.date().isoformat(),
        "start_time": start_at.strftime("%H:%M"),
        "end_time": end_at.strftime("%H:%M"),
        "note": record.note,
    }


def _record_form_context(
    db: Session,
    record: TimeTask,
    values: dict | None = None,
    error: str = "",
) -> dict:
    return {
        "record": record,
        "values": values if values is not None else _record_form_values(record),
        "projects": db.scalars(select(Project).order_by(Project.name)).all(),
        "error": error,
    }


@router.get("/schedule/records/{record_id}/edit", response_class=HTMLResponse)
def schedule_record_edit_form(
    record_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    record = db.get(TimeTask, record_id)
    if record is None or record.is_planned:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    return render_partial(
        request, "partials/modals/schedule_record_form.html", _record_form_context(db, record)
    )


@router.post("/schedule/records/{record_id}/edit", response_class=HTMLResponse)
def schedule_record_update(
    record_id: int,
    request: Request,
    title: str = Form(""),
    project_id: str = Form(""),
    date_value: str = Form("", alias="date"),
    start_time: str = Form("09:00"),
    end_time: str = Form("10:00"),
    note: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    record = db.get(TimeTask, record_id)
    if record is None or record.is_planned:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    values = {
        "title": title,
        "project_id": project_id,
        "date": date_value,
        "start_time": start_time,
        "end_time": end_time,
        "note": note,
    }
    clean_title = title.strip()[:200]
    day = parse_date(date_value)
    start = _parse_time(start_time)
    end = _parse_time(end_time)
    error = ""
    if not clean_title:
        error = "记录名称不能为空"
    elif day is None:
        error = "请选择有效日期"
    elif start is None or end is None:
        error = "请填写有效的开始与结束时间"
    if error:
        return _modal_error(
            request,
            "partials/modals/schedule_record_form.html",
            _record_form_context(db, record, values),
            error,
        )
    start_at = datetime.combine(day, start)
    end_at = datetime.combine(day, end)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    project = db.get(Project, parse_int(project_id)) if parse_int(project_id) else None
    record.title = clean_title
    record.project_id = project.id if project else None
    if record.subproject_id:
        subproject = db.get(Subproject, record.subproject_id)
        if subproject is None or (project is not None and subproject.project_id != project.id):
            record.subproject_id = None
    record.planned_date = start_at.date()
    record.start_at = start_at
    record.end_at = end_at
    record.duration_seconds = int((end_at - start_at).total_seconds())
    record.note = note.strip()
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.post("/schedule/records/{record_id}/delete", response_class=HTMLResponse)
def schedule_record_delete(record_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    record = db.get(TimeTask, record_id)
    if record is None or record.is_planned:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    db.delete(record)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)
