"""核心接口与页面可用性测试。"""

import json

from sqlalchemy import select

from src.core.db import SessionLocal
from src.models import Journey, JourneyPlace, Place, TravelPlaceCandidate


def test_health_and_dashboard(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["data"]["llm_configured"] is False

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "总览看板" in dashboard.text
    assert "本月" in dashboard.text or "热力" in dashboard.text


def test_task_crud_and_dashboard_stats(client):
    created = client.post(
        "/api/v1/tasks",
        json={"title": "测试 API 任务", "priority": "high", "tags": "测试,API"},
    )
    assert created.status_code == 200
    task_id = created.json()["data"]["id"]
    assert created.json()["data"]["tags"] == ["测试"]

    listed = client.get("/api/v1/tasks")
    assert listed.json()["data"][0]["id"] == task_id

    updated = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done"})
    assert updated.status_code == 200
    assert updated.json()["data"]["completed_at"] is not None

    stats = client.get("/api/v1/dashboard/stats")
    assert stats.status_code == 200
    body = stats.json()["data"]
    assert body["stats"]["today_done"] == 1
    assert body["stats"]["streak"] >= 1

    deleted = client.delete(f"/api/v1/tasks/{task_id}")
    assert deleted.status_code == 200


def test_html_task_board_actions(client):
    response = client.post(
        "/todo/tasks",
        data={"title": "看板任务", "priority": "medium", "tags": "看板"},
    )
    assert response.status_code == 200
    assert "看板任务" in response.text
    assert 'id="todo-board"' in response.text


def test_all_pages_render(client):
    for path in (
        "/todo",
        "/research",
        "/reading",
        "/news",
        "/learning/video",
        "/learning/music",
        "/travel",
        "/schedule",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Private Assistant" in response.text


def test_missing_learning_module_returns_structured_error(client):
    response = client.get("/api/v1/learning/unknown")
    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "message": "学习模块不存在",
        "data": None,
    }


def test_xhs_upload_and_book_export(client):
    payload = [
        {
            "title": "我的 AI 书单收藏",
            "desc": "强烈推荐《构建第二大脑》和《深度学习革命》，适合入门。",
            "url": "https://www.xiaohongshu.com/explore/demo",
            "author": "测试博主",
        }
    ]
    response = client.post(
        "/api/v1/reading/upload",
        files={
            "file": (
                "xhs.json",
                json.dumps(payload, ensure_ascii=False).encode(),
                "application/json",
            )
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["notes_created"] == 1
    assert data["books_created"] == 2

    books = client.get("/api/v1/books").json()["data"]
    titles = {book["title"] for book in books}
    assert "构建第二大脑" in titles

    export = client.get("/reading/export")
    assert export.status_code == 200
    assert "构建第二大脑" in export.text


def test_learning_plan_fallback_and_progress(client):
    plan = client.post("/api/v1/learning/music/plan")
    assert plan.status_code == 200
    data = plan.json()["data"]
    assert len(data["created"]) == 3

    track = client.get("/api/v1/learning/music").json()["data"]
    assert track["category"] == "music"
    item = track["items"][0]

    updated = client.patch(f"/api/v1/learning/items/{item['id']}", json={"mastery": 80})
    assert updated.status_code == 200
    assert updated.json()["data"]["status"] == "done"


def test_travel_place_crud(client):
    created = client.post(
        "/api/v1/places",
        json={"name": "测试地点", "city": "杭州", "lat": 30.25, "lng": 120.16},
    )
    assert created.status_code == 200
    place_id = created.json()["data"]["id"]

    updated = client.patch(f"/api/v1/places/{place_id}", json={"visited": True})
    assert updated.json()["data"]["visited"] is True

    page = client.get("/travel?tab=map")
    assert "测试地点" in page.text

    deleted = client.delete(f"/api/v1/places/{place_id}")
    assert deleted.status_code == 200


def test_travel_place_groups_and_reorder(client):
    first = _create_place(client, "排序一", "景点")
    second = _create_place(client, "排序二", "景点")
    third = _create_place(client, "拉面摊", "美食")

    page = client.get("/travel?tab=map")
    assert page.status_code == 200
    assert 'data-group-key="景点"' in page.text
    assert 'data-group-key="美食"' in page.text
    assert "data-list-sort" in page.text
    assert "data-list-rating-filter" in page.text
    assert "data-list-status-filter" in page.text
    assert '<option value="visited">已去</option>' in page.text
    assert '<option value="京都">京都</option>' in page.text
    assert 'data-city="京都"' in page.text
    assert page.text.index('data-place-id="' + str(first) + '"') < page.text.index(
        'data-place-id="' + str(second) + '"'
    )

    reordered = client.post("/travel/places/reorder", json={"ids": [second, first, third]})
    assert reordered.status_code == 200
    assert reordered.json()["ok"] is True
    with SessionLocal() as db:
        assert db.get(Place, second).sort_order == 0
        assert db.get(Place, first).sort_order == 1
        assert db.get(Place, third).sort_order == 2

    page_after = client.get("/travel?tab=map")
    assert page_after.text.index('data-place-id="' + str(second) + '"') < page_after.text.index(
        'data-place-id="' + str(first) + '"'
    )

    bad = client.post("/travel/places/reorder", json={"ids": "nope"})
    assert bad.status_code == 400


def test_place_status_and_rating_quick_actions(client):
    place_id = _create_place(client, "可交互点位", "景点")
    page = client.get("/travel?tab=map")
    assert "data-status-toggle" in page.text
    assert 'data-rate="5"' in page.text

    toggled = client.post(
        f"/travel/places/{place_id}/status",
        data={"status": "visited", "from_list": "1"},
    )
    assert toggled.status_code == 200
    trigger = json.loads(toggled.headers["HX-Trigger"])
    assert "list:refresh" not in trigger
    assert trigger["placeSaved"]["point_status"] == "visited"

    rated = client.post(f"/travel/places/{place_id}/rating", data={"rating": "4"})
    assert rated.status_code == 200
    assert json.loads(rated.headers["HX-Trigger"])["placeSaved"]["rating"] == 4
    with SessionLocal() as db:
        place = db.get(Place, place_id)
        assert place.rating == 4
        assert place.point_status == "visited"
        assert place.marker_color == "#2a9d8f"

    capped = client.post(f"/travel/places/{place_id}/rating", data={"rating": "9"})
    assert json.loads(capped.headers["HX-Trigger"])["placeSaved"]["rating"] == 5


def test_travel_poi_import_and_optional_edit(client):
    response = client.post(
        "/travel/places/poi",
        data={
            "name": "测试咖啡馆",
            "city": "京都",
            "standard_address": "京都府京都市东山区",
            "lng": "135.768100",
            "lat": "35.003700",
            "amap_poi_id": "B0TEST",
            "amap_type": "餐饮服务;咖啡厅",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["created"] is True
    place_data = payload["place"]
    place_id = place_data["id"]
    assert place_data["point_status"] == "want"
    assert place_data["point_category"] == "美食"
    assert place_data["standard_address"] == "京都府京都市东山区"

    duplicate = client.post(
        "/travel/places/poi",
        data={
            "name": "测试咖啡馆（新）",
            "standard_address": "京都府京都市东山区",
            "lng": "135.768100",
            "lat": "35.003700",
            "amap_poi_id": "B0TEST",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    with SessionLocal() as db:
        places = db.scalars(select(Place)).all()
        assert len(places) == 1
        assert places[0].name == "测试咖啡馆（新）"

    edited = client.post(
        f"/travel/places/{place_id}/edit",
        data={
            "point_category": "交通",
            "rating": "5",
            "source_note_url": "https://www.xiaohongshu.com/explore/abc",
            "notes": "下午茶",
        },
    )
    assert edited.status_code == 200
    assert edited.headers.get("HX-Trigger")
    with SessionLocal() as db:
        place = db.get(Place, place_id)
        assert place.rating == 5
        assert place.point_category == "交通"
        assert place.category == "交通"
        assert place.notes == "下午茶"

    detail = client.get(f"/travel/places/{place_id}")
    assert detail.status_code == 200
    assert "高德标准地址" in detail.text
    assert "想去" in detail.text
    assert "交通" in detail.text

    assert client.get("/travel/places/new").status_code != 200
    assert client.get("/travel/content?status=want&point_category=交通").status_code == 200

    status_response = client.post(f"/travel/places/{place_id}/status", data={"status": "visited"})
    assert status_response.status_code == 200
    with SessionLocal() as db:
        place = db.get(Place, place_id)
        assert place.point_status == "visited"
        assert place.visited is True


def test_travel_candidate_confirm_and_ignore(client):
    with SessionLocal() as db:
        first = TravelPlaceCandidate(name="候选一", note_title="笔记", note_url="https://xhs/1")
        second = TravelPlaceCandidate(name="候选二", note_title="笔记", note_url="")
        db.add_all([first, second])
        db.commit()
        db.refresh(first)
        db.refresh(second)
        first_id, second_id = first.id, second.id

    confirmed = client.post(
        f"/travel/candidates/{first_id}/confirm",
        data={
            "name": "确认地点",
            "standard_address": "地址",
            "lng": "120.16",
            "lat": "30.25",
            "point_category": "景点",
            "amap_poi_id": "B0CAND",
        },
    )
    assert confirmed.status_code == 200
    place = confirmed.json()["place"]
    assert place["point_status"] == "want"
    assert place["source_note_url"] == "https://xhs/1"

    repeat = client.post(f"/travel/candidates/{first_id}/confirm", data={"lat": "1", "lng": "1"})
    assert repeat.status_code == 409

    ignored = client.post(f"/travel/candidates/{second_id}/ignore")
    assert ignored.status_code == 200


def _create_place(client, name: str, category: str = "景点") -> int:
    response = client.post(
        "/api/v1/places",
        json={
            "name": name,
            "city": "京都",
            "lat": 35.0,
            "lng": 135.7,
            "point_status": "visited",
            "point_category": category,
            "rating": 4,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_journey_create_list_detail_and_stats(client):
    first_id = _create_place(client, "清水寺")
    second_id = _create_place(client, "拉面店", "美食")
    created = client.post(
        "/travel/journeys/new",
        data={
            "title": "京都赏樱 4 日",
            "start_date": "2026-04-01",
            "end_date": "2026-04-04",
            "status": "visited",
            "mood": "happy",
            "description": "樱花全开，值回票价。",
            "cost_transport": "1200",
            "cost_lodging": "2000",
            "cost_food": "800",
            "cost_other": "300",
            "place_ids": [str(first_id), str(second_id)],
            f"place_note_{first_id}": "人很多但很震撼",
            f"place_note_{second_id}": "排队 40 分钟",
        },
    )
    assert created.status_code == 200
    assert created.headers.get("HX-Trigger")

    with SessionLocal() as db:
        journey = db.scalars(select(Journey)).one()
        journey_id = journey.id
        assert journey.mood == "happy"
        assert journey.status == "visited"
        assert journey.status_label == "已去过"
        assert journey.total_cost == 4300
        links = db.scalars(select(JourneyPlace).order_by(JourneyPlace.id)).all()
        assert [link.place_id for link in links] == [first_id, second_id]
        assert links[0].note == "人很多但很震撼"

    page = client.get("/travel?tab=journey")
    assert "京都赏樱 4 日" in page.text
    assert "开心" in page.text
    assert "¥4300" in page.text
    assert "清水寺" not in page.text
    assert 'data-journal-year="2026"' in page.text
    assert f'data-journey-book-url="/travel/journeys/{journey_id}/book"' in page.text

    listing = client.get("/travel/journeys/list")
    assert listing.status_code == 200
    assert "京都赏樱 4 日" in listing.text

    detail = client.get(f"/travel/journeys/{journey_id}")
    assert detail.status_code == 200
    assert "清水寺" in detail.text
    assert "排队 40 分钟" in detail.text
    assert "路费" in detail.text
    assert "¥4300" in detail.text

    book = client.get(f"/travel/journeys/{journey_id}/book")
    assert book.status_code == 200
    assert "清水寺" in book.text
    assert "排队 40 分钟" in book.text
    assert "¥4300" in book.text

    stats = client.get("/api/v1/dashboard/stats").json()["data"]
    assert stats["travel"]["stats"]["journeys"] == 1
    assert stats["travel"]["stats"]["journey_want"] == 0
    assert stats["travel"]["stats"]["journey_visited"] == 1
    assert stats["travel"]["stats"]["cost_total"] == 4300
    assert stats["travel"]["journeys"][0]["title"] == "京都赏樱 4 日"
    assert stats["travel"]["journeys"][0]["status"] == "visited"

    dashboard = client.get("/")
    assert "趟旅程" in dashboard.text


def test_journey_edit_sync_links_and_delete(client):
    first_id = _create_place(client, "清水寺")
    second_id = _create_place(client, "金阁寺")
    client.post(
        "/travel/journeys/new",
        data={
            "title": "京都初访",
            "mood": "normal",
            "place_ids": str(first_id),
            f"place_note_{first_id}": "旧备注",
        },
    )
    with SessionLocal() as db:
        journey_id = db.scalars(select(Journey)).one().id

    edited = client.post(
        f"/travel/journeys/{journey_id}/edit",
        data={
            "title": "京都二刷",
            "mood": "wow",
            "place_ids": str(second_id),
            f"place_note_{second_id}": "金光闪闪",
        },
    )
    assert edited.status_code == 200
    with SessionLocal() as db:
        journey = db.get(Journey, journey_id)
        assert journey.title == "京都二刷"
        assert journey.mood == "wow"
        links = db.scalars(select(JourneyPlace)).all()
        assert [link.place_id for link in links] == [second_id]
        assert links[0].note == "金光闪闪"

    deleted = client.post(f"/travel/journeys/{journey_id}/delete")
    assert deleted.status_code == 200
    assert deleted.headers.get("HX-Redirect") == "/travel?tab=journey"
    with SessionLocal() as db:
        assert db.get(Journey, journey_id) is None
        assert db.scalars(select(JourneyPlace)).all() == []


def test_add_place_to_journey_upsert_note(client):
    place_id = _create_place(client, "伏见稻荷")
    client.post("/travel/journeys/new", data={"title": "京都", "mood": "normal"})
    with SessionLocal() as db:
        journey_id = db.scalars(select(Journey)).one().id

    form = client.get(f"/travel/places/{place_id}/add-to-journey")
    assert form.status_code == 200
    assert "京都" in form.text

    added = client.post(
        f"/travel/places/{place_id}/journeys",
        data={"journey_id": str(journey_id), "note": "千本鸟居"},
    )
    assert added.status_code == 200
    assert added.headers.get("HX-Trigger")
    again = client.post(
        f"/travel/places/{place_id}/journeys",
        data={"journey_id": str(journey_id), "note": "傍晚更美"},
    )
    assert again.status_code == 200
    with SessionLocal() as db:
        links = db.scalars(select(JourneyPlace)).all()
        assert len(links) == 1
        assert links[0].note == "傍晚更美"


def test_place_edit_form_is_optional_extras_only(client):
    created = client.post(
        "/travel/places/poi",
        data={
            "name": "伏见稻荷大社",
            "standard_address": "京都府京都市伏见区",
            "lng": "135.772700",
            "lat": "34.967100",
            "amap_poi_id": "B0FORM",
            "amap_type": "风景名胜;寺庙道观",
        },
    )
    place_id = created.json()["place"]["id"]

    form = client.get(f"/travel/places/{place_id}/edit")
    assert form.status_code == 200
    assert "star-input" in form.text
    assert "伏见稻荷大社" in form.text
    assert "data-amap-search" not in form.text
    assert 'name="standard_address"' not in form.text
    assert 'name="modal_scope"' not in form.text
    assert "到访日期" not in form.text

    bad_url = client.post(
        f"/travel/places/{place_id}/edit",
        data={"source_note_url": "javascript:alert(1)"},
    )
    assert bad_url.status_code == 200
    assert "alert-error" in bad_url.text


def test_weekly_review_fallback(client):
    response = client.post("/api/v1/dashboard/review")
    assert response.status_code == 200
    review = response.json()["data"]
    assert review["source"] == "fallback"
    assert review["content"]
    assert review["week_start"]


def test_news_digest_without_items(client):
    response = client.post("/api/v1/news/digest")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_mcp_status_and_disabled_start(client):
    status = client.get("/api/v1/mcp/status")
    assert status.status_code == 200
    data = status.json()["data"]
    assert data["mode"] == "stdio"
    names = {server["name"] for server in data["servers"]}
    assert "zotero" in names

    start = client.post("/api/v1/mcp/zotero/start")
    assert start.status_code == 400
    assert "未启用" in start.json()["message"]
