"""旅游模块：高德 GCJ02 点位库与旅程游记。"""

import json
import random
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date, parse_int
from src.api.deps import get_db, render, render_partial
from src.core.config import BASE_DIR, settings
from src.core.logging import get_logger
from src.models import (
    JOURNEY_STATUS_LABELS,
    MOOD_COLORS,
    MOOD_LABELS,
    POINT_CATEGORIES,
    POINT_CATEGORY_COLORS,
    POINT_CATEGORY_DEFAULT_COLOR,
    POINT_STATUS_COLORS,
    POINT_STATUS_LABELS,
    Journey,
    JourneyPlace,
    Place,
    TravelPlaceCandidate,
)

router = APIRouter()
logger = get_logger(__name__)
UPLOAD_DIR = Path(BASE_DIR) / "uploads" / "travel"
JOURNEY_SUBDIR = "journeys"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PHOTOS = 6
MAX_JOURNEY_PHOTOS = 12
POINT_STATUS = tuple(POINT_STATUS_LABELS)
JOURNAL_YEAR_COLORS = ("#FFC8DD", "#CDF5FD", "#DDE7D8", "#E3E1F5", "#FFE0C2", "#F6E7A1")
YEAR_UNDATED_KEY = "undated"


def _trigger(payload: dict) -> dict[str, str]:
    # HTTP header 只能承载 latin-1，中文需转义为 \uXXXX，htmx 仍按 JSON 解析。
    return {"HX-Trigger": json.dumps(payload, ensure_ascii=True)}


def _place_saved_headers(place: Place) -> dict[str, str]:
    return _trigger({"modal:close": True, "list:refresh": True, "placeSaved": _marker(place)})


def _marker(place: Place) -> dict:
    return {
        "id": place.id,
        "name": place.name,
        "city": place.city,
        "country": place.country,
        "lat": place.lat,
        "lng": place.lng,
        "visited": place.visited,
        "point_status": place.point_status,
        "status_label": place.status_label,
        "color": place.marker_color,
        "point_category": place.point_category,
        "standard_address": place.standard_address,
        "amap_poi_id": place.amap_poi_id,
        "source_note_url": place.source_note_url,
        "rating": place.rating,
        "date_label": place.date_label,
        "notes": place.notes,
        "tags": place.tag_list,
    }


def _stats(db: Session) -> dict:
    total_places = int(db.scalar(select(func.count()).select_from(Place)) or 0)
    visited = int(
        db.scalar(select(func.count()).select_from(Place).where(Place.point_status == "visited"))
        or 0
    )
    want = int(
        db.scalar(select(func.count()).select_from(Place).where(Place.point_status == "want")) or 0
    )
    journeys = int(db.scalar(select(func.count()).select_from(Journey)) or 0)
    journey_want = int(
        db.scalar(select(func.count()).select_from(Journey).where(Journey.status == "want")) or 0
    )
    journey_visited = int(
        db.scalar(select(func.count()).select_from(Journey).where(Journey.status == "visited")) or 0
    )
    cost_total = int(
        db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        Journey.cost_transport
                        + Journey.cost_lodging
                        + Journey.cost_food
                        + Journey.cost_other
                    ),
                    0,
                )
            )
        )
        or 0
    )
    pending_candidates = int(
        db.scalar(
            select(func.count())
            .select_from(TravelPlaceCandidate)
            .where(TravelPlaceCandidate.status == "pending")
        )
        or 0
    )
    return {
        "places": total_places,
        "total_places": total_places,
        "want": want,
        "visited": visited,
        "journeys": journeys,
        "journey_want": journey_want,
        "journey_visited": journey_visited,
        "cost_total": cost_total,
        "pending_candidates": pending_candidates,
    }


def _place_stmt(status: str, point_category: str, q: str):
    stmt = select(Place)
    if status and status in POINT_STATUS:
        stmt = stmt.where(Place.point_status == status)
    if point_category:
        stmt = stmt.where(Place.point_category == point_category)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Place.name.ilike(pattern),
                Place.city.ilike(pattern),
                Place.country.ilike(pattern),
                Place.standard_address.ilike(pattern),
                Place.point_category.ilike(pattern),
                Place.tags.ilike(pattern),
                Place.notes.ilike(pattern),
            )
        )
    return stmt.order_by(Place.sort_order, Place.id)


