"""分类管理：弹窗 partial 与新增、重命名、删除表单接口。"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db, render_partial
from src.core.taxonomy import CATEGORY_MODEL, SCOPE_LABELS, clear_category, rename_category
from src.models import Category

router = APIRouter()


def _manage_response(request: Request, db: Session, scope: str, error: str = "") -> HTMLResponse:
    if scope not in CATEGORY_MODEL:
        raise HTTPException(status_code=404, detail="分类分组不存在")
    categories = db.scalars(
        select(Category).where(Category.scope == scope).order_by(Category.id)
    ).all()
    return render_partial(
        request,
        "partials/category_manage.html",
        {
            "scope": scope,
            "scope_label": SCOPE_LABELS.get(scope, scope),
            "categories": categories,
            "error": error,
        },
    )


def _clean_name(value: str) -> str:
    return " ".join(value.split())[:60]


@router.get("/categories/{scope}/manage", response_class=HTMLResponse)
def category_manage(scope: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _manage_response(request, db, scope)


@router.post("/categories/{scope}", response_class=HTMLResponse)
def category_create(
    scope: str,
    request: Request,
    name: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if scope not in CATEGORY_MODEL:
        raise HTTPException(status_code=404, detail="分类分组不存在")
    clean = _clean_name(name)
    if not clean:
        return _manage_response(request, db, scope, "分类名称不能为空")
    exists = db.scalar(select(Category).where(Category.scope == scope, Category.name == clean))
    if exists:
        return _manage_response(request, db, scope, "该分类已存在")
    db.add(Category(scope=scope, name=clean))
    db.commit()
    return _manage_response(request, db, scope)


@router.post("/categories/{scope}/{category_id}/rename", response_class=HTMLResponse)
def category_rename(
    scope: str,
    category_id: int,
    request: Request,
    name: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    item = db.get(Category, category_id)
    if item is None or item.scope != scope:
        raise HTTPException(status_code=404, detail="分类不存在")
    clean = _clean_name(name)
    if not clean:
        return _manage_response(request, db, scope, "分类名称不能为空")
    if clean == item.name:
        return _manage_response(request, db, scope)
    exists = db.scalar(
        select(Category).where(
            Category.scope == scope, Category.name == clean, Category.id != category_id
        )
    )
    if exists:
        return _manage_response(request, db, scope, "该分类已存在")
    rename_category(db, scope, item.name, clean)
    item.name = clean
    db.commit()
    return _manage_response(request, db, scope)


@router.post("/categories/{scope}/{category_id}/delete", response_class=HTMLResponse)
def category_delete(
    scope: str,
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    item = db.get(Category, category_id)
    if item is None or item.scope != scope:
        raise HTTPException(status_code=404, detail="分类不存在")
    clear_category(db, scope, item.name)
    db.delete(item)
    db.commit()
    return _manage_response(request, db, scope)


__all__ = ["router"]
