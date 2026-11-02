"""Todo & 目标管理页面：看板、目标、筛选、分页与弹窗 CRUD。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date, parse_dt, parse_int
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.taxonomy import all_tags, category_names, tag_filter
from src.models import Goal, Task

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


def _filter_tasks(
    stmt,
    category: str,
    tags: list[str],
    date_from: str,
    date_to: str,
    q: str,
):
    if category:
        stmt = stmt.where(Task.category == category)
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


def _filter_goals(stmt, category: str, tags: list[str], q: str):
    if category:
        stmt = stmt.where(Goal.category == category)
    for tag in tags:
        stmt = stmt.where(tag_filter(Goal.tags, tag))
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Goal.title.ilike(pattern), Goal.description.ilike(pattern)))
    return stmt


def todo_context(
    db: Session,
    tab: str = "board",
    category: str = "",
    tags: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    page_goals: int = 1,
) -> dict:
    tags = [tag for tag in (tags or []) if tag]
    base = select(Task).where(Task.archived.is_(False))
    filtered = _filter_tasks(base, category, tags, date_from, date_to, q)

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

    goals_stmt = _filter_goals(select(Goal), category, tags, q).order_by(Goal.id)
    goals_page = paginate(db, goals_stmt, page_goals)

    archived = db.scalars(
        select(Task)
        .where(Task.archived.is_(True))
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(20)
    ).all()

    return {
        "tab": tab if tab in {"board", "goals"} else "board",
        "filters": {
            "category": category,
            "tags": tags,
            "date_from": date_from,
            "date_to": date_to,
            "q": q,
        },
        "categories": category_names(db, "task"),
        "tag_options": all_tags(db, "task"),
        "columns": columns,
        "goals": db.scalars(select(Goal).order_by(Goal.id)).all(),
        "goals_page": goals_page,
        "archived": archived,
        "error": "",
    }


def _content_response(
    request: Request,
    db: Session,
    tab: str = "board",
    category: str = "",
    tags: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    page_goals: int = 1,
    error: str = "",
) -> HTMLResponse:
    context = todo_context(
        db,
        tab=tab,
        category=category,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page_todo=page_todo,
        page_doing=page_doing,
        page_done=page_done,
        page_goals=page_goals,
    )
    context["error"] = error
    return render_partial(request, "partials/todo_content.html", context)


def _task_form_context(db: Session, task: Task | None = None) -> dict:
    return {
        "task": task,
        "goals": db.scalars(select(Goal).order_by(Goal.id)).all(),
        "categories": category_names(db, "task"),
        "tag_options": all_tags(db, "task"),
        "error": "",
    }


def _goal_form_context(db: Session, goal: Goal | None = None) -> dict:
    return {
        "goal": goal,
        "categories": category_names(db, "task"),
        "tag_options": all_tags(db, "task"),
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
    priority: str,
    category: str,
    tags: str,
    date_mode: str,
    due_date: str,
    planned_date: str,
    range_start: str,
    range_end: str,
    progress: int,
    goal_id: str,
    status: str,
) -> dict:
    mode = date_mode if date_mode in DATE_MODES else "deadline"
    return {
        "title": title.strip()[:200],
        "description": description.strip(),
        "priority": priority if priority in PRIORITY_ORDER else "medium",
        "category": category.strip()[:60],
        "tags": tags.strip()[:200],
        "status": status if status in TASK_STATUSES else "todo",
        "date_mode": mode,
        "due_date": parse_dt(due_date) if mode == "deadline" else None,
        "planned_date": parse_date(planned_date) if mode == "single" else None,
        "range_start": parse_date(range_start) if mode == "range" else None,
        "range_end": parse_date(range_end) if mode == "range" else None,
        "progress": max(0, min(100, progress)),
        "goal_id": parse_int(goal_id),
    }


def _validate_task(payload: dict) -> str:
    if not payload["title"]:
        return "任务标题不能为空"
    if payload["date_mode"] == "range":
        start, end = payload["range_start"], payload["range_end"]
        if start and end and end < start:
            return "结束日期不能早于开始日期"
    return ""


def _apply_status(task: Task, status: str) -> None:
    task.status = status
    task.completed_at = datetime.now() if status == "done" else None
    if status == "done":
        task.progress = 100


@router.get("/todo", response_class=HTMLResponse)
def todo_page(
    request: Request,
    tab: str = "board",
    category: str = "",
    tag: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    page_goals: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = todo_context(
        db,
        tab=tab,
        category=category,
        tags=tag,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page_todo=page_todo,
        page_doing=page_doing,
        page_done=page_done,
        page_goals=page_goals,
    )
    return render(request, "todo.html", context, active="todo")


@router.get("/todo/content", response_class=HTMLResponse)
def todo_content(
    request: Request,
    tab: str = "board",
    category: str = "",
    tag: list[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page_todo: int = 1,
    page_doing: int = 1,
    page_done: int = 1,
    page_goals: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(
        request,
        db,
        tab=tab,
        category=category,
        tags=tag,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page_todo=page_todo,
        page_doing=page_doing,
        page_done=page_done,
        page_goals=page_goals,
    )


@router.get("/todo/tasks/new", response_class=HTMLResponse)
def task_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/todo_task_form.html", _task_form_context(db))


@router.post("/todo/tasks/new", response_class=HTMLResponse)
def task_create(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("medium"),
    category: str = Form(""),
    tags: str = Form(""),
    date_mode: str = Form("deadline"),
    due_date: str = Form(""),
    planned_date: str = Form(""),
    range_start: str = Form(""),
    range_end: str = Form(""),
    progress: int = Form(0),
    goal_id: str = Form(""),
    status: str = Form("todo"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = _task_payload(
        title,
        description,
        priority,
        category,
        tags,
        date_mode,
        due_date,
        planned_date,
        range_start,
        range_end,
        progress,
        goal_id,
        status,
    )
    error = _validate_task(payload)
    if error:
        return _modal_error(
            request, "partials/modals/todo_task_form.html", _task_form_context(db), error
        )
    task = Task(**payload)
    if task.status == "done":
        task.completed_at = datetime.now()
    db.add(task)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/todo/tasks/{task_id}/detail", response_class=HTMLResponse)
def task_detail(task_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return render_partial(request, "partials/modals/todo_task_detail.html", {"task": task})


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
    priority: str = Form("medium"),
    category: str = Form(""),
    tags: str = Form(""),
    date_mode: str = Form("deadline"),
    due_date: str = Form(""),
    planned_date: str = Form(""),
    range_start: str = Form(""),
    range_end: str = Form(""),
    progress: int = Form(0),
    goal_id: str = Form(""),
    status: str = Form("todo"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    payload = _task_payload(
        title,
        description,
        priority,
        category,
        tags,
        date_mode,
        due_date,
        planned_date,
        range_start,
        range_end,
        progress,
        goal_id,
        status,
    )
    error = _validate_task(payload)
    if error:
        return _modal_error(
            request, "partials/modals/todo_task_form.html", _task_form_context(db, task), error
        )
    previous_status = task.status
    for field, value in payload.items():
        setattr(task, field, value)
    if task.status != previous_status or task.status == "done":
        task.completed_at = datetime.now() if task.status == "done" else None
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/todo/tasks", response_class=HTMLResponse)
def create_task_legacy(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("medium"),
    category: str = Form(""),
    tags: str = Form(""),
    due_date: str = Form(""),
    goal_id: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not title.strip():
        return _content_response(request, db, error="任务标题不能为空")
    task = Task(
        title=title.strip()[:200],
        description=description.strip(),
        priority=priority if priority in PRIORITY_ORDER else "medium",
        category=category.strip()[:60],
        tags=tags.strip()[:200],
        due_date=parse_dt(due_date),
        goal_id=parse_int(goal_id),
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


@router.get("/todo/goals/new", response_class=HTMLResponse)
def goal_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/todo_goal_form.html", _goal_form_context(db))


@router.post("/todo/goals/new", response_class=HTMLResponse)
def goal_create(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    target_date: str = Form(""),
    progress: int = Form(0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not title.strip():
        return _modal_error(
            request,
            "partials/modals/todo_goal_form.html",
            _goal_form_context(db),
            "目标标题不能为空",
        )
    goal = Goal(
        title=title.strip()[:200],
        description=description.strip(),
        category=category.strip()[:60],
        tags=tags.strip()[:200],
        target_date=parse_date(target_date),
        progress=max(0, min(100, progress)),
    )
    if goal.progress >= 100:
        goal.completed_at = datetime.now()
    db.add(goal)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/todo/goals/{goal_id}/detail", response_class=HTMLResponse)
def goal_detail(goal_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    return render_partial(request, "partials/modals/todo_goal_detail.html", {"goal": goal})


@router.get("/todo/goals/{goal_id}/edit", response_class=HTMLResponse)
def goal_edit_form(goal_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    return render_partial(
        request, "partials/modals/todo_goal_form.html", _goal_form_context(db, goal)
    )


@router.post("/todo/goals/{goal_id}/edit", response_class=HTMLResponse)
def goal_update(
    goal_id: int,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    target_date: str = Form(""),
    progress: int = Form(0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    if not title.strip():
        return _modal_error(
            request,
            "partials/modals/todo_goal_form.html",
            _goal_form_context(db, goal),
            "目标标题不能为空",
        )
    goal.title = title.strip()[:200]
    goal.description = description.strip()
    goal.category = category.strip()[:60]
    goal.tags = tags.strip()[:200]
    goal.target_date = parse_date(target_date)
    goal.progress = max(0, min(100, progress))
    goal.completed_at = datetime.now() if goal.progress >= 100 else None
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/todo/goals/{goal_id}/progress", response_class=HTMLResponse)
def update_goal_progress(
    goal_id: int,
    progress: int = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    goal.progress = max(0, min(100, progress))
    goal.completed_at = datetime.now() if goal.progress >= 100 else None
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/todo/goals/{goal_id}/delete", response_class=HTMLResponse)
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    for task in goal.tasks:
        task.goal_id = None
    db.delete(goal)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)
