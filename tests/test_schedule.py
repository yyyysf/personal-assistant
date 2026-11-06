"""日程时间模块：同源任务、标签颜色、日视图、计时与统计。"""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from src.core.db import SessionLocal
from src.core.time_utils import today
from src.models import Tag, Task


def _create_schedule_task(client, **overrides) -> int:
    payload = {
        "title": "阅读论文",
        "tags": "科研",
        "description": "",
        "date_mode": "single",
        "due_date": "",
        "planned_date": today().isoformat(),
        "range_start": "",
        "range_end": "",
        "start_time": "09:00",
        "end_time": "10:30",
    }
    payload.update(overrides)
    response = client.post("/schedule/tasks/new", data=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        task = db.scalar(
            select(Task).where(Task.title == payload["title"]).order_by(Task.id.desc())
        )
        assert task is not None
        return task.id


def _create_todo_task(client, **overrides) -> int:
    payload = {
        "title": "任务页任务",
        "priority": "medium",
        "tags": "看板",
        "date_mode": "single",
        "due_date": "",
        "planned_date": today().isoformat(),
        "range_start": "",
        "range_end": "",
        "progress": 0,
        "status": "todo",
        "description": "",
    }
    payload.update(overrides)
    response = client.post("/todo/tasks/new", data=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        task = db.scalar(
            select(Task).where(Task.title == payload["title"]).order_by(Task.id.desc())
        )
        assert task is not None
        return task.id


def test_schedule_pages_and_navigation(client):
    for path in (
        "/schedule",
        "/schedule/content?tab=timeline",
        "/schedule/content?tab=timer",
        "/schedule/content?tab=stats",
    ):
        response = client.get(path)
        assert response.status_code == 200, path

    page = client.get("/schedule")
    assert "日程时间" in page.text
    assert "时间轴日历" in page.text
    assert "专注计时台" in page.text
    assert "时间统计看板" in page.text
    assert "项目管理" not in page.text
    assert "Due Days" not in page.text
    assert "Memos" not in page.text


def test_schedule_task_syncs_to_todo_and_tag_color(client):
    task_id = _create_schedule_task(client, title="跨页面同步任务", tags="科研")

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        assert task.tags == "科研"
        tags = {tag.name: tag.color for tag in db.scalars(select(Tag)).all()}
        assert "科研" in tags
        color = tags["科研"]

    content = client.get("/schedule/content?tab=timeline").text
    assert "跨页面同步任务" in content
    assert color in content

    todo = client.get("/todo").text
    assert "跨页面同步任务" in todo
    assert color in todo


def test_todo_task_syncs_to_schedule_timeline(client):
    _create_todo_task(client, title="从任务页创建")

    content = client.get("/schedule/content?tab=timeline").text
    assert "从任务页创建" in content

    day = client.get(f"/schedule/content?tab=timeline&view=day&date={today().isoformat()}").text
    assert "从任务页创建" in day


def test_day_view_uses_three_seven_layout(client):
    _create_schedule_task(client, title="日视图任务")

    content = client.get(f"/schedule/content?tab=timeline&view=day&date={today().isoformat()}").text
    assert "schedule-layout is-day" in content
    assert "day-detail" in content
    assert "日视图任务" in content


def test_cross_midnight_task_rolls_to_next_day(client):
    _create_schedule_task(
        client,
        title="深夜任务",
        planned_date="2026-11-02",
        start_time="23:00",
        end_time="01:00",
    )
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.title == "深夜任务"))
        assert task.start_at == datetime(2026, 11, 2, 23, 0)
        assert task.end_at == datetime(2026, 11, 3, 1, 0)


