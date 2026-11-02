"""小红书收藏 JSON 解析（第一版半自动方案，不实现 Cookie 爬虫）。"""

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.llm.assistant import extract_books
from src.models import Book, ReadingNote

logger = get_logger(__name__)

NOTE_KEYS = ("notes", "items", "data", "list", "favorites", "collect", "collections")
TITLE_KEYS = ("title", "display_title", "name", "desc")
URL_KEYS = ("url", "link", "note_url", "share_url", "web_url")
AUTHOR_KEYS = ("author", "nickname", "user_name", "username", "user")
COVER_KEYS = ("cover", "cover_url", "image", "image_url", "thumbnail")


class XhsParseError(ValueError):
    pass


def _first(data: dict[str, Any], keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("nickname") or value.get("url")
        if value:
            return str(value).strip()
    return default


def _normalize_notes(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in NOTE_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _normalize_notes(value)
                if nested:
                    return nested
        return [data]
    raise XhsParseError("JSON 结构无法识别：顶层必须是笔记数组或包含 notes/items 的对象")


def parse_export(raw: bytes | str) -> list[dict[str, str]]:
    """把油猴脚本导出的 JSON 统一成笔记字典列表。"""
    if not isinstance(raw, (bytes, str)):
        raise XhsParseError("上传内容必须是文本或 JSON 字节流")
    if isinstance(raw, bytes):
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise XhsParseError("文件编码无法识别，请导出为 UTF-8 的 JSON")
    else:
        text = raw

    text = text.strip()
    if not text:
        raise XhsParseError("上传内容为空")
    if len(text) > 5 * 1024 * 1024:
        raise XhsParseError("文件过大，单次导入请控制在 5MB 以内")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"[\[{][\s\S]*[\]}]", text)
        if not match:
            if text:
                return [{"title": "文本笔记", "desc": text, "url": "", "author": ""}]
            raise XhsParseError("不是有效的 JSON 文件") from None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise XhsParseError("JSON 格式错误，请检查导出文件") from exc

    notes = []
    for item in _normalize_notes(data):
        raw_text = item.get("desc") or item.get("content") or item.get("text") or ""
        title = _first(item, ("title", "display_title", "name"))
        if not title:
            first_line = re.sub(r"\s+", " ", str(raw_text)).strip().split("\n")[0]
            title = first_line[:60] or "未命名笔记"
        notes.append(
            {
                "title": title[:300],
                "desc": str(raw_text)[:5000],
                "url": _first(item, URL_KEYS)[:600],
                "author": _first(item, AUTHOR_KEYS)[:120],
                "cover_url": _first(item, COVER_KEYS)[:600],
                "raw": json.dumps(item, ensure_ascii=False)[:8000],
            }
        )
    return notes


def import_notes(db: Session, raw: bytes | str) -> dict:
    """解析收藏并入库，同时抽取推荐书单（去重）。"""
    notes = parse_export(raw)
    created_notes = 0
    created_books = 0
    book_preview: list[dict[str, str]] = []

    existing_titles = {
        title.strip().lower() for title in db.scalars(select(Book.title)).all() if title
    }

    for note in notes:
        reading_note = ReadingNote(
            title=note["title"],
            author=note["author"],
            url=note["url"],
            summary=note["desc"][:500],
            cover_url=note["cover_url"],
            raw_json=note["raw"],
        )
        db.add(reading_note)
        db.flush()
        created_notes += 1

        notes_text = f"{note['title']}\n{note['desc']}"
        for parsed_book in extract_books(notes_text):
            key = parsed_book["title"].strip().lower()
            if not key or key in existing_titles:
                continue
            existing_titles.add(key)
            db.add(
                Book(
                    title=parsed_book["title"],
                    author=parsed_book["author"],
                    notes=parsed_book.get("reason", ""),
                    recommended_by=note["author"] or "小红书收藏",
                    source_note_id=reading_note.id,
                )
            )
            created_books += 1
            book_preview.append(parsed_book)

    db.commit()
    logger.info("小红书导入完成：笔记 %s 条，新增书 %s 本", created_notes, created_books)
    return {
        "notes_created": created_notes,
        "books_created": created_books,
        "books": book_preview,
        "message": f"已导入 {created_notes} 条笔记，新增 {created_books} 本书",
    }
