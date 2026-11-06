"""核心接口与页面可用性测试。"""

import json


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

    page = client.get("/travel")
    assert "测试地点" in page.text

    deleted = client.delete(f"/api/v1/places/{place_id}")
    assert deleted.status_code == 200


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
