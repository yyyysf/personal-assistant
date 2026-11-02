"""书单阅读板块：小红书 JSON 上传解析、书单管理与 TXT 导出。"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db, render, render_partial
from src.core.xhs import XhsParseError, import_notes
from src.models import Book, ReadingNote

router = APIRouter()
STATUS_ORDER = {"reading": 0, "want": 1, "finished": 2}


def reading_context(db: Session) -> dict:
    books = db.scalars(select(Book).order_by(Book.created_at.desc())).all()
    books = sorted(books, key=lambda book: STATUS_ORDER.get(book.status, 9))
    notes = db.scalars(select(ReadingNote).order_by(ReadingNote.created_at.desc()).limit(30)).all()
    stats = {
        "total": len(books),
        "want": sum(1 for book in books if book.status == "want"),
        "reading": sum(1 for book in books if book.status == "reading"),
        "finished": sum(1 for book in books if book.status == "finished"),
    }
    return {"books": books, "notes": notes, "stats": stats, "result": None, "error": ""}


@router.get("/reading", response_class=HTMLResponse)
def reading_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(request, "reading.html", reading_context(db), active="reading")


@router.post("/reading/upload", response_class=HTMLResponse)
async def reading_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = reading_context(db)
    raw = await file.read()
    if not raw:
        context["error"] = "上传文件为空"
        return render_partial(request, "partials/reading_content.html", context)
    if len(raw) > 5 * 1024 * 1024:
        context["error"] = "文件超过 5MB，请拆分后再导入"
        return render_partial(request, "partials/reading_content.html", context)
    try:
        context["result"] = import_notes(db, raw)
    except XhsParseError as exc:
        context["error"] = str(exc)
    except Exception as exc:
        context["error"] = f"解析失败：{exc}"
    refreshed = reading_context(db)
    refreshed["result"] = context["result"]
    refreshed["error"] = context["error"]
    return render_partial(request, "partials/reading_content.html", refreshed)


@router.post("/reading/books", response_class=HTMLResponse)
def reading_add_book(
    request: Request,
    title: str = Form(""),
    author: str = Form(""),
    status: str = Form("want"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = reading_context(db)
    if not title.strip():
        context["error"] = "书名不能为空"
    elif status not in STATUS_ORDER:
        context["error"] = "非法的阅读状态"
    else:
        db.add(
            Book(
                title=title.strip(),
                author=author.strip(),
                status=status,
                recommended_by="手动添加",
            )
        )
        db.commit()
        context = reading_context(db)
        context["result"] = {"message": f"已添加《{title.strip()}》"}
    return render_partial(request, "partials/reading_content.html", context)


@router.post("/reading/books/{book_id}/status", response_class=HTMLResponse)
def reading_update_status(
    book_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if status not in STATUS_ORDER:
        raise HTTPException(status_code=400, detail="非法的阅读状态")
    book.status = status
    db.commit()
    return render_partial(request, "partials/reading_content.html", reading_context(db))


@router.post("/reading/books/{book_id}/delete", response_class=HTMLResponse)
def reading_delete_book(
    book_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    db.delete(book)
    db.commit()
    return render_partial(request, "partials/reading_content.html", reading_context(db))


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
            lines.append(f"- 《{book.title}》{author}")
        lines.append("")
    return PlainTextResponse(
        "﻿" + "\n".join(lines),
        headers={"Content-Disposition": 'attachment; filename="booklist.txt"'},
    )
