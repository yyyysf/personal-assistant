"""动态学习路线：AI 视频 / AI 音乐，LLM 动态拆分今日学习任务。"""

import json
import math
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.api.common import LEARNING_LABELS, ensure_track, parse_date, recalculate_progress
from src.api.deps import get_db, render, render_partial
from src.core.time_utils import today
from src.llm.assistant import generate_learning_plan
from src.models import LearningItem, LearningLog

router = APIRouter()
PER_PAGE = 5
REFRESH = {"HX-Trigger": '{"list:refresh": true}'}
MODAL_DONE = {"HX-Trigger": '{"modal:close": true, "list:refresh": true}'}


def _paged(items: list, page: int) -> dict:
    total = len(items)
    pages = max(1, math.ceil(total / PER_PAGE))
    page = min(max(1, page), pages)
    start = (page - 1) * PER_PAGE
    return {
        "items": items[start : start + PER_PAGE],
        "page": page,
        "pages": pages,
        "total": total,
        "per_page": PER_PAGE,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def _split_items(track, page_today: int, page_upcoming: int, page_done: int) -> dict:
    items = sorted(track.items, key=lambda item: (item.status == "done", item.id))
    today_items = [
        item for item in items if item.scheduled_date == today() and item.status != "done"
    ]
    open_items = [item for item in items if item.status != "done"]
    upcoming = [item for item in open_items if item not in today_items]
    upcoming.sort(key=lambda item: (item.scheduled_date is None, item.scheduled_date or date.max))
    done = sorted(
        [item for item in items if item.status == "done"],
        key=lambda item: item.completed_at or datetime.min,
        reverse=True,
    )
    today_page = _paged(today_items, page_today)
    upcoming_page = _paged(upcoming, page_upcoming)
    done_page = _paged(done, page_done)
    return {
        "today_items": today_page["items"],
        "today_page": today_page,
        "upcoming_items": upcoming_page["items"],
        "upcoming_page": upcoming_page,
        "done_items": done_page["items"],
        "done_page": done_page,
        "open_count": len(open_items),
        "done_count": len(done),
    }


def learning_context(
    db: Session,
    category: str,
    page_today: int = 1,
    page_upcoming: int = 1,
    page_done: int = 1,
    page_logs: int = 1,
) -> dict:
    track = ensure_track(db, category)
    logs = sorted(track.logs, key=lambda log: log.created_at, reverse=True)
    logs_page = _paged(logs, page_logs)
    context = {
        "category": category,
        "category_label": LEARNING_LABELS[category],
        "track": track,
        "guide_urls": track.guide_url_list,
        "logs": logs_page["items"],
        "logs_page": logs_page,
        "notice": "",
        "error": "",
    }
    context.update(_split_items(track, page_today, page_upcoming, page_done))
    return context


def _content_response(
    request: Request,
    db: Session,
    category: str,
    page_today: int = 1,
    page_upcoming: int = 1,
    page_done: int = 1,
    page_logs: int = 1,
    notice: str = "",
    error: str = "",
) -> HTMLResponse:
    context = learning_context(
        db,
        category,
        page_today=page_today,
        page_upcoming=page_upcoming,
        page_done=page_done,
        page_logs=page_logs,
    )
    context["notice"] = notice
    context["error"] = error
    return render_partial(request, "partials/learning_content.html", context)


def _urls_json(values: list[str], fallback: str = "") -> str:
    urls = [value.strip()[:600] for value in values if value.strip()]
    if not urls and fallback.strip():
        urls = [fallback.strip()[:600]]
    return json.dumps(urls, ensure_ascii=False)


def _require_category(category: str) -> str:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    return category


def _get_item(db: Session, track, item_id: int) -> LearningItem:
    item = db.get(LearningItem, item_id)
    if item is None or item.track_id != track.id:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    return item


def _get_log(db: Session, track, log_id: int) -> LearningLog:
    log = db.get(LearningLog, log_id)
    if log is None or log.track_id != track.id:
        raise HTTPException(status_code=404, detail="学习记忆不存在")
    return log


def _item_form_context(category: str, item: LearningItem | None = None, error: str = "") -> dict:
    return {
        "category": category,
        "category_label": LEARNING_LABELS[category],
        "item": item,
        "error": error,
    }


@router.get("/learning/{category}", response_class=HTMLResponse)
def learning_page(
    category: str,
    request: Request,
    page_today: int = 1,
    page_upcoming: int = 1,
    page_done: int = 1,
    page_logs: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    context = learning_context(
        db,
        category,
        page_today=page_today,
        page_upcoming=page_upcoming,
        page_done=page_done,
        page_logs=page_logs,
    )
    return render(request, "learning.html", context, active=category)


@router.get("/learning/{category}/content", response_class=HTMLResponse)
def learning_content(
    category: str,
    request: Request,
    page_today: int = 1,
    page_upcoming: int = 1,
    page_done: int = 1,
    page_logs: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    return _content_response(
        request,
        db,
        category,
        page_today=page_today,
        page_upcoming=page_upcoming,
        page_done=page_done,
        page_logs=page_logs,
    )


@router.post("/learning/{category}/plan", response_class=HTMLResponse)
def learning_plan(category: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _require_category(category)
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
        url = str(entry.get("resource_url", "")).strip()
        db.add(
            LearningItem(
                track_id=track.id,
                title=title,
                description=entry.get("description", ""),
                resource_url=url[:600],
                resource_urls=_urls_json([url]),
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
    return _content_response(
        request,
        db,
        category,
        notice=f"已生成 {added} 项今日学习任务" if added else "今日任务已存在，未重复添加",
    )


@router.get("/learning/{category}/items/new", response_class=HTMLResponse)
def learning_item_new_form(
    category: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    return render_partial(
        request, "partials/modals/learning_item_form.html", _item_form_context(category)
    )


@router.post("/learning/{category}/items/new", response_class=HTMLResponse)
def learning_item_create(
    category: str,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    resource_urls: list[str] = Form([]),
    scheduled_date: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    if not title.strip():
        return _modal_error(
            request,
            category,
            "partials/modals/learning_item_form.html",
            None,
            "任务标题不能为空",
        )
    urls = [value.strip()[:600] for value in resource_urls if value.strip()]
    db.add(
        LearningItem(
            track_id=track.id,
            title=title.strip()[:300],
            description=description.strip(),
            resource_url=urls[0] if urls else "",
            resource_urls=json.dumps(urls, ensure_ascii=False),
            scheduled_date=parse_date(scheduled_date) or today(),
        )
    )
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/learning/{category}/items/{item_id}/detail", response_class=HTMLResponse)
def learning_item_detail(
    category: str, item_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    item = _get_item(db, track, item_id)
    return render_partial(
        request,
        "partials/modals/learning_item_detail.html",
        {"category": category, "item": item},
    )


@router.get("/learning/{category}/items/{item_id}/edit", response_class=HTMLResponse)
def learning_item_edit_form(
    category: str, item_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    item = _get_item(db, track, item_id)
    return render_partial(
        request,
        "partials/modals/learning_item_form.html",
        _item_form_context(category, item),
    )


@router.post("/learning/{category}/items/{item_id}/edit", response_class=HTMLResponse)
def learning_item_update(
    category: str,
    item_id: int,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    resource_urls: list[str] = Form([]),
    scheduled_date: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    item = _get_item(db, track, item_id)
    if not title.strip():
        return _modal_error(
            request,
            category,
            "partials/modals/learning_item_form.html",
            item,
            "任务标题不能为空",
        )
    urls = [value.strip()[:600] for value in resource_urls if value.strip()]
    item.title = title.strip()[:300]
    item.description = description.strip()
    item.resource_urls = json.dumps(urls, ensure_ascii=False)
    item.resource_url = urls[0] if urls else ""
    item.scheduled_date = parse_date(scheduled_date) or today()
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/learning/{category}/items/{item_id}/delete", response_class=HTMLResponse)
def learning_item_delete(
    category: str, item_id: int, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    item = _get_item(db, track, item_id)
    db.delete(item)
    db.commit()
    recalculate_progress(track)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


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
    _require_category(category)
    track = ensure_track(db, category)
    if not title.strip():
        return _content_response(request, db, category, error="任务标题不能为空")
    db.add(
        LearningItem(
            track_id=track.id,
            title=title.strip()[:300],
            description=description.strip(),
            resource_url=resource_url.strip()[:600],
            resource_urls=_urls_json([resource_url]),
            scheduled_date=parse_date(scheduled_date) or today(),
        )
    )
    db.commit()
    return _content_response(request, db, category, notice="学习任务已添加")


@router.post("/learning/{category}/items/{item_id}/complete", response_class=HTMLResponse)
def learning_complete_item(
    category: str, item_id: int, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    item = _get_item(db, track, item_id)
    item.status = "done"
    item.completed_at = datetime.now()
    item.mastery = max(item.mastery, 80)
    recalculate_progress(track)
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/learning/{category}/items/{item_id}/mastery", response_class=HTMLResponse)
def learning_update_mastery(
    category: str,
    item_id: int,
    mastery: int = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    item = _get_item(db, track, item_id)
    item.mastery = max(0, min(100, mastery))
    if item.mastery >= 80 and item.status != "done":
        item.status = "done"
        item.completed_at = datetime.now()
    recalculate_progress(track)
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.get("/learning/{category}/guide", response_class=HTMLResponse)
def learning_guide_form(
    category: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    return render_partial(
        request,
        "partials/modals/learning_guide_form.html",
        {
            "category": category,
            "category_label": LEARNING_LABELS[category],
            "track": track,
            "guide_urls": track.guide_url_list,
            "error": "",
        },
    )


@router.post("/learning/{category}/guide", response_class=HTMLResponse)
def learning_guide_update(
    category: str,
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    guide_urls: list[str] = Form([]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    track.title = title.strip()[:200] or LEARNING_LABELS[category]
    track.description = description.strip()
    track.guide_urls = _urls_json(guide_urls)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/learning/{category}/logs/new", response_class=HTMLResponse)
def learning_log_new_form(
    category: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    return render_partial(
        request,
        "partials/modals/learning_log_form.html",
        {"category": category, "log": None, "default_mastery": track.progress, "error": ""},
    )


@router.post("/learning/{category}/logs/new", response_class=HTMLResponse)
def learning_log_create(
    category: str,
    request: Request,
    content: str = Form(""),
    mastery: int = Form(0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    if not content.strip():
        return _log_modal_error(request, category, None, track.progress, "学习记忆不能为空")
    db.add(
        LearningLog(
            track_id=track.id,
            content=content.strip(),
            mastery=max(0, min(100, mastery)),
        )
    )
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/learning/{category}/logs/{log_id}/edit", response_class=HTMLResponse)
def learning_log_edit_form(
    category: str, log_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    log = _get_log(db, track, log_id)
    return render_partial(
        request,
        "partials/modals/learning_log_form.html",
        {"category": category, "log": log, "default_mastery": log.mastery, "error": ""},
    )


@router.post("/learning/{category}/logs/{log_id}/edit", response_class=HTMLResponse)
def learning_log_update(
    category: str,
    log_id: int,
    request: Request,
    content: str = Form(""),
    mastery: int = Form(0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    log = _get_log(db, track, log_id)
    if not content.strip():
        return _log_modal_error(request, category, log, log.mastery, "学习记忆不能为空")
    log.content = content.strip()
    log.mastery = max(0, min(100, mastery))
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/learning/{category}/logs/{log_id}/delete", response_class=HTMLResponse)
def learning_log_delete(category: str, log_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    _require_category(category)
    track = ensure_track(db, category)
    log = _get_log(db, track, log_id)
    db.delete(log)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


def _modal_error(
    request: Request,
    category: str,
    template: str,
    item: LearningItem | None,
    message: str,
) -> HTMLResponse:
    response = render_partial(request, template, _item_form_context(category, item, message))
    response.headers["HX-Retarget"] = "#modal-body"
    return response


def _log_modal_error(
    request: Request,
    category: str,
    log: LearningLog | None,
    default_mastery: int,
    message: str,
) -> HTMLResponse:
    response = render_partial(
        request,
        "partials/modals/learning_log_form.html",
        {
            "category": category,
            "log": log,
            "default_mastery": default_mastery,
            "error": message,
        },
    )
    response.headers["HX-Retarget"] = "#modal-body"
    return response


@router.get("/learning/{category}/items", response_class=HTMLResponse)
def learning_items(
    category: str,
    request: Request,
    page_today: int = 1,
    page_upcoming: int = 1,
    page_done: int = 1,
    page_logs: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_category(category)
    return _content_response(
        request,
        db,
        category,
        page_today=page_today,
        page_upcoming=page_upcoming,
        page_done=page_done,
        page_logs=page_logs,
    )