def test_invalid_range_dates_rejected(client):
    response = client.post(
        "/schedule/tasks/new",
        data={
            "title": "错误区间",
            "tags": "",
            "description": "",
            "date_mode": "range",
            "due_date": "",
            "planned_date": "",
            "range_start": "2026-11-10",
            "range_end": "2026-11-01",
            "start_time": "",
            "end_time": "",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Retarget") == "#modal-body"
    assert "结束日期不能早于开始日期" in response.text
    with SessionLocal() as db:
        assert db.scalar(select(Task).where(Task.title == "错误区间")) is None


def test_timer_finish_temp_task_and_idempotency(client):
    payload = {
        "title": "临时专注",
        "tags": "专注",
        "started_at": "2026-11-02T09:00:00",
        "ended_at": "2026-11-02T09:30:00",
        "duration_seconds": 1800,
        "description": "整理数据",
        "client_token": "token-temp-1",
    }
    first = client.post("/schedule/timer/finish", json=payload)
    assert first.status_code == 200
    record_id = first.json()["data"]["id"]

    with SessionLocal() as db:
        record = db.get(Task, record_id)
        assert record.status == "done"
        assert record.duration_seconds == 1800
        assert record.planned_date == date(2026, 11, 2)
        assert record.tags == "专注"

    duplicate = client.post("/schedule/timer/finish", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["id"] == record_id
    with SessionLocal() as db:
        assert db.scalar(select(Task).where(Task.client_token == "token-temp-1")) is not None

    records = client.get("/schedule/timer/records")
    assert "临时专注" in records.text
    assert "0:30" in records.text


def test_timer_finish_planned_task_updates_original(client):
    task_id = _create_schedule_task(client, title="计划任务")
    finished = client.post(
        "/schedule/timer/finish",
        json={
            "task_id": task_id,
            "started_at": "2026-11-02T14:00:00",
            "ended_at": "2026-11-02T15:00:00",
            "duration_seconds": 3600,
            "client_token": "token-plan-1",
        },
    )
    assert finished.status_code == 200
    assert finished.json()["data"]["id"] == task_id

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        assert task.status == "done"
        assert task.completed_at is not None
        assert task.duration_seconds == 3600

    again = client.post(
        "/schedule/timer/finish",
        json={
            "task_id": task_id,
            "started_at": "2026-11-02T14:00:00",
            "ended_at": "2026-11-02T15:00:00",
            "client_token": "token-plan-2",
        },
    )
    assert again.status_code == 409


def test_record_edit_recalculates_duration_and_delete(client):
    created = client.post(
        "/schedule/timer/finish",
        json={
            "title": "可编辑记录",
            "started_at": "2026-11-02T08:00:00",
            "ended_at": "2026-11-02T09:00:00",
            "duration_seconds": 3600,
        },
    )
    record_id = created.json()["data"]["id"]

    updated = client.post(
        f"/schedule/records/{record_id}/edit",
        data={
            "title": "改后的记录",
            "tags": "复盘",
            "date": "2026-11-02",
            "start_time": "10:00",
            "end_time": "11:15",
            "description": "重新计时",
        },
    )
    assert updated.status_code == 200
    with SessionLocal() as db:
        record = db.get(Task, record_id)
        assert record.title == "改后的记录"
        assert record.duration_seconds == 4500
        assert record.tags == "复盘"

    deleted = client.post(f"/schedule/records/{record_id}/delete")
    assert deleted.status_code == 200
    with SessionLocal() as db:
        assert db.get(Task, record_id) is None


def test_standalone_tag_selectable_in_task_forms(client):
    created = client.post("/todo/tags/new", data={"name": "新建未用标签"})
    assert created.status_code == 200

    with SessionLocal() as db:
        tag = db.scalar(select(Tag).where(Tag.name == "新建未用标签"))
        assert tag is not None and tag.color

    for path in ("/schedule/tasks/new", "/todo/tasks/new"):
        form = client.get(path)
        assert form.status_code == 200, path
        assert "新建未用标签" in form.text, path


def test_tag_rename_and_recolor_sync_tasks(client):
    _create_todo_task(client, title="待重命名", tags="旧标签")
    with SessionLocal() as db:
        tag = db.scalar(select(Tag).where(Tag.name == "旧标签"))
        tag_id = tag.id

    renamed = client.post(f"/todo/tags/{tag_id}/rename", data={"name": "新标签"})
    assert renamed.status_code == 200
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.title == "待重命名"))
        assert task.tags == "新标签"
        assert db.get(Tag, tag_id).name == "新标签"

    recolored = client.post(f"/todo/tags/{tag_id}/recolor", data={"color": "#F4A8A8"})
    assert recolored.status_code == 200
    with SessionLocal() as db:
        assert db.get(Tag, tag_id).color == "#f4a8a8"


def test_stats_aggregation_and_escaping(client):
    tag_name = "<script>alert(1)</script>"
    created = client.post(
        "/schedule/timer/finish",
        json={
            "title": "统计任务",
            "tags": tag_name,
            "started_at": f"{today().isoformat()}T09:00:00",
            "ended_at": f"{today().isoformat()}T11:00:00",
            "duration_seconds": 7200,
        },
    )
    assert created.status_code == 200

    content = client.get("/schedule/content?tab=stats").text
    assert "统计任务" not in content
    assert "2.0 h" in content
    assert tag_name not in content
    assert "&lt;script&gt;" in content
    assert 'id="schedule-stats-data"' in content

    filtered = client.get(
        "/schedule/content",
        params={"tab": "stats", "range": "week", "tag": tag_name},
    ).text
    assert "2.0 h" in filtered


def test_goal_entries_removed(client):
    todo = client.get("/todo").text
    assert "目标管理" not in todo
    assert "新增目标" not in todo
    assert "关联目标" not in todo
    schedule = client.get("/schedule").text
    assert "项目管理" not in schedule


def test_todo_filter_uses_tag_dropdown(client):
    _create_todo_task(client, title="筛选任务", tags="下拉筛选")
    page = client.get("/todo").text
    assert "tag-filter-panel" in page
    assert "tag-filter-trigger" in page
    assert '<select name="tag"' not in page


def test_board_cards_are_minimal_and_draggable(client):
    task_id = _create_todo_task(
        client,
        title="极简卡片任务",
        tags="看板",
        description="这段说明只应该在详情里出现",
    )
    page = client.get("/todo").text
    assert "极简卡片任务" in page
    assert "这段说明只应该在详情里出现" not in page
    assert 'draggable="true"' in page
    assert f'data-task-id="{task_id}"' in page

    moved = client.post(f"/todo/tasks/{task_id}/status", data={"status": "doing"})
    assert moved.status_code == 200
    with SessionLocal() as db:
        assert db.get(Task, task_id).status == "doing"

    detail = client.get(f"/todo/tasks/{task_id}/detail").text
    assert "这段说明只应该在详情里出现" in detail
    assert "进度" not in detail


def test_board_card_shows_single_tag(client):
    task_id = _create_todo_task(client, title="单标签卡片", tags="甲,乙")

    with SessionLocal() as db:
        assert db.get(Task, task_id).tags == "甲"

    page = client.get("/todo").text
    assert "单标签卡片" in page
    assert "task-head" in page
    assert ">甲</span>" in page
    assert "乙" not in page.split("单标签卡片")[1].split("</article>")[0]


def test_task_form_is_simplified_with_calendar(client):
    form = client.get("/todo/tasks/new").text
    assert 'name="title"' in form
    assert 'name="tags"' in form
    assert 'name="date_mode"' in form
    assert "calendar-field" in form
    assert 'name="priority"' not in form
    assert 'name="status"' not in form
    assert 'name="progress"' not in form


def test_frontend_assets_load_locally_in_order(client):
    page = client.get("/todo").text
    assert "/static/js/vendor/alpine.min.js" in page
    assert "/static/js/vendor/htmx.min.js" in page
    assert "cdn.jsdelivr.net" not in page
    assert page.index("components.js") < page.index("vendor/alpine.min.js")
    for path in (
        "/static/js/vendor/alpine.min.js",
        "/static/js/vendor/htmx.min.js",
        "/static/js/vendor/chart.umd.js",
    ):
        assert client.get(path).status_code == 200, path


def test_timer_lists_all_open_tasks(client):
    _create_todo_task(client, title="待计时任务", tags="计时")
    with SessionLocal() as db:
        db.add(Task(title="无日期待办", status="todo"))
        db.commit()

    timer = client.get("/schedule/content?tab=timer").text
    assert "待计时任务" in timer
    assert "无日期待办" in timer

    with SessionLocal() as db:
        done = Task(title="已完成不显示", status="done")
        db.add(done)
        db.commit()
    timer = client.get("/schedule/content?tab=timer").text
    assert "已完成不显示" not in timer


def test_schedule_and_todo_share_same_task_record(client):
    _create_todo_task(client, title="同源记录", tags="共享")
    with SessionLocal() as db:
        count = len(db.scalars(select(Task).where(Task.title == "同源记录")).all())
        assert count == 1

    response = client.get("/todo")
    assert "同源记录" in response.text
    timeline = client.get("/schedule/content?tab=timeline").text
    assert "同源记录" in timeline

    ranged = client.post(
        "/todo/tasks/new",
        data={
            "title": "区间任务",
            "priority": "low",
            "tags": "共享",
            "date_mode": "range",
            "due_date": "",
            "planned_date": "",
            "range_start": today().isoformat(),
            "range_end": (today() + timedelta(days=2)).isoformat(),
            "progress": 0,
            "status": "todo",
            "description": "",
        },
    )
    assert ranged.status_code == 200
    timeline = client.get("/schedule/content?tab=timeline").text
    assert "区间任务" in timeline
