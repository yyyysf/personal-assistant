"""任务管理页面：看板、筛选、分页、标签管理与弹窗 CRUD。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date, parse_dt
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.tags import (
    all_task_tags,
    clean_tag,
    ensure_tags,
    normalize_single_tag,
    rename_tag,
    set_tag_color,
    tag_color_map,
    task_tag_counts,
)
from src.core.taxonomy import tag_filter
from src.models import Tag, Task

router = APIRouter()
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
TASK_STATUSES = {"todo", "doing", "done"}
DATE_MODES = {"deadline", "single", "range"}

REFRESH = {"HX-Trigger": '{"list:refresh": true}'}
MODAL_DONE = {"HX-Trigger": '{"modal:close": true, "list:refresh": true}'}


def _task_order():
    priority = case(
        (Task.priority == "high", 0),
        (Task.priority == "medium", 1),
        else_=2,
    )
    return priority, Task.due_date.is_(None), Task.due_date, Task.id.desc()


def _filter_tasks(stmt, tags: list[str], date_from: str, date_to: str, q: str):
    for tag in tags:
        stmt = stmt.where(tag_filter(Task.tags, tag))
    start_date = parse_date(date_from)
    end_date = parse_date(date_to)
    if start_date:
        stmt = stmt.where(
            func.date(func.coalesce(Task.due_date, Task.planned_date, Task.range_start))
            >= start_date.isoformat()
        )
    if end_date:
        stmt = stmt.where(
            func.date(
                func.coalesce(Task.range_end, Task.due_date, Task.planned_date, Task.range_start)
            )
            <= end_date.isoformat()
        )
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Task.title.ilike(pattern), Task.description.ilike(pattern), Task.tags.ilike(pattern)
            )
        )
    return stmt


def todo_context(
    db: Session,
    tags: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
) -> dict:
    tags = [tag for tag in (tags or []) if tag]
    base = select(Task).where(Task.archived.is_(False))
    filtered = _filter_tasks(base, tags, date_from, date_to, q)

    columns = []
    for key, label, param, page_number in (
        ("todo", "待办", "page_todo", page_todo),
        ("doing", "进行中", "page_doing", page_doing),
        ("done", "已完成", "page_done", page_done),
    ):
        stmt = filtered.where(Task.status == key).order_by(*_task_order())
        columns.append(
            {
                "key": key,
                "label": label,
                "param": param,
                "page": paginate(db, stmt, page_number),
            }
        )

    archived = db.scalars(
        select(Task)
        .where(Task.archived.is_(True))
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(20)
    ).all()

    return {
        "filters": {
            "tags": tags,
            "date_from": date_from,
            "date_to": date_to,
            "q": q,
        },
        "tag_options": all_task_tags(db),
        "tag_colors": tag_color_map(db),
        "columns": columns,
        "archived": archived,
        "error": "",
    }


def _content_response(
    request: Request,
    db: Session,
    tags: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    error: str = "",
) -> HTMLResponse:
    context = todo_context(
        db,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page_todo=page_todo,
        page_doing=page_doing,
        page_done=page_done,
    )
    context["error"] = error
    return render_partial(request, "partials/todo_content.html", context)


def _task_form_context(db: Session, task: Task | None = None) -> dict:
    return {
        "task": task,
        "tag_options": all_task_tags(db),
        "tag_colors": tag_color_map(db),
        "error": "",
    }


def _modal_error(request: Request, template: str, context: dict, message: str) -> HTMLResponse:
    context["error"] = message
    response = render_partial(request, template, context)
    response.headers["HX-Retarget"] = "#modal-body"
    return response


def _task_payload(
    title: str,
    description: str,
    tags: str,
    date_mode: str,
    due_date: str,
    planned_date: str,
    range_start: str,
    range_end: str,
) -> dict:
    mode = date_mode if date_mode in DATE_MODES else "single"
    return {
        "title": title.strip()[:200],
        "description": description.strip(),
        "tags": normalize_single_tag(tags),
        "date_mode": mode,
        "due_date": parse_dt(due_date) if mode == "deadline" else None,
        "planned_date": parse_date(planned_date) if mode == "single" else None,
        "range_start": parse_date(range_start) if mode == "range" else None,
        "range_end": parse_date(range_end) if mode == "range" else None,
    }


def _validate_task(payload: dict) -> str:
    if not payload["title"]:
        return "任务标题不能为空"
    if payload["date_mode"] == "range":
        start, end = payload["range_start"], payload["range_end"]
        if start and end and end < start:
            return "结束日期不能早于开始日期"
    return ""


def _sync_schedule_dates(task: Task, payload: dict) -> None:
    """任务页改日期时保持时间轴锚点一致；非单日任务交给时间轴按日期推导。"""
    if payload["date_mode"] == "single" and payload["planned_date"]:
        if task.start_at is not None:
            duration = timedelta(hours=1)
            if task.end_at and task.end_at > task.start_at:
                duration = task.end_at - task.start_at
            start = datetime.combine(payload["planned_date"], task.start_at.time())
            task.start_at = start
            task.end_at = start + duration
    elif task.status != "done":
        task.start_at = None
        task.end_at = None
        task.duration_seconds = 0


def _apply_status(task: Task, status: str) -> None:
    task.status = status
    task.completed_at = datetime.now() if status == "done" else None
    if status == "done":
        task.progress = 100


@router.get("/todo", response_class=HTMLResponse)
def todo_page(
    request: Request,
    tag: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = todo_context(
        db,
        tags=tag,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page_todo=page_todo,
        page_doing=page_doing,
        page_done=page_done,
    )
    return render(request, "todo.html", context, active="todo")


@router.get("/todo/content", response_class=HTMLResponse)
def todo_content(
    request: Request,
    tag: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(
        request,
        db,
        tags=tag,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page_todo=page_todo,
        page_doing=page_doing,
        page_done=page_done,
    )


@router.get("/todo/tasks/new", response_class=HTMLResponse)
def task_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/todo_task_form.html", _task_form_context(db))


@router.post("/todo/tasks/new", response_class=HTMLResponse)
def task_create(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    date_mode: str = Form("single"),
    due_date: str = Form(""),
    planned_date: str = Form(""),
    range_start: str = Form(""),
    range_end: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = _task_payload(
        title,
        description,
        tags,
        date_mode,
        due_date,
        planned_date,
        range_start,
        range_end,
    )
    error = _validate_task(payload)
    if error:
        return _modal_error(
            request, "partials/modals/todo_task_form.html", _task_form_context(db), error
        )
    ensure_tags(db, payload["tags"])
    task = Task(**payload)
    db.add(task)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/todo/tasks/{task_id}/detail", response_class=HTMLResponse)
def task_detail(task_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return render_partial(
        request,
        "partials/modals/todo_task_detail.html",
        {"task": task, "tag_colors": tag_color_map(db)},
    )


@router.get("/todo/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit_form(task_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return render_partial(
        request, "partials/modals/todo_task_form.html", _task_form_context(db, task)
    )


@router.post("/todo/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_update(
    task_id: int,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    date_mode: str = Form("single"),
    due_date: str = Form(""),
    planned_date: str = Form(""),
    range_start: str = Form(""),
    range_end: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    payload = _task_payload(
        title,
        description,
        tags,
        date_mode,
        due_date,
        planned_date,
        range_start,
        range_end,
    )
    error = _validate_task(payload)
    if error:
        return _modal_error(
            request, "partials/modals/todo_task_form.html", _task_form_context(db, task), error
        )
    for field, value in payload.items():
        setattr(task, field, value)
    _sync_schedule_dates(task, payload)
    ensure_tags(db, payload["tags"])
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/todo/tasks", response_class=HTMLResponse)
def create_task_legacy(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("medium"),
    tags: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not title.strip():
        return _content_response(request, db, error="任务标题不能为空")
    clean_tags = normalize_single_tag(tags)
    ensure_tags(db, clean_tags)
    task = Task(
        title=title.strip()[:200],
        description=description.strip(),
        priority=priority if priority in PRIORITY_ORDER else "medium",
        tags=clean_tags,
        due_date=parse_dt(due_date),
    )
    db.add(task)
    db.commit()
    return _content_response(request, db)


@router.post("/todo/tasks/{task_id}/status", response_class=HTMLResponse)
def update_task_status(
    task_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="非法的任务状态")
    _apply_status(task, status)
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/todo/tasks/{task_id}/delete", response_class=HTMLResponse)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/todo/archive", response_class=HTMLResponse)
def archive_done(db: Session = Depends(get_db)) -> HTMLResponse:
    done_tasks = db.scalars(
        select(Task).where(Task.status == "done", Task.archived.is_(False))
    ).all()
    for task in done_tasks:
        task.archived = True
    db.commit()
    return HTMLResponse("", headers=REFRESH)


# ---------- 标签管理 ----------


TAG_REFRESH = {"HX-Trigger": '{"list:refresh": true}'}


def _tag_manage_context(db: Session, error: str = "") -> dict:
    ensure_tags(db, all_task_tags(db))
    db.commit()
    counts = task_tag_counts(db)
    tags = db.scalars(select(Tag).order_by(func.lower(Tag.name), Tag.id)).all()
    return {
        "tag_rows": [{"tag": tag, "count": counts[tag.name.casefold()]} for tag in tags],
        "error": error,
    }


def _tag_response(request: Request, db: Session, error: str = "") -> HTMLResponse:
    response = render_partial(request, "partials/tag_manage.html", _tag_manage_context(db, error))
    response.headers.update(TAG_REFRESH)
    return response


@router.get("/todo/tags/manage", response_class=HTMLResponse)
def tag_manage(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _tag_response(request, db)


@router.post("/todo/tags/new", response_class=HTMLResponse)
def tag_create(
    request: Request,
    name: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    clean = clean_tag(name)
    if not clean:
        return _tag_response(request, db, "标签名称不能为空")
    exists = any(tag.name.casefold() == clean.casefold() for tag in db.scalars(select(Tag)).all())
    if exists:
        return _tag_response(request, db, "该标签已存在")
    ensure_tags(db, [clean])
    db.commit()
    return _tag_response(request, db)


@router.post("/todo/tags/{tag_id}/rename", response_class=HTMLResponse)
def tag_rename(
    tag_id: int,
    request: Request,
    name: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    error = rename_tag(db, tag, name)
    if error:
        db.rollback()
        return _tag_response(request, db, error)
    db.commit()
    return _tag_response(request, db)


@router.post("/todo/tags/{tag_id}/recolor", response_class=HTMLResponse)
def tag_recolor(
    tag_id: int,
    request: Request,
    color: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    error = set_tag_color(tag, color)
    if error:
        db.rollback()
        return _tag_response(request, db, error)
    db.commit()
    return _tag_response(request, db)
