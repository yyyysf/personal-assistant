"""旅游规划 & 地图标记：Leaflet 打点、行程草稿、旅行足迹。"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.common import parse_date, parse_int
from src.api.deps import get_db, render, render_partial
from src.api.pagination import paginate
from src.core.config import BASE_DIR
from src.core.logging import get_logger
from src.core.taxonomy import all_tags, category_names, tag_filter
from src.models import Place, TripPlan

router = APIRouter()
logger = get_logger(__name__)
MODAL_DONE = {"HX-Trigger": '{"modal:close": true, "list:refresh": true}'}
UPLOAD_DIR = Path(BASE_DIR) / "uploads" / "travel"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PHOTOS = 6
TRIP_STATUS = {"draft": "草稿", "planned": "已计划", "done": "已完成"}


def _trigger(payload: dict) -> dict[str, str]:
    # HTTP header 只能承载 latin-1，中文需转义为 \uXXXX，htmx 仍按 JSON 解析。
    return {"HX-Trigger": json.dumps(payload, ensure_ascii=True)}


def _marker(place: Place) -> dict:
    return {
        "id": place.id,
        "name": place.name,
        "city": place.city,
        "country": place.country,
        "lat": place.lat,
        "lng": place.lng,
        "visited": place.visited,
        "rating": place.rating,
        "category": place.category,
        "date_label": place.date_label,
        "notes": place.notes,
    }


def _stats(db: Session) -> dict:
    total_places = int(db.scalar(select(func.count()).select_from(Place)) or 0)
    visited = int(
        db.scalar(select(func.count()).select_from(Place).where(Place.visited.is_(True))) or 0
    )
    total_trips = int(db.scalar(select(func.count()).select_from(TripPlan)) or 0)
    return {"total_places": total_places, "visited": visited, "trips": total_trips}


def _place_stmt(category: str, tag: str, q: str):
    stmt = select(Place)
    if category:
        stmt = stmt.where(Place.category == category)
    if tag.strip():
        stmt = stmt.where(tag_filter(Place.tags, tag))
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Place.name.ilike(pattern),
                Place.city.ilike(pattern),
                Place.country.ilike(pattern),
                Place.category.ilike(pattern),
                Place.tags.ilike(pattern),
                Place.notes.ilike(pattern),
            )
        )
    return stmt.order_by(Place.visited.desc(), Place.id.desc())


def _trip_stmt(category: str, tag: str, q: str):
    stmt = select(TripPlan)
    if category:
        stmt = stmt.where(TripPlan.category == category)
    if tag.strip():
        stmt = stmt.where(tag_filter(TripPlan.tags, tag))
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                TripPlan.title.ilike(pattern),
                TripPlan.category.ilike(pattern),
                TripPlan.tags.ilike(pattern),
                TripPlan.itinerary.ilike(pattern),
                TripPlan.notes.ilike(pattern),
            )
        )
    return stmt.order_by(TripPlan.id.desc())


def travel_context(
    db: Session,
    tab: str = "visited",
    category: str = "",
    tag: str = "",
    q: str = "",
    page: int = 1,
    trip_page: int = 1,
) -> dict:
    tab = tab if tab in {"visited", "draft"} else "visited"
    places_page = paginate(db, _place_stmt(category, tag, q), page)
    trips_page = paginate(db, _trip_stmt(category, tag, q), trip_page)
    markers = [
        _marker(place)
        for place in db.scalars(select(Place).order_by(Place.id)).all()
        if place.lat and place.lng
    ]
    return {
        "tab": tab,
        "places": places_page["items"],
        "page_data": places_page,
        "trips": trips_page["items"],
        "trip_page_data": trips_page,
        "markers": markers,
        "stats": _stats(db),
        "categories": category_names(db, "place"),
        "trip_categories": category_names(db, "trip"),
        "tag_options": all_tags(db, "place"),
        "trip_tag_options": all_tags(db, "trip"),
        "filters": {"tab": tab, "category": category, "tag": tag, "q": q},
        "notice": "",
        "error": "",
    }


def _content_response(
    request: Request,
    db: Session,
    tab: str = "visited",
    category: str = "",
    tag: str = "",
    q: str = "",
    page: int = 1,
    trip_page: int = 1,
    notice: str = "",
    error: str = "",
) -> HTMLResponse:
    context = travel_context(db, tab, category, tag, q, page, trip_page)
    context["notice"] = notice
    context["error"] = error
    return render_partial(request, "partials/travel_content.html", context)


def _get_place(db: Session, place_id: int) -> Place:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="足迹不存在")
    return place


def _get_trip(db: Session, trip_id: int) -> TripPlan:
    trip = db.get(TripPlan, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="行程不存在")
    return trip


def _date_text(value) -> str:
    return value.isoformat() if value else ""


def _place_defaults(place: Place | None = None, lat: str = "", lng: str = "") -> dict:
    values = {
        "name": "",
        "city": "",
        "country": "",
        "lat": lat or "",
        "lng": lng or "",
        "visited": True,
        "category": "",
        "tags": "",
        "date_mode": "single",
        "visit_date": "",
        "visit_end_date": "",
        "rating": 0,
        "notes": "",
        "keep_photos": [],
    }
    if place is not None:
        values.update(
            {
                "name": place.name,
                "city": place.city,
                "country": place.country,
                "lat": place.lat,
                "lng": place.lng,
                "visited": place.visited,
                "category": place.category,
                "tags": place.tags,
                "date_mode": place.date_mode or "single",
                "visit_date": _date_text(place.visit_date),
                "visit_end_date": _date_text(place.visit_end_date),
                "rating": place.rating,
                "notes": place.notes,
                "keep_photos": place.photo_list,
            }
        )
    return values


def _place_form_context(
    db: Session,
    place: Place | None = None,
    error: str = "",
    values: dict | None = None,
    lat: str = "",
    lng: str = "",
) -> dict:
    merged = _place_defaults(place, lat, lng)
    if values:
        merged.update(values)
    return {
        "place": place,
        "values": merged,
        "categories": category_names(db, "place"),
        "tag_options": all_tags(db, "place"),
        "error": error,
    }


def _submitted_place(
    name: str,
    city: str,
    country: str,
    lat: str,
    lng: str,
    visited: str,
    category: str,
    tags: str,
    date_mode: str,
    visit_date: str,
    visit_end_date: str,
    rating: str,
    notes: str,
) -> dict:
    return {
        "name": name,
        "city": city,
        "country": country,
        "lat": lat,
        "lng": lng,
        "visited": bool(visited),
        "category": category,
        "tags": tags,
        "date_mode": date_mode,
        "visit_date": visit_date,
        "visit_end_date": visit_end_date,
        "rating": parse_int(rating) or 0,
        "notes": notes,
    }


def _place_payload(values: dict) -> tuple[dict | None, str]:
    if not values["name"].strip():
        return None, "地点名称不能为空"
    try:
        lat_value = float(values["lat"])
        lng_value = float(values["lng"])
    except (TypeError, ValueError):
        return None, "请在地图上点选坐标，或填写合法经纬度"
    if not (-90 <= lat_value <= 90 and -180 <= lng_value <= 180):
        return None, "经纬度范围不合法"
    mode = values["date_mode"] if values["date_mode"] in {"single", "range"} else "single"
    start = parse_date(values["visit_date"])
    end = parse_date(values["visit_end_date"]) if mode == "range" else None
    if mode == "range" and start and end and end < start:
        return None, "结束日期不能早于开始日期"
    stars = parse_int(values["rating"]) or 0
    return {
        "name": values["name"].strip()[:200],
        "city": values["city"].strip()[:100],
        "country": values["country"].strip()[:100],
        "lat": lat_value,
        "lng": lng_value,
        "visited": bool(values["visited"]),
        "category": values["category"].strip()[:60],
        "tags": values["tags"].strip()[:200],
        "date_mode": mode,
        "visit_date": start,
        "visit_end_date": end,
        "rating": max(0, min(5, stars)),
        "notes": values["notes"].strip(),
    }, ""


def _trip_defaults(trip: TripPlan | None = None) -> dict:
    values = {
        "title": "",
        "category": "",
        "tags": "",
        "status": "draft",
        "start_date": "",
        "end_date": "",
        "itinerary": "",
        "notes": "",
    }
    if trip is not None:
        values.update(
            {
                "title": trip.title,
                "category": trip.category,
                "tags": trip.tags,
                "status": trip.status,
                "start_date": _date_text(trip.start_date),
                "end_date": _date_text(trip.end_date),
                "itinerary": trip.itinerary,
                "notes": trip.notes,
            }
        )
    return values


def _trip_form_context(
    db: Session,
    trip: TripPlan | None = None,
    error: str = "",
    values: dict | None = None,
) -> dict:
    merged = _trip_defaults(trip)
    if values:
        merged.update(values)
    return {
        "trip": trip,
        "values": merged,
        "statuses": TRIP_STATUS,
        "categories": category_names(db, "trip"),
        "tag_options": all_tags(db, "trip"),
        "error": error,
    }


def _trip_payload(values: dict) -> tuple[dict | None, str]:
    if not values["title"].strip():
        return None, "行程标题不能为空"
    status = values["status"] if values["status"] in TRIP_STATUS else "draft"
    start = parse_date(values["start_date"])
    end = parse_date(values["end_date"])
    if start and end and end < start:
        return None, "结束日期不能早于开始日期"
    return {
        "title": values["title"].strip()[:200],
        "category": values["category"].strip()[:60],
        "tags": values["tags"].strip()[:200],
        "status": status,
        "start_date": start,
        "end_date": end,
        "itinerary": values["itinerary"].strip(),
        "notes": values["notes"].strip(),
    }, ""


def _delete_photos(paths: list[str]) -> None:
    for path in paths:
        if not str(path).startswith("/uploads/travel/"):
            continue
        target = UPLOAD_DIR / Path(str(path)).name
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("删除图片失败 %s: %s", target, exc)


async def _save_images(files: list[UploadFile], limit: int) -> list[str]:
    saved: list[str] = []
    try:
        for upload in files:
            if upload is None or not upload.filename:
                continue
            if len(saved) >= limit:
                raise ValueError(f"每个足迹最多保存 {MAX_PHOTOS} 张图片")
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in IMAGE_SUFFIXES:
                raise ValueError("仅支持 JPG、PNG、WebP 格式的图片")
            raw = await upload.read()
            if not raw:
                continue
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError(f"图片「{upload.filename}」超过 5MB")
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}{suffix}"
            (UPLOAD_DIR / name).write_bytes(raw)
            saved.append(f"/uploads/travel/{name}")
    except ValueError:
        _delete_photos(saved)
        raise
    return saved


def _place_form_error(
    request: Request,
    db: Session,
    place: Place | None,
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


def _trip_form_error(
    request: Request,
    db: Session,
    trip: TripPlan | None,
    message: str,
    values: dict,
) -> HTMLResponse:
    response = render_partial(
        request,
        "partials/modals/trip_form.html",
        _trip_form_context(db, trip, message, values),
    )
    response.headers["HX-Retarget"] = "#modal-body"
    return response


@router.get("/travel", response_class=HTMLResponse)
def travel_page(
    request: Request,
    tab: str = "visited",
    category: str = "",
    tag: str = "",
    q: str = "",
    page: int = 1,
    trip_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = travel_context(db, tab, category, tag, q, page, trip_page)
    return render(request, "travel.html", context, active="travel")


@router.get("/travel/content", response_class=HTMLResponse)
def travel_content(
    request: Request,
    tab: str = "visited",
    category: str = "",
    tag: str = "",
    q: str = "",
    page: int = 1,
    trip_page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _content_response(request, db, tab, category, tag, q, page, trip_page)


@router.get("/travel/places/new", response_class=HTMLResponse)
def travel_place_new(
    request: Request,
    lat: str = "",
    lng: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return render_partial(
        request, "partials/modals/place_form.html", _place_form_context(db, lat=lat, lng=lng)
    )


@router.post("/travel/places/new", response_class=HTMLResponse)
async def travel_place_create(
    request: Request,
    name: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    lat: str = Form(""),
    lng: str = Form(""),
    visited: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    date_mode: str = Form("single"),
    visit_date: str = Form(""),
    visit_end_date: str = Form(""),
    rating: str = Form("0"),
    notes: str = Form(""),
    images: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    raw = _submitted_place(
        name,
        city,
        country,
        lat,
        lng,
        visited,
        category,
        tags,
        date_mode,
        visit_date,
        visit_end_date,
        rating,
        notes,
    )
    payload, error = _place_payload(raw)
    if error:
        return _place_form_error(request, db, None, error, raw)
    try:
        photos = await _save_images(images, MAX_PHOTOS)
    except ValueError as exc:
        return _place_form_error(request, db, None, str(exc), raw)
    place = Place(**payload, photos=json.dumps(photos, ensure_ascii=False))
    db.add(place)
    db.commit()
    db.refresh(place)
    return HTMLResponse(
        "",
        headers=_trigger({"modal:close": True, "list:refresh": True, "placeSaved": _marker(place)}),
    )


@router.get("/travel/places/{place_id}/detail", response_class=HTMLResponse)
def travel_place_detail(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    return render_partial(
        request, "partials/modals/place_detail.html", {"place": _get_place(db, place_id)}
    )


@router.get("/travel/places/{place_id}/edit", response_class=HTMLResponse)
def travel_place_edit_form(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    place = _get_place(db, place_id)
    return render_partial(
        request, "partials/modals/place_form.html", _place_form_context(db, place)
    )


@router.post("/travel/places/{place_id}/edit", response_class=HTMLResponse)
async def travel_place_update(
    place_id: int,
    request: Request,
    name: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    lat: str = Form(""),
    lng: str = Form(""),
    visited: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    date_mode: str = Form("single"),
    visit_date: str = Form(""),
    visit_end_date: str = Form(""),
    rating: str = Form("0"),
    notes: str = Form(""),
    keep_photos: list[str] = Form([]),
    images: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    raw = _submitted_place(
        name,
        city,
        country,
        lat,
        lng,
        visited,
        category,
        tags,
        date_mode,
        visit_date,
        visit_end_date,
        rating,
        notes,
    )
    existing = place.photo_list
    kept = [path for path in keep_photos if path in existing]
    kept = list(dict.fromkeys(kept))
    raw["keep_photos"] = kept
    payload, error = _place_payload(raw)
    if error:
        return _place_form_error(request, db, place, error, raw)
    try:
        photos = await _save_images(images, max(0, MAX_PHOTOS - len(kept)))
    except ValueError as exc:
        return _place_form_error(request, db, place, str(exc), raw)
    removed = [path for path in existing if path not in kept]
    for field, value in payload.items():
        setattr(place, field, value)
    place.photos = json.dumps(kept + photos, ensure_ascii=False)
    db.commit()
    db.refresh(place)
    _delete_photos(removed)
    return HTMLResponse(
        "",
        headers=_trigger({"modal:close": True, "list:refresh": True, "placeSaved": _marker(place)}),
    )


@router.post("/travel/places/{place_id}/visited", response_class=HTMLResponse)
def travel_toggle_visited(
    place_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    place.visited = not place.visited
    db.commit()
    return HTMLResponse(
        "",
        headers=_trigger({"modal:close": True, "list:refresh": True, "placeSaved": _marker(place)}),
    )


@router.post("/travel/places/{place_id}/delete", response_class=HTMLResponse)
def travel_delete_place(
    place_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    place = _get_place(db, place_id)
    photos = place.photo_list
    db.delete(place)
    db.commit()
    _delete_photos(photos)
    return HTMLResponse(
        "",
        headers=_trigger(
            {"modal:close": True, "list:refresh": True, "placeDeleted": {"id": place_id}}
        ),
    )


@router.get("/travel/trips/new", response_class=HTMLResponse)
def travel_trip_new(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render_partial(request, "partials/modals/trip_form.html", _trip_form_context(db))


@router.post("/travel/trips/new", response_class=HTMLResponse)
def travel_trip_create(
    request: Request,
    title: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    status: str = Form("draft"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    itinerary: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    raw = {
        "title": title,
        "category": category,
        "tags": tags,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "itinerary": itinerary,
        "notes": notes,
    }
    payload, error = _trip_payload(raw)
    if error:
        return _trip_form_error(request, db, None, error, raw)
    db.add(TripPlan(**payload))
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.get("/travel/trips/{trip_id}/detail", response_class=HTMLResponse)
def travel_trip_detail(
    trip_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    return render_partial(
        request,
        "partials/modals/trip_detail.html",
        {"trip": _get_trip(db, trip_id), "statuses": TRIP_STATUS},
    )


@router.get("/travel/trips/{trip_id}/edit", response_class=HTMLResponse)
def travel_trip_edit_form(
    trip_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    trip = _get_trip(db, trip_id)
    return render_partial(request, "partials/modals/trip_form.html", _trip_form_context(db, trip))


@router.post("/travel/trips/{trip_id}/edit", response_class=HTMLResponse)
def travel_trip_update(
    trip_id: int,
    request: Request,
    title: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    status: str = Form("draft"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    itinerary: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    trip = _get_trip(db, trip_id)
    raw = {
        "title": title,
        "category": category,
        "tags": tags,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "itinerary": itinerary,
        "notes": notes,
    }
    payload, error = _trip_payload(raw)
    if error:
        return _trip_form_error(request, db, trip, error, raw)
    for field, value in payload.items():
        setattr(trip, field, value)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)


@router.post("/travel/trips/{trip_id}/delete", response_class=HTMLResponse)
def travel_delete_trip(trip_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    trip = _get_trip(db, trip_id)
    db.delete(trip)
    db.commit()
    return HTMLResponse("", headers=MODAL_DONE)
