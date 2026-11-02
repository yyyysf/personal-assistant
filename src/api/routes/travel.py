"""旅游规划 & 地图标记：Leaflet 打点、行程草稿、旅行足迹。"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.common import parse_date
from src.api.deps import get_db, render, render_partial
from src.models import Place, TripPlan

router = APIRouter()


def travel_context(db: Session) -> dict:
    places = db.scalars(select(Place).order_by(Place.visited.desc(), Place.id.desc())).all()
    trips = db.scalars(select(TripPlan).order_by(TripPlan.id.desc())).all()
    markers = [
        {
            "id": place.id,
            "name": place.name,
            "city": place.city,
            "country": place.country,
            "lat": place.lat,
            "lng": place.lng,
            "visited": place.visited,
            "notes": place.notes,
        }
        for place in places
        if place.lat and place.lng
    ]
    return {
        "places": places,
        "trips": trips,
        "markers": markers,
        "markers_json": json.dumps(markers, ensure_ascii=False),
        "visited_count": sum(1 for place in places if place.visited),
        "error": "",
        "notice": "",
    }


@router.get("/travel", response_class=HTMLResponse)
def travel_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(request, "travel.html", travel_context(db), active="travel")


@router.post("/travel/places", response_class=HTMLResponse)
def travel_add_place(
    request: Request,
    name: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    lat: str = Form(""),
    lng: str = Form(""),
    visited: str = Form(""),
    visit_date: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = travel_context(db)
    if not name.strip():
        context["error"] = "地点名称不能为空"
        return render_partial(request, "partials/travel_places.html", context)
    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        context["error"] = "请在地图上点选坐标，或填写合法经纬度"
        return render_partial(request, "partials/travel_places.html", context)
    if not (-90 <= lat_value <= 90 and -180 <= lng_value <= 180):
        context["error"] = "经纬度范围不合法"
        return render_partial(request, "partials/travel_places.html", context)

    place = Place(
        name=name.strip(),
        city=city.strip(),
        country=country.strip(),
        lat=lat_value,
        lng=lng_value,
        visited=bool(visited),
        visit_date=parse_date(visit_date),
        notes=notes.strip(),
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    context = travel_context(db)
    context["notice"] = f"已添加地点「{place.name}」"
    response = render_partial(request, "partials/travel_places.html", context)
    response.headers["HX-Trigger"] = json.dumps(
        {
            "placeAdded": {
                "id": place.id,
                "name": place.name,
                "city": place.city,
                "country": place.country,
                "lat": place.lat,
                "lng": place.lng,
                "visited": place.visited,
                "notes": place.notes,
            }
        },
        ensure_ascii=False,
    )
    return response


@router.post("/travel/places/{place_id}/visited", response_class=HTMLResponse)
def travel_toggle_visited(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="地点不存在")
    place.visited = not place.visited
    db.commit()
    return render_partial(request, "partials/travel_places.html", travel_context(db))


@router.post("/travel/places/{place_id}/delete", response_class=HTMLResponse)
def travel_delete_place(
    place_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="地点不存在")
    db.delete(place)
    db.commit()
    return render_partial(request, "partials/travel_places.html", travel_context(db))


@router.post("/travel/trips", response_class=HTMLResponse)
def travel_add_trip(
    request: Request,
    title: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    itinerary: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = travel_context(db)
    if not title.strip():
        context["error"] = "行程标题不能为空"
    else:
        db.add(
            TripPlan(
                title=title.strip(),
                start_date=parse_date(start_date),
                end_date=parse_date(end_date),
                itinerary=itinerary.strip(),
                notes=notes.strip(),
            )
        )
        db.commit()
        context = travel_context(db)
        context["notice"] = "行程草稿已保存"
    return render_partial(request, "partials/travel_trips.html", context)