def _place_groups(places: list[Place]) -> list[dict]:
    buckets: dict[str, list[Place]] = {}
    for place in places:
        buckets.setdefault(place.point_category or "", []).append(place)
    groups = [
        {"key": name, "name": name, "places": buckets[name]}
        for name in POINT_CATEGORIES
        if name in buckets
    ]
    if buckets.get(""):
        groups.append({"key": "", "name": "未分类", "places": buckets[""]})
    for name, items in buckets.items():
        if name and name not in POINT_CATEGORIES:
            groups.append({"key": name, "name": name, "places": items})
    return groups


def _journey_year_key(journey: Journey) -> str:
    value = journey.start_date or journey.end_date
    return str(value.year) if value else YEAR_UNDATED_KEY


def _journey_year_groups(journeys: list[Journey]) -> list[dict]:
    """按出行年份把旅程分成手账分册，没有日期的归入「未编年」。"""
    buckets: dict[str, list[Journey]] = {}
    for journey in journeys:
        buckets.setdefault(_journey_year_key(journey), []).append(journey)
    groups: list[dict] = []
    for key, items in buckets.items():
        year = None if key == YEAR_UNDATED_KEY else int(key)
        cover = next((item.photo_list[0] for item in items if item.photo_list), "")
        # 每段旅程随机抽一张照片放进拼贴，照片点击后回到对应旅程
        photos = [
            {
                "src": random.choice(item.photo_list),
                "title": item.title,
                "journey_id": item.id,
            }
            for item in items
            if item.photo_list
        ][:6]
        groups.append(
            {
                "key": key,
                "year": year,
                "label": f"{year} 年" if year is not None else "未编年",
                "cover": cover,
                "color": JOURNAL_YEAR_COLORS[len(groups) % len(JOURNAL_YEAR_COLORS)],
                "journeys": items,
                "photos": photos,
                "count": len(items),
                "visited": sum(1 for item in items if item.status == "visited"),
                "want": sum(1 for item in items if item.status == "want"),
                "cost": sum(item.total_cost for item in items),
            }
        )
    groups.sort(key=lambda group: (group["year"] is None, -(group["year"] or 0)))
    return groups


def _journey_detail_context(db: Session, journey: Journey) -> dict:
    rows = db.execute(
        select(JourneyPlace, Place)
        .join(Place, JourneyPlace.place_id == Place.id)
        .where(JourneyPlace.journey_id == journey.id)
        .order_by(JourneyPlace.id)
    ).all()
    return {
        "journey": journey,
        "journey_places": [{"place": place, "note": link.note} for link, place in rows],
    }


def _normalize_tab(value: str) -> str:
    """兼容旧链接：visited/map 走地图，其余走游记。"""
    return "map" if value in {"map", "visited", "places"} else "journey"


def travel_context(
    db: Session,
    tab: str = "journey",
    status: str = "",
    point_category: str = "",
    q: str = "",
    journey_status: str = "",
) -> dict:
    tab = _normalize_tab(tab)
    places = list(db.scalars(_place_stmt(status, point_category, q)).all())
    cities = sorted(
        {city.strip() for city in db.scalars(select(Place.city)).all() if city and city.strip()}
    )
    markers = [
        _marker(place)
        for place in db.scalars(select(Place).order_by(Place.id)).all()
        if place.lat and place.lng
    ]
    candidates = db.scalars(
        select(TravelPlaceCandidate)
        .where(TravelPlaceCandidate.status == "pending")
        .order_by(TravelPlaceCandidate.id.desc())
        .limit(20)
    ).all()
    journey_stmt = select(Journey)
    if journey_status in JOURNEY_STATUS_LABELS:
        journey_stmt = journey_stmt.where(Journey.status == journey_status)
    journeys = db.scalars(journey_stmt.order_by(Journey.id.desc())).all()
    context = {
        "tab": tab,
        "places": places,
        "place_groups": _place_groups(places),
        "place_cities": cities,
        "journeys": list(journeys),
        "journey_years": _journey_year_groups(list(journeys)),
        "current_year": date.today().year,
        "journey_status": journey_status,
        "journey_statuses": JOURNEY_STATUS_LABELS,
        "markers": markers,
        "stats": _stats(db),
        "point_categories": list(POINT_CATEGORIES),
        "category_colors": POINT_CATEGORY_COLORS,
        "category_default_color": POINT_CATEGORY_DEFAULT_COLOR,
        "point_statuses": POINT_STATUS_LABELS,
        "status_colors": POINT_STATUS_COLORS,
        "moods": MOOD_LABELS,
        "mood_colors": MOOD_COLORS,
        "candidates": list(candidates),
        "amap_web_key": settings.amap_web_key,
        "amap_security_code": settings.amap_security_js_code,
        "amap_configured": settings.amap_configured,
        "filters": {
            "tab": tab,
            "status": status,
            "point_category": point_category,
            "q": q,
            "journey_status": journey_status,
        },
        "notice": "",
        "error": "",
    }
    return context


