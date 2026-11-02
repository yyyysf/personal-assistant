"""动态学习路线：AI 视频 / AI 音乐，LLM 动态拆分今日学习任务。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.api.common import LEARNING_LABELS, ensure_track, parse_date, recalculate_progress
from src.api.deps import get_db, render, render_partial
from src.core.time_utils import today
from src.llm.assistant import generate_learning_plan
from src.models import LearningItem, LearningLog

router = APIRouter()


def _split_items(track) -> dict:
    items = sorted(track.items, key=lambda item: (item.status == "done", item.id))
    today_items = [
        item for item in items if item.scheduled_date == today() and item.status != "done"
    ]
    open_items = [item for item in items if item.status != "done"]
    return {
        "today_items": today_items,
        "open_items": open_items,
        "upcoming_items": [item for item in open_items if item not in today_items],
        "done_items": [item for item in items if item.status == "done"][-10:],
    }


def learning_context(db: Session, category: str) -> dict:
    track = ensure_track(db, category)
    logs = sorted(track.logs, key=lambda log: log.created_at, reverse=True)[:10]
    context = {
        "category": category,
        "category_label": LEARNING_LABELS[category],
        "track": track,
        "logs": logs,
        "notice": "",
        "error": "",
    }
    context.update(_split_items(track))
    return context


@router.get("/learning/{category}", response_class=HTMLResponse)
def learning_page(category: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    return render(
        request,
        "learning.html",
        learning_context(db, category),
        active=category,
    )


@router.post("/learning/{category}/plan", response_class=HTMLResponse)
def learning_plan(category: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    track = ensure_track(db, category)
    done = [item.title for item in track.items if item.status == "done"]
    opened = [item.title for item in track.items if item.status != "done"]
    logs = [log.content for log in track.logs]
    plan = generate_learning_plan(
        category, LEARNING_LABELS[category], track.progress, done, opened, logs
    )
    existing_today = {
        item.title
        for item in track.items
        if item.scheduled_date == today() and item.status != "done"
    }
    added = 0
    for entry in plan:
        title = entry["title"].strip()
        if title in existing_today:
            continue
        db.add(
            LearningItem(
                track_id=track.id,
                title=title,
                description=entry.get("description", ""),
                resource_url=entry.get("resource_url", ""),
                scheduled_date=today(),
                mastery=0,
            )
        )
        added += 1
    db.add(
        LearningLog(
            track_id=track.id,
            content=f"按当前进度动态生成今日学习计划，新增 {added} 项任务。",
            mastery=track.progress,
            source="agent",
        )
    )
    db.commit()
    context = learning_context(db, category)
    context["notice"] = f"已生成 {added} 项今日学习任务" if added else "今日任务已存在，未重复添加"
    return render_partial(request, "partials/learning_content.html", context)


@router.post("/learning/{category}/items", response_class=HTMLResponse)
def learning_add_item(
    category: str,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    resource_url: str = Form(""),
    scheduled_date: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    track = ensure_track(db, category)
    context = learning_context(db, category)
    if not title.strip():
        context["error"] = "任务标题不能为空"
    else:
        db.add(
            LearningItem(
                track_id=track.id,
                title=title.strip(),
                description=description.strip(),
                resource_url=resource_url.strip(),
                scheduled_date=parse_date(scheduled_date) or today(),
            )
        )
        db.commit()
        context = learning_context(db, category)
        context["notice"] = "学习任务已添加"
    return render_partial(request, "partials/learning_content.html", context)


@router.post("/learning/{category}/items/{item_id}/complete", response_class=HTMLResponse)
def learning_complete_item(
    category: str, item_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    track = ensure_track(db, category)
    item = db.get(LearningItem, item_id)
    if item is None or item.track_id != track.id:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    item.status = "done"
    item.completed_at = datetime.now()
    item.mastery = max(item.mastery, 80)
    recalculate_progress(track)
    db.commit()
    context = learning_context(db, category)
    context["notice"] = "完成记录已更新"
    return render_partial(request, "partials/learning_content.html", context)


@router.post("/learning/{category}/items/{item_id}/mastery", response_class=HTMLResponse)
def learning_update_mastery(
    category: str,
    item_id: int,
    request: Request,
    mastery: int = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    track = ensure_track(db, category)
    item = db.get(LearningItem, item_id)
    if item is None or item.track_id != track.id:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    item.mastery = max(0, min(100, mastery))
    if item.mastery >= 80 and item.status != "done":
        item.status = "done"
        item.completed_at = datetime.now()
    recalculate_progress(track)
    db.commit()
    return render_partial(request, "partials/learning_content.html", learning_context(db, category))


@router.post("/learning/{category}/logs", response_class=HTMLResponse)
def learning_add_log(
    category: str,
    request: Request,
    content: str = Form(""),
    mastery: int = Form(0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    track = ensure_track(db, category)
    if content.strip():
        db.add(
            LearningLog(
                track_id=track.id,
                content=content.strip(),
                mastery=max(0, min(100, mastery)),
            )
        )
        db.commit()
    context = learning_context(db, category)
    context["notice"] = "学习记忆已保存"
    return render_partial(request, "partials/learning_logs.html", context)


@router.get("/learning/{category}/items", response_class=HTMLResponse)
def learning_items(category: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    return render_partial(request, "partials/learning_content.html", learning_context(db, category))
