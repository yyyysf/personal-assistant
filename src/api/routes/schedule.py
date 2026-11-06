"""日程时间模块：统一任务时间轴、专注计时与时间统计。"""

import calendar
import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date, parse_dt
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.tags import (
    all_task_tags,
    ensure_tags,
    normalize_single_tag,
    tag_color_map,
)
from src.core.taxonomy import tag_filter
from src.core.time_utils import now, today, week_start
from src.models import Task

router = APIRouter()

TABS = {"timeline", "timer", "stats"}
VIEWS = {"week", "day"}
STATS_RANGES = {"week", "month", "custom"}
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
UNTAGGED_COLOR = "#C7C7CC"


class TimerFinishPayload(BaseModel):
    task_id: int | None = None
    title: str = ""
    tags: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: int = 0
    description: str = ""
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


def _task_seconds(task: Task) -> int:
    if task.duration_seconds and task.duration_seconds > 0:
        return int(task.duration_seconds)
    if task.start_at and task.end_at and task.end_at > task.start_at:
        return int((task.end_at - task.start_at).total_seconds())
    return 0


def _block_times(task: Task, day_start: datetime) -> tuple[datetime, datetime] | None:
    """返回任务在某一天的可视起止时间，兼容真实计时与三种日期模式。"""
    if task.start_at is not None:
        end_at = task.end_at
        if end_at is None or end_at <= task.start_at:
            minutes = max(30, _task_seconds(task) // 60)
            end_at = task.start_at + timedelta(minutes=minutes)
        return task.start_at, end_at
    if task.date_mode == "single" and task.planned_date is not None:
        start = datetime.combine(task.planned_date, time(9, 0))
        return start, start + timedelta(hours=1)
    if task.date_mode == "deadline" and task.due_date is not None:
        return task.due_date - timedelta(hours=1), task.due_date
    if task.date_mode == "range" and task.range_start is not None:
        day = day_start.date()
        last_day = task.range_end or task.range_start
        if task.range_start <= day <= last_day:
            start = datetime.combine(day, time(9, 0))
            return start, start + timedelta(hours=1)
    return None


def _task_color(task: Task, colors: dict[str, str]) -> str:
    for tag in task.tag_list:
        color = colors.get(tag.casefold())
        if color:
            return color
    return UNTAGGED_COLOR


def _segments(
    tasks: list[Task], day_start: datetime, day_end: datetime, colors: dict[str, str]
) -> list[dict]:
    segments: list[dict] = []
    for task in tasks:
        block = _block_times(task, day_start)
        if block is None:
            continue
        start_at, end_at = block
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
                "color": _task_color(task, colors),
                "time_label": f"{start_at:%H:%M}–{end_at:%H:%M}"
                + ("（次日）" if end_at.date() != start_at.date() else ""),
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


def _timeline_tasks(db: Session, first: date, last: date) -> list[Task]:
    window_start = datetime.combine(first, time.min)
    window_end = datetime.combine(last + timedelta(days=1), time.min)
    return list(
        db.scalars(
            select(Task)
            .where(
                Task.archived.is_(False),
                or_(
                    and_(
                        Task.start_at.is_not(None),
                        Task.start_at < window_end,
                        or_(Task.end_at.is_(None), Task.end_at > window_start),
                    ),
                    and_(
                        Task.date_mode == "single",
                        Task.planned_date.is_not(None),
                        Task.planned_date >= first,
                        Task.planned_date <= last,
                    ),
                    and_(
                        Task.date_mode == "deadline",
                        Task.due_date.is_not(None),
                        Task.due_date >= window_start,
                        Task.due_date < window_end,
                    ),
                    and_(
                        Task.date_mode == "range",
                        Task.range_start.is_not(None),
                        Task.range_start <= last,
                        or_(Task.range_end.is_(None), Task.range_end >= first),
                    ),
                ),
            )
            .order_by(Task.start_at, Task.id)
        ).all()
    )


def _timeline(
    db: Session, view: str, anchor: date, colors: dict[str, str]
) -> tuple[list[dict], date, date]:
    if view == "day":
        first = last = anchor
    else:
        first = anchor - timedelta(days=anchor.weekday())
        last = first + timedelta(days=6)
    tasks = _timeline_tasks(db, first, last)

    days: list[dict] = []
    current = first
    while current <= last:
        day_start = datetime.combine(current, time.min)
        day_end = day_start + timedelta(days=1)
        segments = _segments(tasks, day_start, day_end, colors)
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
    tag: str,
    colors: dict[str, str],
) -> dict:
    first, last = _stats_bounds(stats_range, anchor, date_from, date_to)
    start_dt = datetime.combine(first, time.min)
    end_dt = datetime.combine(last + timedelta(days=1), time.min)
    statement = select(Task).where(
        Task.status == "done",
        Task.start_at.is_not(None),
        Task.start_at >= start_dt,
        Task.start_at < end_dt,
    )
    selected_tag = tag.strip()
    if selected_tag:
        statement = statement.where(tag_filter(Task.tags, selected_tag))
    records = db.scalars(statement.order_by(Task.start_at)).all()

    day_list: list[date] = []
    current = first
    while current <= last:
        day_list.append(current)
        current += timedelta(days=1)
    daily = {day: 0 for day in day_list}

    tag_totals: dict[str, dict] = {}
    for task in records:
        seconds = _task_seconds(task)
        start_at = task.start_at
        if start_at is not None and start_at.date() in daily:
            daily[start_at.date()] += seconds
        labels = task.tag_list
        name = labels[0] if labels else ""
        key = name.casefold()
        entry = tag_totals.setdefault(
            key,
            {
                "name": name or "未分类",
                "color": colors.get(key, UNTAGGED_COLOR),
                "seconds": 0,
                "count": 0,
            },
        )
        entry["seconds"] += seconds
        entry["count"] += 1

    daily_seconds = [daily[day] for day in day_list]
    total_seconds = sum(daily_seconds)
    tag_rows = sorted(tag_totals.values(), key=lambda item: (-item["seconds"], item["name"]))
    for row in tag_rows:
        row["hours"] = round(row["seconds"] / 3600, 2)
        row["percent"] = round(row["seconds"] * 100 / total_seconds) if total_seconds else 0

    busiest_day = max(daily, key=lambda day: daily[day]) if total_seconds else None
    return {
        "range_key": stats_range if stats_range in STATS_RANGES else "week",
        "date_from": first.isoformat(),
        "date_to": last.isoformat(),
        "labels": [f"{day.month}/{day.day}" for day in day_list],
        "daily_seconds": daily_seconds,
        "daily_hours": [round(seconds / 3600, 2) for seconds in daily_seconds],
        "tags": tag_rows,
        "total_seconds": total_seconds,
        "total_hours": round(total_seconds / 3600, 2),
        "record_count": len(records),
        "busiest_day": busiest_day,
        "busiest_seconds": daily[busiest_day] if busiest_day else 0,
        "chart_data": {
            "labels": [f"{day.month}/{day.day}" for day in day_list],
            "daily": [round(seconds / 3600, 2) for seconds in daily_seconds],
            "tags": [
                {"name": row["name"], "color": row["color"], "hours": row["hours"]}
                for row in tag_rows
            ],
        },
    }


