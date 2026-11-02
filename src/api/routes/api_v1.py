"""结构化 JSON API，统一前缀 /api/v1。"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.common import LEARNING_LABELS, ensure_track, recalculate_progress
from src.api.deps import get_db
from src.api.schemas import (
    BookCreate,
    BookUpdate,
    GoalCreate,
    LearningItemCreate,
    LearningItemUpdate,
    LearningLogCreate,
    PaperNoteCreate,
    PlaceCreate,
    PlaceUpdate,
    TaskCreate,
    TaskUpdate,
    TripCreate,
)
from src.api.serializers import (
    book_to_dict,
    dashboard_to_dict,
    digest_to_dict,
    goal_to_dict,
    learning_item_to_dict,
    learning_log_to_dict,
    news_to_dict,
    paper_note_to_dict,
    paper_to_dict,
    place_to_dict,
    reading_note_to_dict,
    review_to_dict,
    task_to_dict,
    track_to_dict,
    trip_to_dict,
)
from src.core.config import settings
from src.core.stats import dashboard_context, ring_data, week_completion
from src.core.time_utils import today
from src.core.xhs import XhsParseError, import_notes
from src.core.zotero import ZoteroError, import_paper
from src.llm.assistant import generate_learning_plan, summarize_paper
from src.mcp_host.manager import MCPHostError, mcp_host
from src.models import (
    Book,
    Goal,
    LearningItem,
    LearningLog,
    NewsDigest,
    NewsItem,
    Paper,
    PaperNote,
    Place,
    ReadingNote,
    Task,
    TripPlan,
)
from src.scheduler.fetchers import build_daily_digest, fetch_arxiv, fetch_rss, refresh_news_summary
from src.scheduler.review import generate_and_store_review
from src.scheduler.runner import scheduler_status

router = APIRouter()


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"ok": True, "message": message, "data": data}


def _validate_status(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise HTTPException(status_code=422, detail=f"{label} 取值不合法")
    return value


@router.get("/health")
def health() -> dict:
    return ok(
        {
            "app": settings.app_name,
            "env": settings.app_env,
            "llm_configured": settings.llm_configured,
            "model": settings.deepseek_model,
            "scheduler": scheduler_status(),
            "mcp_mode": settings.mcp_mode,
            "time": datetime.now().isoformat(),
        }
    )


@router.get("/system/status")
def system_status() -> dict:
    return ok(
        {
            "app_env": settings.app_env,
            "llm_configured": settings.llm_configured,
            "llm_model": settings.deepseek_model,
            "zotero_configured": settings.zotero_configured,
            "database": settings.database_url.split("///")[-1],
            "scheduler": scheduler_status(),
            "mcp": mcp_host.status(),
        }
    )


@router.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)) -> dict:
    return ok(dashboard_to_dict(dashboard_context(db)))


@router.post("/dashboard/review")
def dashboard_review(db: Session = Depends(get_db)) -> dict:
    review = generate_and_store_review(db)
    return ok(review_to_dict(review), "本周复盘已生成")


@router.get("/tasks")
def list_tasks(
    status: str = Query(""),
    archived: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Task).where(Task.archived.is_(archived))
    if status:
        stmt = stmt.where(Task.status == status)
    tasks = db.scalars(stmt.order_by(Task.id.desc())).all()
    return ok([task_to_dict(task) for task in tasks])


@router.post("/tasks")
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> dict:
    task = Task(
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        tags=payload.tags,
        due_date=payload.due_date,
        goal_id=payload.goal_id,
    )
    if task.status == "done":
        task.completed_at = datetime.now()
    db.add(task)
    db.commit()
    db.refresh(task)
    return ok(task_to_dict(task), "任务已创建")


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    data = payload.model_dump(exclude_unset=True)
    if "priority" in data:
        _validate_status(data["priority"], {"high", "medium", "low"}, "priority")
    if "status" in data:
        _validate_status(data["status"], {"todo", "doing", "done"}, "status")
        task.completed_at = datetime.now() if data["status"] == "done" else None
    for field, value in data.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return ok(task_to_dict(task), "任务已更新")


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return ok(message="任务已删除")


@router.get("/goals")
def list_goals(db: Session = Depends(get_db)) -> dict:
    goals = db.scalars(select(Goal).order_by(Goal.id)).all()
    return ok([goal_to_dict(goal) for goal in goals])


@router.post("/goals")
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)) -> dict:
    goal = Goal(**payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return ok(goal_to_dict(goal), "目标已创建")


@router.get("/papers")
def list_papers(
    limit: int = Query(30, ge=1, le=200),
    read_status: str = Query(""),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Paper)
    if read_status:
        stmt = stmt.where(Paper.read_status == read_status)
    papers = db.scalars(stmt.order_by(Paper.fetched_at.desc()).limit(limit)).all()
    return ok([paper_to_dict(paper, include_notes=True) for paper in papers])


@router.post("/papers/fetch")
def papers_fetch(db: Session = Depends(get_db)) -> dict:
    result = fetch_arxiv(db)
    return ok(result, result.get("message", ""))


@router.post("/papers/{paper_id}/summarize")
def paper_summarize(paper_id: int, db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    paper.summary = summarize_paper(paper.title, paper.abstract, paper.authors)
    db.commit()
    return ok(paper_to_dict(paper), "摘要已更新")


@router.post("/papers/{paper_id}/zotero")
def paper_zotero(paper_id: int, db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    try:
        result = import_paper(db, paper)
    except ZoteroError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({**result, "paper": paper_to_dict(paper)}, result["message"])


@router.patch("/papers/{paper_id}")
def update_paper(
    paper_id: int,
    read_status: str = Query(""),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if read_status:
        paper.read_status = _validate_status(read_status, {"read", "unread"}, "read_status")
    db.commit()
    return ok(paper_to_dict(paper), "论文状态已更新")


@router.post("/papers/{paper_id}/notes")
def add_paper_note(paper_id: int, payload: PaperNoteCreate, db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    note = PaperNote(paper_id=paper_id, content=payload.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return ok(paper_note_to_dict(note), "笔记已保存")


@router.get("/books")
def list_books(status: str = Query(""), db: Session = Depends(get_db)) -> dict:
    stmt = select(Book)
    if status:
        stmt = stmt.where(Book.status == status)
    books = db.scalars(stmt.order_by(Book.created_at.desc())).all()
    return ok([book_to_dict(book) for book in books])


@router.post("/books")
def create_book(payload: BookCreate, db: Session = Depends(get_db)) -> dict:
    book = Book(**payload.model_dump())
    db.add(book)
    db.commit()
    db.refresh(book)
    return ok(book_to_dict(book), "书籍已添加")


@router.patch("/books/{book_id}")
def update_book(book_id: int, payload: BookUpdate, db: Session = Depends(get_db)) -> dict:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    data = payload.model_dump(exclude_unset=True)
    if data.get("status"):
        _validate_status(data["status"], {"want", "reading", "finished"}, "status")
    for field, value in data.items():
        setattr(book, field, value)
    db.commit()
    db.refresh(book)
    return ok(book_to_dict(book), "书籍已更新")


@router.delete("/books/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db)) -> dict:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    db.delete(book)
    db.commit()
    return ok(message="书籍已删除")


@router.post("/reading/upload")
async def upload_reading_export(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 5MB")
    try:
        result = import_notes(db, raw)
    except XhsParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(result, result["message"])


@router.get("/reading-notes")
def list_reading_notes(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)):
    notes = db.scalars(
        select(ReadingNote).order_by(ReadingNote.created_at.desc()).limit(limit)
    ).all()
    return ok([reading_note_to_dict(note) for note in notes])


@router.get("/news")
def list_news(
    q: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(NewsItem)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(NewsItem.title.ilike(pattern) | NewsItem.summary.ilike(pattern))
    items = db.scalars(stmt.order_by(NewsItem.fetched_at.desc()).limit(limit)).all()
    return ok([news_to_dict(item) for item in items])


@router.post("/news/fetch")
def news_fetch(db: Session = Depends(get_db)) -> dict:
    result = fetch_rss(db)
    return ok(result, result.get("message", ""))


@router.post("/news/digest")
def news_digest(db: Session = Depends(get_db)) -> dict:
    message = build_daily_digest(db)
    digest = db.scalar(select(NewsDigest).where(NewsDigest.digest_date == today()))
    return ok(digest_to_dict(digest) if digest else None, message or "暂无简报")


@router.post("/news/{item_id}/summarize")
def news_summarize(item_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(NewsItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资讯不存在")
    refresh_news_summary(db, item)
    db.refresh(item)
    return ok(news_to_dict(item), "摘要已更新")


@router.get("/learning/{category}")
def get_learning(category: str, db: Session = Depends(get_db)) -> dict:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    track = ensure_track(db, category)
    return ok(track_to_dict(track))


@router.post("/learning/{category}/plan")
def learning_plan(category: str, db: Session = Depends(get_db)) -> dict:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    track = ensure_track(db, category)
    plan = generate_learning_plan(
        category,
        LEARNING_LABELS[category],
        track.progress,
        [item.title for item in track.items if item.status == "done"],
        [item.title for item in track.items if item.status != "done"],
        [log.content for log in track.logs],
    )
    existing_today = {
        item.title
        for item in track.items
        if item.scheduled_date == today() and item.status != "done"
    }
    created = []
    for entry in plan:
        if entry["title"] in existing_today:
            continue
        item = LearningItem(
            track_id=track.id,
            title=entry["title"],
            description=entry.get("description", ""),
            resource_url=entry.get("resource_url", ""),
            scheduled_date=today(),
        )
        db.add(item)
        created.append(item)
    db.commit()
    return ok(
        {"plan": plan, "created": [learning_item_to_dict(item) for item in created]},
        f"已生成今日学习任务 {len(created)} 项",
    )


@router.post("/learning/{category}/items")
def add_learning_item(
    category: str, payload: LearningItemCreate, db: Session = Depends(get_db)
) -> dict:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    track = ensure_track(db, category)
    item = LearningItem(
        track_id=track.id,
        title=payload.title,
        description=payload.description,
        resource_url=payload.resource_url,
        scheduled_date=payload.scheduled_date or today(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ok(learning_item_to_dict(item), "学习任务已创建")


@router.patch("/learning/items/{item_id}")
def update_learning_item(
    item_id: int, payload: LearningItemUpdate, db: Session = Depends(get_db)
) -> dict:
    item = db.get(LearningItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    data = payload.model_dump(exclude_unset=True)
    if "mastery" in data:
        item.mastery = data["mastery"]
        if item.mastery >= 80:
            item.status = "done"
            item.completed_at = datetime.now()
    if "status" in data:
        item.status = _validate_status(data["status"], {"todo", "doing", "done"}, "status")
        item.completed_at = datetime.now() if item.status == "done" else None
        if item.status == "done":
            item.mastery = max(item.mastery, 80)
    recalculate_progress(item.track)
    db.commit()
    db.refresh(item)
    return ok(learning_item_to_dict(item), "学习任务已更新")


@router.delete("/learning/items/{item_id}")
def delete_learning_item(item_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(LearningItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    track = item.track
    db.delete(item)
    db.commit()
    recalculate_progress(track)
    db.commit()
    return ok(message="学习任务已删除")


@router.post("/learning/{category}/logs")
def add_learning_log(
    category: str, payload: LearningLogCreate, db: Session = Depends(get_db)
) -> dict:
    if category not in LEARNING_LABELS:
        raise HTTPException(status_code=404, detail="学习模块不存在")
    track = ensure_track(db, category)
    log = LearningLog(
        track_id=track.id,
        content=payload.content,
        mastery=payload.mastery,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return ok(learning_log_to_dict(log), "学习记忆已保存")


@router.get("/places")
def list_places(db: Session = Depends(get_db)) -> dict:
    places = db.scalars(select(Place).order_by(Place.id.desc())).all()
    return ok([place_to_dict(place) for place in places])


@router.post("/places")
def create_place(payload: PlaceCreate, db: Session = Depends(get_db)) -> dict:
    place = Place(**payload.model_dump())
    db.add(place)
    db.commit()
    db.refresh(place)
    return ok(place_to_dict(place), "地点已添加")


@router.patch("/places/{place_id}")
def update_place(place_id: int, payload: PlaceUpdate, db: Session = Depends(get_db)) -> dict:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="地点不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(place, field, value)
    db.commit()
    db.refresh(place)
    return ok(place_to_dict(place), "地点已更新")


@router.delete("/places/{place_id}")
def delete_place(place_id: int, db: Session = Depends(get_db)) -> dict:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="地点不存在")
    db.delete(place)
    db.commit()
    return ok(message="地点已删除")


@router.get("/trips")
def list_trips(db: Session = Depends(get_db)) -> dict:
    trips = db.scalars(select(TripPlan).order_by(TripPlan.id.desc())).all()
    return ok([trip_to_dict(trip) for trip in trips])


@router.post("/trips")
def create_trip(payload: TripCreate, db: Session = Depends(get_db)) -> dict:
    trip = TripPlan(**payload.model_dump())
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return ok(trip_to_dict(trip), "行程已保存")


@router.delete("/trips/{trip_id}")
def delete_trip(trip_id: int, db: Session = Depends(get_db)) -> dict:
    trip = db.get(TripPlan, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="行程不存在")
    db.delete(trip)
    db.commit()
    return ok(message="行程已删除")


@router.get("/mcp/status")
def mcp_status() -> dict:
    return ok(mcp_host.status())


@router.post("/mcp/{name}/start")
def mcp_start(name: str) -> dict:
    try:
        return ok(mcp_host.start(name))
    except MCPHostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/mcp/{name}/stop")
def mcp_stop(name: str) -> dict:
    try:
        return ok(mcp_host.stop(name))
    except MCPHostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stats/weekly")
def weekly_stats(db: Session = Depends(get_db)) -> dict:
    return ok({"completion": week_completion(db), "rings": ring_data(db)})
