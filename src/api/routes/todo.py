"""Todo & 目标管理页面：看板、今日待办、历史归档。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.common import parse_dt, parse_int
from src.api.deps import get_db, render, render_partial
from src.models import Goal, Task

router = APIRouter()
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _sort_tasks(tasks: list[Task]) -> list[Task]:
    return sorted(
        tasks,
        key=lambda task: (
            PRIORITY_ORDER.get(task.priority, 9),
            task.due_date or datetime.max,
            -task.id,
        ),
    )


def todo_context(db: Session) -> dict:
    tasks = db.scalars(select(Task).where(Task.archived.is_(False)).order_by(Task.id.desc())).all()
    archived = db.scalars(
        select(Task)
        .where(Task.archived.is_(True))
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(50)
    ).all()
    groups = {
        "todo": _sort_tasks([task for task in tasks if task.status == "todo"]),
        "doing": _sort_tasks([task for task in tasks if task.status == "doing"]),
        "done": _sort_tasks([task for task in tasks if task.status == "done"]),
    }
    goals = db.scalars(select(Goal).order_by(Goal.id)).all()
    return {"groups": groups, "archived": archived, "goals": goals, "error": ""}


def _board_response(request: Request, db: Session, error: str = "") -> HTMLResponse:
    context = todo_context(db)
    context["error"] = error
    return render_partial(request, "partials/todo_board.html", context)


@router.get("/todo", response_class=HTMLResponse)
def todo_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(request, "todo.html", todo_context(db), active="todo")


@router.get("/todo/board", response_class=HTMLResponse)
def todo_board(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _board_response(request, db)


@router.post("/todo/tasks", response_class=HTMLResponse)
def create_task(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("medium"),
    tags: str = Form(""),
    due_date: str = Form(""),
    goal_id: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not title.strip():
        return _board_response(request, db, "任务标题不能为空")
    if priority not in PRIORITY_ORDER:
        priority = "medium"
    db.add(
        Task(
            title=title.strip(),
            description=description.strip(),
            priority=priority,
            tags=tags.strip(),
            due_date=parse_dt(due_date),
            goal_id=parse_int(goal_id),
        )
    )
    db.commit()
    return _board_response(request, db)


@router.post("/todo/tasks/{task_id}/status", response_class=HTMLResponse)
def update_task_status(
    task_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if status not in {"todo", "doing", "done"}:
        raise HTTPException(status_code=400, detail="非法的任务状态")
    task.status = status
    task.completed_at = datetime.now() if status == "done" else None
    db.commit()
    return _board_response(request, db)


@router.post("/todo/tasks/{task_id}/delete", response_class=HTMLResponse)
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return _board_response(request, db)


@router.post("/todo/archive", response_class=HTMLResponse)
def archive_done(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    done_tasks = db.scalars(
        select(Task).where(Task.status == "done", Task.archived.is_(False))
    ).all()
    for task in done_tasks:
        task.archived = True
    db.commit()
    return _board_response(request, db)


@router.post("/todo/goals", response_class=HTMLResponse)
def create_goal(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    target_date: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if title.strip():
        db.add(
            Goal(
                title=title.strip(),
                description=description.strip(),
                target_date=parse_dt(target_date).date() if parse_dt(target_date) else None,
            )
        )
        db.commit()
    goals = db.scalars(select(Goal).order_by(Goal.id)).all()
    return render_partial(request, "partials/todo_goals.html", {"goals": goals})


@router.post("/todo/goals/{goal_id}/progress", response_class=HTMLResponse)
def update_goal_progress(
    goal_id: int,
    request: Request,
    progress: int = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    goal.progress = max(0, min(100, progress))
    db.commit()
    goals = db.scalars(select(Goal).order_by(Goal.id)).all()
    return render_partial(request, "partials/todo_goals.html", {"goals": goals})
