"""科研板块页面：arXiv 抓取、LLM 摘要、Zotero 导入、阅读笔记。"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_db, render, render_partial
from src.core.zotero import ZoteroError, import_paper
from src.llm.assistant import summarize_paper
from src.models import Paper, PaperNote
from src.scheduler.fetchers import fetch_arxiv

router = APIRouter()


def research_context(db: Session) -> dict:
    papers = db.scalars(select(Paper).order_by(Paper.fetched_at.desc()).limit(50)).all()
    stats = {
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
    return {"papers": papers, "stats": stats, "notice": "", "error": ""}


@router.get("/research", response_class=HTMLResponse)
def research_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(request, "research.html", research_context(db), active="research")


@router.post("/research/fetch", response_class=HTMLResponse)
def research_fetch(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    result = fetch_arxiv(db)
    context = research_context(db)
    if result.get("ok"):
        context["notice"] = result.get("message", "")
    else:
        context["error"] = result.get("message", "抓取失败")
    return render_partial(request, "partials/research_list.html", context)


def _paper_card(
    request: Request, db: Session, paper: Paper, notice: str = "", error: str = ""
) -> HTMLResponse:
    db.refresh(paper)
    return render_partial(
        request,
        "partials/paper_card.html",
        {"paper": paper, "card_notice": notice, "card_error": error},
    )


@router.post("/research/papers/{paper_id}/summarize", response_class=HTMLResponse)
def research_summarize(
    paper_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    paper.summary = summarize_paper(paper.title, paper.abstract, paper.authors)
    db.commit()
    return _paper_card(request, db, paper, notice="摘要已更新")


@router.post("/research/papers/{paper_id}/zotero", response_class=HTMLResponse)
def research_zotero(paper_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    try:
        result = import_paper(db, paper)
        return _paper_card(request, db, paper, notice=result["message"])
    except ZoteroError as exc:
        return _paper_card(request, db, paper, error=str(exc))


@router.post("/research/papers/{paper_id}/read", response_class=HTMLResponse)
def research_toggle_read(
    paper_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    paper.read_status = "unread" if paper.read_status == "read" else "read"
    db.commit()
    return _paper_card(request, db, paper)


@router.post("/research/papers/{paper_id}/notes", response_class=HTMLResponse)
def research_add_note(
    paper_id: int,
    request: Request,
    content: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if content.strip():
        db.add(PaperNote(paper_id=paper.id, content=content.strip()))
        db.commit()
    db.refresh(paper)
    return render_partial(request, "partials/paper_notes.html", {"paper": paper})