def _content_response(
    request: Request,
    db: Session,
    tab: str = "map",
    status: str = "",
    point_category: str = "",
    q: str = "",
    journey_status: str = "",
    notice: str = "",
    error: str = "",
) -> HTMLResponse:
    context = travel_context(db, tab, status, point_category, q, journey_status)
    context["notice"] = notice
    context["error"] = error
    return render_partial(request, "partials/travel_content.html", context)


def _get_place(db: Session, place_id: int) -> Place:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="点位不存在")
    return place


def _get_journey(db: Session, journey_id: int) -> Journey:
    journey = db.get(Journey, journey_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="旅程不存在")
    return journey


def _get_candidate(db: Session, candidate_id: int) -> TravelPlaceCandidate:
    candidate = db.get(TravelPlaceCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选地点不存在")
    return candidate


def _date_text(value) -> str:
    return value.isoformat() if value else ""


AMAP_CATEGORY_RULES = (
    ("风景名胜", "景点"),
    ("公园", "景点"),
    ("寺庙", "景点"),
    ("旅游", "景点"),
    ("餐饮", "美食"),
    ("美食", "美食"),
    ("住宿", "住宿"),
    ("酒店", "住宿"),
    ("宾馆", "住宿"),
    ("交通", "交通"),
    ("机场", "交通"),
    ("车站", "交通"),
    ("地铁", "交通"),
    ("停车场", "交通"),
    ("购物", "商场"),
    ("商场", "商场"),
    ("超市", "商场"),
    ("体育", "娱乐"),
    ("休闲", "娱乐"),
    ("娱乐", "娱乐"),
    ("影", "娱乐"),
    ("乐园", "娱乐"),
    ("文化", "娱乐"),
)


def _category_from_amap(amap_type: str, name: str) -> str:
    text = f"{amap_type or ''} {name or ''}"
    for keyword, category in AMAP_CATEGORY_RULES:
        if keyword in text:
            return category
    return ""


def _place_edit_defaults(place: Place) -> dict:
    return {
        "point_category": place.point_category,
        "rating": place.rating,
        "source_note_url": place.source_note_url,
        "notes": place.notes,
    }


def _place_form_context(
    db: Session,
    place: Place,
    error: str = "",
    values: dict | None = None,
) -> dict:
    merged = _place_edit_defaults(place)
    if values:
        merged.update(values)
    return {
        "place": place,
        "values": merged,
        "point_categories": list(POINT_CATEGORIES),
        "error": error,
    }


def _journey_defaults(journey: Journey | None = None) -> dict:
    values = {
        "title": "",
        "status": "want",
        "start_date": "",
        "end_date": "",
        "mood": "normal",
        "description": "",
        "cost_transport": 0,
        "cost_lodging": 0,
        "cost_food": 0,
        "cost_other": 0,
        "keep_photos": [],
    }
    if journey is not None:
        values.update(
            {
                "title": journey.title,
                "status": journey.status,
                "start_date": _date_text(journey.start_date),
                "end_date": _date_text(journey.end_date),
                "mood": journey.mood,
                "description": journey.description,
                "cost_transport": journey.cost_transport,
                "cost_lodging": journey.cost_lodging,
                "cost_food": journey.cost_food,
                "cost_other": journey.cost_other,
                "keep_photos": journey.photo_list,
            }
        )
    return values


def _journey_links(db: Session, journey: Journey) -> dict[int, str]:
    rows = db.scalars(select(JourneyPlace).where(JourneyPlace.journey_id == journey.id)).all()
    return {row.place_id: row.note for row in rows}


def _journey_form_context(
    db: Session,
    journey: Journey | None = None,
    error: str = "",
    values: dict | None = None,
) -> dict:
    merged = _journey_defaults(journey)
    if values:
        merged.update(values)
    selected = _journey_links(db, journey) if journey is not None else {}
    if values and "place_notes" in values:
        selected = values["place_notes"]
    places = db.scalars(select(Place).order_by(Place.name)).all()
    context = {
        "journey": journey,
        "values": merged,
        "places": list(places),
        "place_notes": selected,
        "journey_statuses": JOURNEY_STATUS_LABELS,
        "moods": MOOD_LABELS,
        "mood_colors": MOOD_COLORS,
        "error": error,
    }
    return context


def _journey_payload(values: dict) -> tuple[dict | None, str]:
    if not values["title"].strip():
        return None, "旅程标题不能为空"
    start = parse_date(values["start_date"])
    end = parse_date(values["end_date"])
    if start and end and end < start:
        return None, "结束日期不能早于开始日期"
    mood = values["mood"] if values["mood"] in MOOD_LABELS else "normal"
    journey_status = values.get("status", "want")
    if journey_status not in JOURNEY_STATUS_LABELS:
        journey_status = "want"

    def money(key: str) -> int:
        return max(0, parse_int(values.get(key, 0)) or 0)

    return {
        "title": values["title"].strip()[:200],
        "status": journey_status,
        "start_date": start,
        "end_date": end,
        "mood": mood,
        "description": values["description"].strip(),
        "cost_transport": money("cost_transport"),
        "cost_lodging": money("cost_lodging"),
        "cost_food": money("cost_food"),
        "cost_other": money("cost_other"),
    }, ""


def _selected_places(form) -> tuple[list[int], dict[int, str]]:
    place_ids: list[int] = []
    notes: dict[int, str] = {}
    for raw in form.getlist("place_ids"):
        text = str(raw).strip()
        if not text.isdigit():
            continue
        place_id = int(text)
        if place_id not in place_ids:
            place_ids.append(place_id)
        notes[place_id] = str(form.get(f"place_note_{place_id}", "")).strip()[:300]
    return place_ids, notes


def _sync_journey_places(
    db: Session,
    journey: Journey,
    place_ids: list[int],
    notes: dict[int, str],
) -> None:
    valid_ids = (
        set(db.scalars(select(Place.id).where(Place.id.in_(place_ids))).all())
        if place_ids
        else set()
    )
    existing = {
        row.place_id: row
        for row in db.scalars(
            select(JourneyPlace).where(JourneyPlace.journey_id == journey.id)
        ).all()
    }
    for place_id, row in existing.items():
        if place_id not in valid_ids:
            db.delete(row)
        elif notes.get(place_id, "") != row.note:
            row.note = notes.get(place_id, "")
    for place_id in valid_ids:
        if place_id in existing:
            continue
        db.add(JourneyPlace(journey_id=journey.id, place_id=place_id, note=notes.get(place_id, "")))


def _delete_photos(paths: list[str]) -> None:
    root = UPLOAD_DIR.resolve()
    for raw in paths:
        path = str(raw)
        if not path.startswith("/uploads/travel/"):
            continue
        relative = path.removeprefix("/uploads/travel/")
        target = (UPLOAD_DIR / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("删除图片失败 %s: %s", target, exc)


async def _save_images(files: list[UploadFile], limit: int, subdir: str = "") -> list[str]:
    saved: list[str] = []
    target_dir = UPLOAD_DIR / subdir if subdir else UPLOAD_DIR
    prefix = f"/uploads/travel/{subdir}/" if subdir else "/uploads/travel/"
    try:
        for upload in files:
            if upload is None or not upload.filename:
                continue
            if len(saved) >= limit:
                raise ValueError(f"最多保存 {limit} 张图片")
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in IMAGE_SUFFIXES:
                raise ValueError("仅支持 JPG、PNG、WebP 格式的图片")
            raw = await upload.read()
            if not raw:
                continue
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError(f"图片「{upload.filename}」超过 5MB")
            target_dir.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}{suffix}"
            (target_dir / name).write_bytes(raw)
            saved.append(f"{prefix}{name}")
    except ValueError:
        _delete_photos(saved)
        raise
    return saved


def _place_form_error(
    request: Request,
    db: Session,
    place: Place,
    message: str,
    values: dict,
) -> HTMLResponse:
    response = render_partial(
        request,
        "partials/modals/place_form.html",
        _place_form_context(db, place, message, values),
    )
    response.headers["HX-Retarget"] = "#modal-body"
    return response


def _journey_form_error(
    request: Request,
    db: Session,
    journey: Journey | None,
    message: str,
    values: dict,
) -> HTMLResponse:
    response = render_partial(
        request,
        "partials/modals/journey_form.html",
        _journey_form_context(db, journey, message, values),
    )
    response.headers["HX-Retarget"] = "#modal-body"
    return response


@router.get("/travel", response_class=HTMLResponse)
def travel_page(
    request: Request,
    tab: str = "journey",
    status: str = "",
    point_category: str = "",
    q: str = "",
    journey_status: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = travel_context(db, tab, status, point_category, q, journey_status)
    return render(request, "travel.html", context, active="travel")


@router.get("/travel/content", response_class=HTMLResponse)
def travel_content(
    request: Request,
    tab: str = "map",
    status: str = "",
    point_category: str = "",
    q: str = "",
    journey_status: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(request, db, tab, status, point_category, q, journey_status)


@router.post("/travel/places/poi", response_class=JSONResponse)
def travel_place_from_poi(
    name: str = Form(""),
    standard_address: str = Form(""),
    lng: str = Form(""),
    lat: str = Form(""),
    point_category: str = Form(""),
    amap_poi_id: str = Form(""),
    city: str = Form(""),
    amap_type: str = Form(""),
    db: Session = Depends(get_db),
) -> JSONResponse:
    name = name.strip()[:200]
    if not name:
        return JSONResponse({"ok": False, "message": "缺少 POI 名称"}, status_code=400)
    try:
        lng_value = float(lng)
        lat_value = float(lat)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "message": "缺少 POI 坐标"}, status_code=400)
    if not (-180 <= lng_value <= 180 and -90 <= lat_value <= 90):
        return JSONResponse({"ok": False, "message": "经纬度范围不合法"}, status_code=400)
    poi_id = amap_poi_id.strip()[:64]
    category = point_category.strip()
    if category not in POINT_CATEGORIES:
        category = _category_from_amap(amap_type, name)
    existing = db.scalar(select(Place).where(Place.amap_poi_id == poi_id)) if poi_id else None
    if existing is not None:
        existing.name = name
        existing.standard_address = standard_address.strip()[:255]
        existing.city = city.strip()[:100]
        existing.lng = lng_value
        existing.lat = lat_value
        if category:
            existing.point_category = category
            existing.category = category
        db.commit()
        db.refresh(existing)
        return JSONResponse({"ok": True, "created": False, "place": _marker(existing)})
    place = Place(
        name=name,
        standard_address=standard_address.strip()[:255],
        city=city.strip()[:100],
        lng=lng_value,
        lat=lat_value,
        point_status="want",
        point_category=category,
        category=category,
        amap_poi_id=poi_id,
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    return JSONResponse({"ok": True, "created": True, "place": _marker(place)})


@router.get("/travel/places/{place_id}", response_class=HTMLResponse)
def travel_place_page(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    context = {
        "place": _get_place(db, place_id),
        "point_statuses": POINT_STATUS_LABELS,
        "status_colors": POINT_STATUS_COLORS,
        "amap_web_key": settings.amap_web_key,
        "amap_security_code": settings.amap_security_js_code,
        "amap_configured": settings.amap_configured,
    }
    return render(request, "place_detail.html", context, active="travel")


@router.get("/travel/places/{place_id}/detail", response_class=HTMLResponse)
def travel_place_detail(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    return render_partial(
        request, "partials/modals/place_detail.html", {"place": _get_place(db, place_id)}
    )


@router.get("/travel/places/{place_id}/edit", response_class=HTMLResponse)
def travel_place_edit_form(
    place_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    return render_partial(
        request,
        "partials/modals/place_form.html",
        _place_form_context(db, place),
    )


@router.post("/travel/places/{place_id}/edit", response_class=HTMLResponse)
def travel_place_update(
    place_id: int,
    request: Request,
    point_category: str = Form(""),
    source_note_url: str = Form(""),
    rating: str = Form("0"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    note_url = source_note_url.strip()[:600]
    category = point_category if point_category in POINT_CATEGORIES else ""
    if note_url and not note_url.startswith(("http://", "https://")):
        values = {
            "point_category": point_category,
            "rating": rating,
            "source_note_url": source_note_url,
            "notes": notes,
        }
        return _place_form_error(
            request, db, place, "小红书笔记链接需以 http:// 或 https:// 开头", values
        )
    place.source_note_url = note_url
    place.point_category = category
    place.category = category
    place.rating = max(0, min(5, parse_int(rating) or 0))
    place.notes = notes.strip()
    db.commit()
    db.refresh(place)
    return HTMLResponse("", headers=_place_saved_headers(place))


@router.post("/travel/places/reorder", response_class=JSONResponse)
async def travel_reorder_places(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        payload = await request.json()
    except (TypeError, ValueError):
        payload = {}
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list):
        return JSONResponse({"ok": False, "message": "排序数据不合法"}, status_code=400)
    ordered: list[int] = []
    for raw in ids:
        try:
            place_id = int(raw)
        except (TypeError, ValueError):
            continue
        if place_id not in ordered:
            ordered.append(place_id)
    rows = (
        {place.id: place for place in db.scalars(select(Place).where(Place.id.in_(ordered))).all()}
        if ordered
        else {}
    )
    for index, place_id in enumerate(ordered):
        place = rows.get(place_id)
        if place is not None:
            place.sort_order = index
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/travel/places/{place_id}/status", response_class=HTMLResponse)
def travel_set_status(
    place_id: int,
    status: str = Form("want"),
    from_list: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    if status not in POINT_STATUS:
        raise HTTPException(status_code=422, detail="点位状态不合法")
    place.point_status = status
    place.visited = status == "visited"
    db.commit()
    # 列表内点击由前端就地更新行，避免整块刷新导致滚动位置丢失。
    payload: dict = {"placeSaved": _marker(place)}
    if not from_list:
        payload["list:refresh"] = True
    return HTMLResponse("", headers=_trigger(payload))


@router.post("/travel/places/{place_id}/rating", response_class=HTMLResponse)
def travel_set_rating(
    place_id: int,
    rating: str = Form("0"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    place.rating = max(0, min(5, parse_int(rating) or 0))
    db.commit()
    return HTMLResponse("", headers=_trigger({"placeSaved": _marker(place)}))


@router.post("/travel/places/{place_id}/delete", response_class=HTMLResponse)
def travel_delete_place(
    place_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    photos = place.photo_list
    db.execute(delete(JourneyPlace).where(JourneyPlace.place_id == place_id))
    db.delete(place)
    db.commit()
    _delete_photos(photos)
    return HTMLResponse(
        "",
        headers=_trigger(
            {"modal:close": True, "list:refresh": True, "placeDeleted": {"id": place_id}}
        ),
    )


@router.post("/travel/candidates/{candidate_id}/confirm", response_class=JSONResponse)
def travel_candidate_confirm(
    candidate_id: int,
    name: str = Form(""),
    standard_address: str = Form(""),
    lng: str = Form(""),
    lat: str = Form(""),
    amap_poi_id: str = Form(""),
    point_category: str = Form(""),
    db: Session = Depends(get_db),
) -> JSONResponse:
    candidate = _get_candidate(db, candidate_id)
    if candidate.status != "pending":
        raise HTTPException(status_code=409, detail="该候选地点已处理")
    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="高德未返回有效坐标") from None
    category = point_category if point_category in POINT_CATEGORIES else ""
    note_url = candidate.note_url
    if not note_url.startswith(("http://", "https://")):
        note_url = ""
    place = Place(
        name=(name.strip() or candidate.name)[:200],
        lat=lat_value,
        lng=lng_value,
        point_status="want",
        visited=False,
        point_category=category,
        category=category,
        standard_address=standard_address.strip()[:255],
        amap_poi_id=amap_poi_id.strip()[:64],
        source_note_url=note_url,
        notes=f"来源笔记：{candidate.note_title}" if candidate.note_title else "",
    )
    db.add(place)
    db.flush()
    candidate.status = "imported"
    candidate.place_id = place.id
    db.commit()
    db.refresh(place)
    return JSONResponse({"ok": True, "place": _marker(place)})


@router.post("/travel/candidates/{candidate_id}/ignore", response_class=JSONResponse)
def travel_candidate_ignore(
    candidate_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    candidate = _get_candidate(db, candidate_id)
    candidate.status = "ignored"
    db.commit()
    return JSONResponse({"ok": True})


def _journey_submitted(
    title: str,
    status: str,
    start_date: str,
    end_date: str,
    mood: str,
    description: str,
    cost_transport: str,
    cost_lodging: str,
    cost_food: str,
    cost_other: str,
    keep_photos: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "mood": mood,
        "description": description,
        "cost_transport": cost_transport,
        "cost_lodging": cost_lodging,
        "cost_food": cost_food,
        "cost_other": cost_other,
        "keep_photos": keep_photos or [],
    }


def _journey_saved_headers(journey: Journey) -> dict[str, str]:
    return _trigger(
        {
            "modal:close": True,
            "list:refresh": True,
            "toast": {"message": f"旅程「{journey.title}」已保存", "type": "success"},
        }
    )


@router.get("/travel/journeys/list", response_class=HTMLResponse)
def travel_journey_list(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    stmt = select(Journey)
    if status in JOURNEY_STATUS_LABELS:
        stmt = stmt.where(Journey.status == status)
    journeys = list(db.scalars(stmt.order_by(Journey.id.desc())).all())
    return render_partial(
        request,
        "partials/journey_list.html",
        {
            "journeys": journeys,
            "journey_years": _journey_year_groups(journeys),
            "current_year": date.today().year,
            "journey_status": status,
            "journey_statuses": JOURNEY_STATUS_LABELS,
        },
    )


@router.get("/travel/journal/stats", response_class=HTMLResponse)
def travel_journal_stats(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/journal_stats.html", {"stats": _stats(db)})


@router.get("/travel/journal/years", response_class=HTMLResponse)
def travel_journal_years(
    request: Request,
    journey_status: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    stmt = select(Journey)
    if journey_status in JOURNEY_STATUS_LABELS:
        stmt = stmt.where(Journey.status == journey_status)
    journeys = list(db.scalars(stmt.order_by(Journey.id.desc())).all())
    return render_partial(
        request,
        "partials/journal_years.html",
        {
            "journey_years": _journey_year_groups(journeys),
            "current_year": date.today().year,
        },
    )


@router.get("/travel/journeys/new", response_class=HTMLResponse)
def travel_journey_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/journey_form.html", _journey_form_context(db))


@router.post("/travel/journeys/new", response_class=HTMLResponse)
async def travel_journey_create(
    request: Request,
    title: str = Form(""),
    status: str = Form("want"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    mood: str = Form("normal"),
    description: str = Form(""),
    cost_transport: str = Form("0"),
    cost_lodging: str = Form("0"),
    cost_food: str = Form("0"),
    cost_other: str = Form("0"),
    images: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    place_ids, notes = _selected_places(form)
    raw = _journey_submitted(
        title,
        status,
        start_date,
        end_date,
        mood,
        description,
        cost_transport,
        cost_lodging,
        cost_food,
        cost_other,
    )
    raw["place_notes"] = notes
    payload, error = _journey_payload(raw)
    if error:
        return _journey_form_error(request, db, None, error, raw)
    try:
        photos = await _save_images(images, MAX_JOURNEY_PHOTOS, JOURNEY_SUBDIR)
    except ValueError as exc:
        return _journey_form_error(request, db, None, str(exc), raw)
    journey = Journey(**payload, photos=json.dumps(photos, ensure_ascii=False))
    try:
        db.add(journey)
        db.flush()
        _sync_journey_places(db, journey, place_ids, notes)
        db.commit()
    except Exception:
        db.rollback()
        _delete_photos(photos)
        raise
    db.refresh(journey)
    return HTMLResponse("", headers=_journey_saved_headers(journey))


@router.get("/travel/journeys/{journey_id}", response_class=HTMLResponse)
def travel_journey_page(
    journey_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    context = _journey_detail_context(db, _get_journey(db, journey_id))
    context.update(
        {
            "amap_web_key": settings.amap_web_key,
            "amap_security_code": settings.amap_security_js_code,
            "amap_configured": settings.amap_configured,
        }
    )
    return render(request, "journey_detail.html", context, active="travel")


@router.get("/travel/journeys/{journey_id}/book", response_class=HTMLResponse)
def travel_journey_book(
    journey_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    context = _journey_detail_context(db, _get_journey(db, journey_id))
    context["year_label"] = (
        context["journey"].start_date.strftime("%Y 年")
        if context["journey"].start_date
        else "未编年"
    )
    return render_partial(request, "partials/modals/journey_book.html", context)


@router.get("/travel/journeys/{journey_id}/edit", response_class=HTMLResponse)
def travel_journey_edit_form(
    journey_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    journey = _get_journey(db, journey_id)
    return render_partial(
        request,
        "partials/modals/journey_form.html",
        _journey_form_context(db, journey),
    )


@router.post("/travel/journeys/{journey_id}/edit", response_class=HTMLResponse)
async def travel_journey_update(
    journey_id: int,
    request: Request,
    title: str = Form(""),
    status: str = Form("want"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    mood: str = Form("normal"),
    description: str = Form(""),
    cost_transport: str = Form("0"),
    cost_lodging: str = Form("0"),
    cost_food: str = Form("0"),
    cost_other: str = Form("0"),
    keep_photos: list[str] = Form([]),
    images: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    journey = _get_journey(db, journey_id)
    form = await request.form()
    place_ids, notes = _selected_places(form)
    existing = journey.photo_list
    kept = list(dict.fromkeys(path for path in keep_photos if path in existing))
    raw = _journey_submitted(
        title,
        status,
        start_date,
        end_date,
        mood,
        description,
        cost_transport,
        cost_lodging,
        cost_food,
        cost_other,
        kept,
    )
    raw["place_notes"] = notes
    payload, error = _journey_payload(raw)
    if error:
        return _journey_form_error(request, db, journey, error, raw)
    try:
        photos = await _save_images(images, max(0, MAX_JOURNEY_PHOTOS - len(kept)), JOURNEY_SUBDIR)
    except ValueError as exc:
        return _journey_form_error(request, db, journey, str(exc), raw)
    removed = [path for path in existing if path not in kept]
    for field, value in payload.items():
        setattr(journey, field, value)
    journey.photos = json.dumps(kept + photos, ensure_ascii=False)
    try:
        _sync_journey_places(db, journey, place_ids, notes)
        db.commit()
    except Exception:
        db.rollback()
        _delete_photos(photos)
        raise
    db.refresh(journey)
    _delete_photos(removed)
    return HTMLResponse("", headers=_journey_saved_headers(journey))


@router.post("/travel/journeys/{journey_id}/delete", response_class=HTMLResponse)
def travel_journey_delete(
    journey_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    journey = _get_journey(db, journey_id)
    photos = journey.photo_list
    db.execute(delete(JourneyPlace).where(JourneyPlace.journey_id == journey.id))
    db.delete(journey)
    db.commit()
    _delete_photos(photos)
    return HTMLResponse("", headers={"HX-Redirect": "/travel?tab=journey"})


def _add_to_journey_context(db: Session, place: Place, error: str = "") -> dict:
    journeys = db.scalars(select(Journey).order_by(Journey.id.desc())).all()
    return {"place": place, "journeys": list(journeys), "error": error}


@router.get("/travel/places/{place_id}/add-to-journey", response_class=HTMLResponse)
def travel_add_to_journey_form(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    place = _get_place(db, place_id)
    return render_partial(
        request,
        "partials/modals/add_to_journey.html",
        _add_to_journey_context(db, place),
    )


@router.post("/travel/places/{place_id}/journeys", response_class=HTMLResponse)
def travel_add_place_to_journey(
    place_id: int,
    request: Request,
    journey_id: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    parsed = parse_int(journey_id)
    journey = db.get(Journey, parsed) if parsed else None
    if journey is None:
        return render_partial(
            request,
            "partials/modals/add_to_journey.html",
            _add_to_journey_context(db, place, "请选择要加入的旅程"),
        )
    link = db.scalar(
        select(JourneyPlace).where(
            JourneyPlace.journey_id == journey.id,
            JourneyPlace.place_id == place.id,
        )
    )
    if link is None:
        link = JourneyPlace(journey_id=journey.id, place_id=place.id)
        db.add(link)
    link.note = note.strip()[:300]
    db.commit()
    return HTMLResponse(
        "",
        headers=_trigger(
            {
                "modal:close": True,
                "list:refresh": True,
                "toast": {"message": "已加入旅程", "type": "success"},
            }
        ),
    )