def _records_page(db: Session, page: int = 1) -> dict:
    statement = (
        select(Task)
        .where(Task.status == "done", Task.start_at.is_not(None))
        .order_by(Task.start_at.desc(), Task.id.desc())
    )
    return paginate(db, statement, page)


def _planned_tasks(db: Session) -> list[Task]:
    tasks = list(
        db.scalars(select(Task).where(Task.status != "done", Task.archived.is_(False))).all()
    )
    return sorted(
        tasks,
        key=lambda task: (
            task.schedule_start is None,
            task.schedule_start or datetime.max,
            task.id,
        ),
    )


def schedule_context(
    db: Session,
    tab: str = "timeline",
    view: str = "week",
    date_value: str = "",
    stats_range: str = "week",
    date_from: str = "",
    date_to: str = "",
    tag: str = "",
    record_page: int = 1,
) -> dict:
    tab = tab if tab in TABS else "timeline"
    view = view if view in VIEWS else "week"
    stats_range = stats_range if stats_range in STATS_RANGES else "week"
    anchor = parse_date(date_value) or today()
    colors = tag_color_map(db)
    days, first, last = _timeline(db, view, anchor, colors)
    if view == "day":
        prev_date = anchor - timedelta(days=1)
        next_date = anchor + timedelta(days=1)
    else:
        prev_date = first - timedelta(days=7)
        next_date = first + timedelta(days=7)
    current = now()
    now_pct = round((current.hour * 60 + current.minute) / 1440 * 100, 4)
    stats = _stats_payload(db, stats_range, anchor, date_from, date_to, tag, colors)
    day_cards = days[0]["segments"] if view == "day" and days else []
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
        "day_cards": day_cards,
        "tag_colors": colors,
        "tag_options": all_task_tags(db),
        "timer_tasks": _planned_tasks(db),
        "records_page": _records_page(db, record_page),
        "stats": stats,
        "stats_filters": {
            "range": stats_range,
            "date_from": stats["date_from"],
            "date_to": stats["date_to"],
            "tag": tag,
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
    tag: str = "",
    record_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = schedule_context(
        db, tab, view, date_value, stats_range, date_from, date_to, tag, record_page
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
    tag: str = "",
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
        tag=tag,
        record_page=record_page,
    )


# ---------- 任务 CRUD ----------


def _task_form_values(task: Task | None = None) -> dict:
    if task is None:
        return {
            "title": "",
            "tags": "",
            "description": "",
            "date_mode": "single",
            "due_date": "",
            "planned_date": today().isoformat(),
            "range_start": "",
            "range_end": "",
            "start_time": "09:00",
            "end_time": "10:00",
        }
    start_at = task.start_at or task.schedule_start
    end_at = task.end_at
    start_time = start_at.strftime("%H:%M") if start_at else ""
    if not start_time and task.due_date:
        start_time = task.due_date.strftime("%H:%M")
    end_time = end_at.strftime("%H:%M") if end_at else ""
    return {
        "title": task.title,
        "tags": task.tags,
        "description": task.description,
        "date_mode": task.date_mode
        if task.date_mode in {"deadline", "single", "range"}
        else "single",
        "due_date": task.due_date.strftime("%Y-%m-%dT%H:%M") if task.due_date else "",
        "planned_date": task.planned_date.isoformat() if task.planned_date else "",
        "range_start": task.range_start.isoformat() if task.range_start else "",
        "range_end": task.range_end.isoformat() if task.range_end else "",
        "start_time": start_time,
        "end_time": end_time,
    }


def _task_form_context(
    db: Session,
    task: Task | None = None,
    values: dict | None = None,
    error: str = "",
) -> dict:
    return {
        "task": task,
        "values": values if values is not None else _task_form_values(task),
        "tag_options": all_task_tags(db),
        "tag_colors": tag_color_map(db),
        "error": error,
    }


def _submitted_task(
    title: str,
    tags: str,
    description: str,
    date_mode: str,
    due_date: str,
    planned_date: str,
    range_start: str,
    range_end: str,
    start_time: str,
    end_time: str,
) -> dict:
    return {
        "title": title,
        "tags": tags,
        "description": description,
        "date_mode": date_mode,
        "due_date": due_date,
        "planned_date": planned_date,
        "range_start": range_start,
        "range_end": range_end,
        "start_time": start_time,
        "end_time": end_time,
    }


def _task_payload(values: dict) -> tuple[dict | None, str]:
    title = values["title"].strip()[:200]
    if not title:
        return None, "任务标题不能为空"
    mode = (
        values["date_mode"] if values["date_mode"] in {"deadline", "single", "range"} else "single"
    )
    due_date = parse_dt(values["due_date"]) if mode == "deadline" else None
    planned_date = parse_date(values["planned_date"]) if mode == "single" else None
    range_start = parse_date(values["range_start"]) if mode == "range" else None
    range_end = parse_date(values["range_end"]) if mode == "range" else None
    if mode == "deadline" and due_date is None:
        return None, "请填写截止时间"
    if mode == "single" and planned_date is None:
        return None, "请选择计划日期"
    if mode == "range":
        if range_start is None:
            return None, "请选择开始日期"
        if range_end is not None and range_end < range_start:
            return None, "结束日期不能早于开始日期"

    start_at: datetime | None = None
    end_at: datetime | None = None
    if mode == "single":
        start_time = _parse_time(values["start_time"])
        end_time = _parse_time(values["end_time"])
        if (start_time is None) != (end_time is None):
            return None, "请同时填写开始与结束时间"
        if start_time is not None and end_time is not None and planned_date is not None:
            start_at = datetime.combine(planned_date, start_time)
            end_at = datetime.combine(planned_date, end_time)
            if end_at <= start_at:
                end_at += timedelta(days=1)

    return {
        "title": title,
        "description": values["description"].strip(),
        "tags": normalize_single_tag(values["tags"]),
        "date_mode": mode,
        "due_date": due_date,
        "planned_date": planned_date,
        "range_start": range_start,
        "range_end": range_end,
        "start_at": start_at,
        "end_at": end_at,
    }, ""


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
        values["planned_date"] = parsed_day.isoformat()
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
    tags: str = Form(""),
    description: str = Form(""),
    date_mode: str = Form("single"),
    due_date: str = Form(""),
    planned_date: str = Form(""),
    range_start: str = Form(""),
    range_end: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    values = _submitted_task(
        title,
        tags,
        description,
        date_mode,
        due_date,
        planned_date,
        range_start,
        range_end,
        start_time,
        end_time,
    )
    payload, error = _task_payload(values)
    if error:
        return _modal_error(
            request,
            "partials/modals/schedule_task_form.html",
            _task_form_context(db, None, values),
            error,
        )
    ensure_tags(db, payload["tags"])
    db.add(Task(**payload))
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.get("/schedule/tasks/{task_id}/detail", response_class=HTMLResponse)
def schedule_task_detail(
    task_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return render_partial(
        request,
        "partials/modals/schedule_task_detail.html",
        {
            "task": task,
            "duration_seconds": _task_seconds(task),
            "tag_colors": tag_color_map(db),
        },
    )


@router.get("/schedule/tasks/{task_id}/edit", response_class=HTMLResponse)
def schedule_task_edit_form(
    task_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
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
    tags: str = Form(""),
    description: str = Form(""),
    date_mode: str = Form("single"),
    due_date: str = Form(""),
    planned_date: str = Form(""),
    range_start: str = Form(""),
    range_end: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    values = _submitted_task(
        title,
        tags,
        description,
        date_mode,
        due_date,
        planned_date,
        range_start,
        range_end,
        start_time,
        end_time,
    )
    payload, error = _task_payload(values)
    if error:
        return _modal_error(
            request,
            "partials/modals/schedule_task_form.html",
            _task_form_context(db, task, values),
            error,
        )
    for field, value in payload.items():
        setattr(task, field, value)
    if task.status == "done":
        task.duration_seconds = _task_seconds(task)
    ensure_tags(db, payload["tags"])
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.post("/schedule/tasks/{task_id}/delete", response_class=HTMLResponse)
def schedule_task_delete(task_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


# ---------- 专注计时 ----------


def _record_data(task: Task) -> dict:
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
        existing = db.scalar(select(Task).where(Task.client_token == token))
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
    tags = normalize_single_tag(payload.tags)

    if payload.task_id:
        task = db.get(Task, payload.task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status == "done":
            raise HTTPException(status_code=409, detail="该任务已完成计时")
        task.start_at = started_at
        task.end_at = ended_at
        task.duration_seconds = duration
        task.planned_date = started_at.date()
        task.date_mode = "single"
        if tags:
            task.tags = tags
        if payload.description.strip():
            task.description = payload.description.strip()
        task.status = "done"
        task.progress = 100
        task.completed_at = now()
        task.client_token = token or None
        ensure_tags(db, task.tags)
        db.commit()
        db.refresh(task)
        return JSONResponse({"ok": True, "message": "", "data": _record_data(task)})

    title = payload.title.strip()[:200]
    if not title:
        raise HTTPException(status_code=422, detail="临时任务名称不能为空")

    task = Task(
        title=title,
        description=payload.description.strip(),
        tags=tags,
        status="done",
        date_mode="single",
        planned_date=started_at.date(),
        start_at=started_at,
        end_at=ended_at,
        duration_seconds=duration,
        progress=100,
        completed_at=now(),
        client_token=token or None,
    )
    if tags:
        ensure_tags(db, tags)
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
        {
            "records_page": _records_page(db, record_page),
            "today": today(),
            "tag_colors": tag_color_map(db),
        },
    )


def _record_form_values(record: Task) -> dict:
    start_at = record.start_at or now()
    end_at = record.end_at or (start_at + timedelta(minutes=max(1, record.duration_seconds // 60)))
    return {
        "title": record.title,
        "tags": record.tags,
        "date": start_at.date().isoformat(),
        "start_time": start_at.strftime("%H:%M"),
        "end_time": end_at.strftime("%H:%M"),
        "description": record.description,
    }


def _record_form_context(
    db: Session,
    record: Task,
    values: dict | None = None,
    error: str = "",
) -> dict:
    return {
        "record": record,
        "values": values if values is not None else _record_form_values(record),
        "tag_options": all_task_tags(db),
        "tag_colors": tag_color_map(db),
        "error": error,
    }


@router.get("/schedule/records/{record_id}/edit", response_class=HTMLResponse)
def schedule_record_edit_form(
    record_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    record = db.get(Task, record_id)
    if record is None or record.status != "done" or record.start_at is None:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    return render_partial(
        request, "partials/modals/schedule_record_form.html", _record_form_context(db, record)
    )


@router.post("/schedule/records/{record_id}/edit", response_class=HTMLResponse)
def schedule_record_update(
    record_id: int,
    request: Request,
    title: str = Form(""),
    tags: str = Form(""),
    date_value: str = Form("", alias="date"),
    start_time: str = Form("09:00"),
    end_time: str = Form("10:00"),
    description: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    record = db.get(Task, record_id)
    if record is None or record.status != "done" or record.start_at is None:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    values = {
        "title": title,
        "tags": tags,
        "date": date_value,
        "start_time": start_time,
        "end_time": end_time,
        "description": description,
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
    record.title = clean_title
    record.tags = normalize_single_tag(tags)
    record.description = description.strip()
    record.date_mode = "single"
    record.planned_date = start_at.date()
    record.start_at = start_at
    record.end_at = end_at
    record.duration_seconds = int((end_at - start_at).total_seconds())
    record.status = "done"
    ensure_tags(db, record.tags)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)


@router.post("/schedule/records/{record_id}/delete", response_class=HTMLResponse)
def schedule_record_delete(record_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    record = db.get(Task, record_id)
    if record is None or record.status != "done" or record.start_at is None:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    db.delete(record)
    db.commit()
    return HTMLResponse("", headers=SCHEDULE_DONE)
