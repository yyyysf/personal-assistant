"""列表分页：全站默认每页 5 条。"""

import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

PER_PAGE = 5


def parse_page(value: int | str | None) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def paginate(db: Session, stmt: Any, page: int | str | None = 1, per_page: int = PER_PAGE) -> dict:
    page = parse_page(page)
    total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    pages = max(1, math.ceil(total / per_page)) if total else 1
    page = min(page, pages)
    items = list(db.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).all())
    return {
        "items": items,
        "page": page,
        "pages": pages,
        "total": total,
        "per_page": per_page,
        "has_prev": page > 1,
        "has_next": page < pages,
        "start": (page - 1) * per_page + 1 if total else 0,
        "end": min(page * per_page, total),
    }
