"""科研板块页面：arXiv 抓取、中文摘要、Zotero 导入、收藏与阅读笔记。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.taxonomy import all_tags, tag_filter
from src.core.zotero import ZoteroError, import_paper
from src.llm.assistant import summarize_paper_bilingual
from src.models import Paper, PaperNote
from src.scheduler.fetchers import fetch_arxiv

router = APIRouter()
REFRESH = {"HX-Trigger": '{"list:refresh": true}'}
MODAL_DONE = {"HX-Trigger": '{"modal:close": true, "list:refresh": true}'}


def _stats(db: Session) -> dict:
    return {
        "total": db.scalar(select(func.count()).select_from(Paper)) or 0,
        "read": db.scalar(
            select(func.count()).select_from(Paper).where(Paper.read_status == "read")
        )
        or 0,
        "imported": db.scalar(
            select(func.count()).select_from(Paper).where(Paper.imported_to_zotero.is_(True))
        )
        or 0,
        "notes": db.scalar(select(func.count()).select_from(PaperNote)) or 0,
    }


def research_context(
    db: Session,
    read: str = "",
    zotero: str = "",
    tag: str = "",
    favorite: str = "",
    q: str = "",
    page: int = 1,
) -> dict:
    stmt = select(Paper)
    if read in {"read", "unread"}:
        stmt = stmt.where(Paper.read_status == read)
    if zotero == "imported":
        stmt = stmt.where(Paper.imported_to_zotero.is_(True))
    elif zotero == "pending":
        stmt = stmt.where(Paper.imported_to_zotero.is_(False))
    if tag:
        stmt = stmt.where(tag_filter(Paper.tags, tag))
    if favorite:
        stmt = stmt.where(Paper.favorite.is_(True))
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Paper.title.ilike(pattern),
                Paper.title_zh.ilike(pattern),
                Paper.authors.ilike(pattern),
                Paper.summary.ilike(pattern),
                Paper.tags.ilike(pattern),
            )
        )
    page_data = paginate(db, stmt.order_by(Paper.fetched_at.desc(), Paper.id.desc()), page)
    return {
        "papers": page_data["items"],
        "page_data": page_data,
        "stats": _stats(db),
        "tag_options": all_tags(db, "paper"),
        "filters": {
            "read": read,
            "zotero": zotero,
            "tag": tag,
            "favorite": favorite,
            "q": q,
        },
        "notice": "",
        "error": "",
    }


def _list_response(
    request: Request,
    db: Session,
    read: str = "",
    zotero: str = "",
    tag: str = "",
    favorite: str = "",
    q: str = "",
    page: int = 1,
    notice: str = "",
    error: str = "",
) -> HTMLResponse:
    context = research_context(
        db, read=read, zotero=zotero, tag=tag, favorite=favorite, q=q, page=page
    )
    context["notice"] = notice
    context["error"] = error
    return render_partial(request, "partials/research_list.html", context)


@router.get("/research", response_class=HTMLResponse)
def research_page(
    request: Request,
    read: str = "",
    zotero: str = "",
    tag: str = "",
    favorite: str = "",
    q: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = research_context(
        db, read=read, zotero=zotero, tag=tag, favorite=favorite, q=q, page=page
    )
    return render(request, "research.html", context, active="research")


@router.get("/research/list", response_class=HTMLResponse)
def research_list(
    request: Request,
    read: str = "",
    zotero: str = "",
    tag: str = "",
    favorite: str = "",
    q: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _list_response(
        request, db, read=read, zotero=zotero, tag=tag, favorite=favorite, q=q, page=page
    )


@router.post("/research/fetch", response_class=HTMLResponse)
def research_fetch(
    request: Request,
    read: str = Form(""),
    zotero: str = Form(""),
    tag: str = Form(""),
    favorite: str = Form(""),
    q: str = Form(""),
    page: int = Form(1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    result = fetch_arxiv(db)
    return _list_response(
        request,
        db,
        read=read,
        zotero=zotero,
        tag=tag,
        favorite=favorite,
        q=q,
        page=page,
        notice=result.get("message", "") if result.get("ok") else "",
        error="" if result.get("ok") else result.get("message", "抓取失败"),
    )


def _get_paper(db: Session, paper_id: int) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return paper


@router.post("/research/papers/{paper_id}/summarize", response_class=HTMLResponse)
def research_summarize(paper_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    title_zh, summary = summarize_paper_bilingual(paper.title, paper.abstract, paper.authors)
    if title_zh:
        paper.title_zh = title_zh
    paper.summary = summary
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/research/papers/{paper_id}/zotero", response_class=HTMLResponse)
def research_zotero(paper_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    try:
        import_paper(db, paper)
    except ZoteroError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse("", headers=REFRESH)


@router.post("/research/papers/{paper_id}/read", response_class=HTMLResponse)
def research_toggle_read(paper_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    if paper.read_status == "read":
        paper.read_status = "unread"
        paper.read_at = None
    else:
        paper.read_status = "read"
        paper.read_at = paper.read_at or datetime.now()
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/research/papers/{paper_id}/favorite", response_class=HTMLResponse)
def research_toggle_favorite(paper_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    paper.favorite = not paper.favorite
    db.commit()
    return HTMLResponse("", headers=REFRESH)


@router.post("/research/papers/{paper_id}/delete", response_class=HTMLResponse)
def research_delete(paper_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    db.delete(paper)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/research/papers/{paper_id}/detail", response_class=HTMLResponse)
def research_detail(paper_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(
        request, "partials/modals/paper_detail.html", {"paper": _get_paper(db, paper_id)}
    )


@router.get("/research/papers/{paper_id}/edit", response_class=HTMLResponse)
def research_edit_form(
    paper_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    return render_partial(
        request,
        "partials/modals/paper_form.html",
        {"paper": _get_paper(db, paper_id), "tag_options": all_tags(db, "paper"), "error": ""},
    )


@router.post("/research/papers/{paper_id}/edit", response_class=HTMLResponse)
def research_edit(
    paper_id: int,
    request: Request,
    title_zh: str = Form(""),
    summary: str = Form(""),
    tags: str = Form(""),
    read_status: str = Form("unread"),
    favorite: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    if read_status not in {"read", "unread"}:
        read_status = paper.read_status
    paper.title_zh = title_zh.strip()[:500]
    paper.summary = summary.strip()
    paper.tags = tags.strip()[:300]
    paper.favorite = bool(favorite)
    if read_status == "read" and paper.read_status != "read":
        paper.read_at = datetime.now()
    if read_status == "unread":
        paper.read_at = None
    paper.read_status = read_status
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/research/papers/{paper_id}/notes/new", response_class=HTMLResponse)
def paper_note_form(paper_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(
        request,
        "partials/modals/paper_note_form.html",
        {"paper": _get_paper(db, paper_id), "note": None, "error": ""},
    )


@router.post("/research/papers/{paper_id}/notes/new", response_class=HTMLResponse)
def paper_note_create(
    paper_id: int,
    request: Request,
    content: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    paper = _get_paper(db, paper_id)
    if not content.strip():
        response = render_partial(
            request,
            "partials/modals/paper_note_form.html",
            {"paper": paper, "note": None, "error": "笔记内容不能为空"},
        )
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    db.add(PaperNote(paper_id=paper.id, content=content.strip()))
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


def _get_note(db: Session, note_id: int) -> PaperNote:
    note = db.get(PaperNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


@router.get("/research/notes/{note_id}/edit", response_class=HTMLResponse)
def paper_note_edit_form(
    note_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    note = _get_note(db, note_id)
    return render_partial(
        request,
        "partials/modals/paper_note_form.html",
        {"paper": note.paper, "note": note, "error": ""},
    )


@router.post("/research/notes/{note_id}/edit", response_class=HTMLResponse)
def paper_note_edit(
    note_id: int,
    request: Request,
    content: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    note = _get_note(db, note_id)
    if not content.strip():
        response = render_partial(
            request,
            "partials/modals/paper_note_form.html",
            {"paper": note.paper, "note": note, "error": "笔记内容不能为空"},
        )
        response.headers["HX-Retarget"] = "#modal-body"
        return response
    note.content = content.strip()
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/research/notes/{note_id}/delete", response_class=HTMLResponse)
def paper_note_delete(note_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    note = _get_note(db, note_id)
    db.delete(note)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)
