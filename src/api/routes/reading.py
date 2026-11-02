"""书单阅读板块：小红书 JSON 上传解析、书单管理与 TXT 导出。"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_int
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.taxonomy import all_tags, category_names
from src.core.xhs import XhsParseError, import_notes
from src.models import Book, ReadingNote

router = APIRouter()
STATUS_ORDER = {"reading": 0, "want": 1, "finished": 2}
STATUS_LABELS = {"reading": "在读", "want": "想读", "finished": "已读"}
REFRESH = {"HX-Trigger": '{"list:refresh": true}'}
MODAL_DONE = {"HX-Trigger": '{"modal:close": true, "list:refresh": true}'}


def _stats(db: Session) -> dict:
    rows = db.execute(select(Book.status, func.count()).group_by(Book.status)).all()
    counts = {status: count for status, count in rows}
    total = sum(counts.values())
    return {
        "total": total,
        "want": counts.get("want", 0),
        "reading": counts.get("reading", 0),
        "finished": counts.get("finished", 0),
    }


def _order():
    rank = case(
        (Book.status == "reading", 0),
        (Book.status == "want", 1),
        (Book.status == "finished", 2),
        else_=3,
    )
    return rank, Book.created_at.desc(), Book.id.desc()


def reading_context(
    db: Session,
    category: str = "",
    status: str = "",
    q: str = "",
    page: int = 1,
) -> dict:
    stmt = select(Book)
    if category:
        stmt = stmt.where(Book.category == category)
    if status in STATUS_ORDER:
        stmt = stmt.where(Book.status == status)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Book.title.ilike(pattern),
                Book.author.ilike(pattern),
                Book.category.ilike(pattern),
                Book.tags.ilike(pattern),
                Book.recommended_by.ilike(pattern),
                Book.notes.ilike(pattern),
            )
        )
    page_data = paginate(db, stmt.order_by(*_order()), page)
    notes = db.scalars(select(ReadingNote).order_by(ReadingNote.created_at.desc()).limit(6)).all()
    return {
        "books": page_data["items"],
        "page_data": page_data,
        "stats": _stats(db),
        "categories": category_names(db, "book"),
        "tag_options": all_tags(db, "book"),
        "notes": notes,
        "filters": {"category": category, "status": status, "q": q},
        "result": None,
        "error": "",
    }


def _content_response(
    request: Request,
    db: Session,
    category: str = "",
    status: str = "",
    q: str = "",
    page: int = 1,
    result: dict | None = None,
    error: str = "",
) -> HTMLResponse:
    context = reading_context(db, category=category, status=status, q=q, page=page)
    context["result"] = result
    context["error"] = error
    return render_partial(request, "partials/reading_content.html", context)


def _get_book(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return book


def _book_form_context(db: Session, book: Book | None = None) -> dict:
    return {
        "book": book,
        "categories": category_names(db, "book"),
        "tag_options": all_tags(db, "book"),
        "error": "",
    }


def _book_values(
    title: str,
    author: str,
    status: str,
    category: str,
    tags: str,
    rating: str,
    notes: str,
    resource_url: str,
    recommended_by: str,
) -> dict:
    stars = parse_int(rating)
    return {
        "title": title.strip()[:300],
        "author": author.strip()[:200],
        "status": status if status in STATUS_ORDER else "want",
        "category": category.strip()[:60],
        "tags": tags.strip()[:200],
        "rating": stars if stars and 1 <= stars <= 5 else None,
        "notes": notes.strip(),
        "resource_url": resource_url.strip()[:600],
        "recommended_by": recommended_by.strip()[:200],
    }


def _apply_status(book: Book, status: str) -> None:
    book.status = status
    if status == "finished":
        book.finished_at = book.finished_at or datetime.now()
    else:
        book.finished_at = None


@router.get("/reading", response_class=HTMLResponse)
def reading_page(
    request: Request,
    category: str = "",
    status: str = "",
    q: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = reading_context(db, category=category, status=status, q=q, page=page)
    return render(request, "reading.html", context, active="reading")


@router.get("/reading/content", response_class=HTMLResponse)
def reading_content(
    request: Request,
    category: str = "",
    status: str = "",
    q: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(request, db, category=category, status=status, q=q, page=page)


@router.get("/reading/import", response_class=HTMLResponse)
def reading_import_form(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(
        request,
        "partials/modals/reading_import.html",
        {"categories": category_names(db, "book"), "error": ""},
    )


@router.post("/reading/upload", response_class=HTMLResponse)
async def reading_upload(
    request: Request,
    file: UploadFile = File(...),
    default_category: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    raw = await file.read()
    if not raw:
        response = render_partial(
            request,
            "partials/modals/reading_import.html",
            {"categories": category_names(db, "book"), "error": "上传文件为空"},
        )
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    if len(raw) > 5 * 1024 * 1024:
        response = render_partial(
            request,
            "partials/modals/reading_import.html",
            {"categories": category_names(db, "book"), "error": "文件超过 5MB，请拆分后再导入"},
        )
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    try:
        result = import_notes(db, raw, default_category=default_category)
    except XhsParseError as exc:
        response = render_partial(
            request,
            "partials/modals/reading_import.html",
            {"categories": category_names(db, "book"), "error": str(exc)},
        )
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    except Exception as exc:  # noqa: BLE001 - 面向用户的兜底提示
        response = render_partial(
            request,
            "partials/modals/reading_import.html",
            {"categories": category_names(db, "book"), "error": f"解析失败：{exc}"},
        )
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    response = _content_response(request, db, result=result)
    response.headers["HX-Trigger"] = '{"modal:close": true}'
    return response


@router.get("/reading/books/new", response_class=HTMLResponse)
def book_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/book_form.html", _book_form_context(db))


@router.post("/reading/books/new", response_class=HTMLResponse)
def book_create(
    request: Request,
    title: str = Form(""),
    author: str = Form(""),
    status: str = Form("want"),
    category: str = Form(""),
    tags: str = Form(""),
    rating: str = Form(""),
    notes: str = Form(""),
    resource_url: str = Form(""),
    recommended_by: str = Form("手动添加"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    values = _book_values(
        title, author, status, category, tags, rating, notes, resource_url, recommended_by
    )
    if not values["title"]:
        context = _book_form_context(db)
        context["error"] = "书名不能为空"
        response = render_partial(request, "partials/modals/book_form.html", context)
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    book = Book(**values)
    if book.status == "finished":
        book.finished_at = datetime.now()
    db.add(book)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/reading/books/{book_id}/detail", response_class=HTMLResponse)
def book_detail(book_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(
        request, "partials/modals/book_detail.html", {"book": _get_book(db, book_id)}
    )


@router.get("/reading/books/{book_id}/edit", response_class=HTMLResponse)
def book_edit_form(book_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    book = _get_book(db, book_id)
    return render_partial(request, "partials/modals/book_form.html", _book_form_context(db, book))


@router.post("/reading/books/{book_id}/edit", response_class=HTMLResponse)
def book_update(
    book_id: int,
    request: Request,
    title: str = Form(""),
    author: str = Form(""),
    status: str = Form("want"),
    category: str = Form(""),
    tags: str = Form(""),
    rating: str = Form(""),
    notes: str = Form(""),
    resource_url: str = Form(""),
    recommended_by: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    book = _get_book(db, book_id)
    values = _book_values(
        title, author, status, category, tags, rating, notes, resource_url, recommended_by
    )
    if not values["title"]:
        context = _book_form_context(db, book)
        context["error"] = "书名不能为空"
        response = render_partial(request, "partials/modals/book_form.html", context)
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    previous_status = book.status
    for field, value in values.items():
        setattr(book, field, value)
    if book.status != previous_status or book.status == "finished":
        _apply_status(book, book.status)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/reading/books/{book_id}/status", response_class=HTMLResponse)
def reading_update_status(
    book_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    book = _get_book(db, book_id)
    if status not in STATUS_ORDER:
        raise HTTPException(status_code=400, detail="非法的阅读状态")
    _apply_status(book, status)
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/reading/books/batch-category", response_class=HTMLResponse)
def reading_batch_category(
    book_ids: list[int] = Form([]),
    category: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if book_ids:
        books = db.scalars(select(Book).where(Book.id.in_(book_ids))).all()
        for book in books:
            book.category = category.strip()[:60]
        db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/reading/books/{book_id}/delete", response_class=HTMLResponse)
def reading_delete_book(book_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    book = _get_book(db, book_id)
    db.delete(book)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/reading/export", response_class=PlainTextResponse)
def reading_export(db: Session = Depends(get_db)) -> PlainTextResponse:
    books = db.scalars(select(Book).order_by(Book.status, Book.title)).all()
    groups = {"reading": "在读", "want": "想读", "finished": "已读"}
    lines = ["我的书单（导出自 My Private Assistant）", ""]
    for key, label in groups.items():
        subset = [book for book in books if book.status == key]
        if not subset:
            continue
        lines.append(f"【{label}】")
        for book in subset:
            author = f" / {book.author}" if book.author else ""
            category = f"（{book.category}）" if book.category else ""
            lines.append(f"- 《{book.title}》{author}{category}")
        lines.append("")
    return PlainTextResponse(
        "﻿" + "\n".join(lines),
        headers={"Content-Disposition": 'attachment; filename="booklist.txt"'},
    )
