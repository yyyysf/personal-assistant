"""Zotero 入库：配置了 API Key 时写入 Web API，否则返回明确提示。"""

import httpx
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.logging import get_logger
from src.models import Paper

logger = get_logger(__name__)

ZOTERO_WEB_API = "https://api.zotero.org"


class ZoteroError(RuntimeError):
    pass


def _creators(authors: str) -> list[dict]:
    creators = []
    for name in (authors or "").split(","):
        name = name.strip()
        if not name:
            continue
        parts = name.split()
        if len(parts) >= 2:
            creators.append(
                {
                    "creatorType": "author",
                    "firstName": " ".join(parts[:-1]),
                    "lastName": parts[-1],
                }
            )
        else:
            creators.append({"creatorType": "author", "name": name})
    return creators


def import_paper(db: Session, paper: Paper) -> dict:
    if not settings.zotero_configured:
        raise ZoteroError("未配置 ZOTERO_API_KEY / ZOTERO_USER_ID，请先在 .env 中填写")

    library = settings.zotero_library_type or "user"
    if library == "group":
        endpoint = f"{ZOTERO_WEB_API}/groups/{settings.zotero_user_id}/items"
    else:
        endpoint = f"{ZOTERO_WEB_API}/users/{settings.zotero_user_id}/items"

    payload = [
        {
            "itemType": "journalArticle",
            "title": paper.title,
            "creators": _creators(paper.authors),
            "abstractNote": paper.abstract,
            "url": paper.url,
            "date": paper.published_date.isoformat() if paper.published_date else "",
            "tags": [{"tag": tag.strip()} for tag in paper.tags.split(",") if tag.strip()],
            "extra": f"arXiv: {paper.arxiv_id}",
        }
    ]

    try:
        response = httpx.post(
            endpoint,
            headers={
                "Zotero-API-Key": settings.zotero_api_key,
                "Content-Type": "application/json",
                "Zotero-API-Version": "3",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Zotero 入库失败：%s", exc)
        raise ZoteroError(f"Zotero 入库失败：{exc}") from exc

    key = ""
    try:
        data = response.json()
        if isinstance(data, dict) and "successful" in data:
            first = next(iter(data["successful"].values()), {})
            key = first.get("key", "")
    except ValueError:
        pass

    paper.imported_to_zotero = True
    paper.zotero_item_key = key
    db.commit()
    return {"ok": True, "message": "已导入 Zotero" + (f"（{key}）" if key else ""), "key": key}
