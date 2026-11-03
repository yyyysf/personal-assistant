"""日程时间模块：时间轴、计时、截止事项、备忘录与统计。"""

from datetime import date, datetime, timedelta

from src.core.db import SessionLocal
from src.core.time_utils import today
from src.models import DueItem, Project, ScheduleMemo, Subproject, TimeTask


def _create_project(client, name: str = "科研", color: str = "#ff375f") -> int:
    response = client.post("/schedule/projects/new", data={"name": name, "color": color})
    assert response.status_code == 200
    with SessionLocal() as db:
        project = db.query(Project).filter(Project.name == name).one()
        return project.id


def _create_task(client, **overrides) -> int:
    payload = {
        "title": "阅读论文",
        "project_id": "",
        "subproject_id": "",
        "new_project_name": "",
        "new_project_color": "#0071e3",
        "new_subproject_name": "",
        "date": today().isoformat(),
        "start_time": "09:00",
        "end_time": "10:30",
        "note": "",
    }
    payload.update(overrides)
    response = client.post("/schedule/tasks/new", data=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        task = (
            db.query(TimeTask)
            .filter(TimeTask.title == payload["title"])
            .order_by(TimeTask.id.desc())
            .first()
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


def test_task_creation_and_timeline(client):
    project_id = _create_project(client, "科研", "#ff375f")
    _create_task(
        client,
        title="读一篇 Agent 论文",
        project_id=str(project_id),
        new_subproject_name="LLM",
    )

    with SessionLocal() as db:
        task = db.query(TimeTask).one()
        assert task.subproject_id is not None
        assert db.get(Subproject, task.subproject_id).name == "LLM"

    content = client.get("/schedule/content?tab=timeline").text
    assert "读一篇 Agent 论文" in content
    assert "#ff375f" in content
    assert "LLM" in content


def test_subproject_must_belong_to_project(client):
    first = _create_project(client, "项目甲", "#0071e3")
    second = _create_project(client, "项目乙", "#34c759")
    _create_task(client, title="乙项目任务", project_id=str(second), new_subproject_name="子项乙")
    with SessionLocal() as db:
        subproject = db.query(Subproject).filter(Subproject.name == "子项乙").one()
        subproject_id = subproject.id

    response = client.post(
        "/schedule/tasks/new",
        data={
            "title": "错误关联",
            "project_id": str(first),
            "subproject_id": str(subproject_id),
            "new_project_name": "",
            "new_project_color": "#0071e3",
            "new_subproject_name": "",
            "date": today().isoformat(),
            "start_time": "09:00",
            "end_time": "10:00",
            "note": "",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Retarget") == "#modal-body"
    assert "子项目不属于所选项目" in response.text
    with SessionLocal() as db:
        assert db.query(TimeTask).filter(TimeTask.title == "错误关联").count() == 0


def test_cross_midnight_task_rolls_to_next_day(client):
    _create_task(
        client,
        title="深夜任务",
        date=date(2026, 11, 2).isoformat(),
        start_time="23:00",
        end_time="01:00",
    )
    with SessionLocal() as db:
        task = db.query(TimeTask).filter(TimeTask.title == "深夜任务").one()
        assert task.start_at == datetime(2026, 11, 2, 23, 0)
        assert task.end_at == datetime(2026, 11, 3, 1, 0)


def test_timer_finish_temp_task_and_idempotency(client):
    payload = {
        "title": "临时专注",
        "started_at": "2026-11-02T09:00:00",
        "ended_at": "2026-11-02T09:30:00",
        "duration_seconds": 1800,
        "note": "整理数据",
        "client_token": "token-temp-1",
    }
    first = client.post("/schedule/timer/finish", json=payload)
    assert first.status_code == 200
    record_id = first.json()["data"]["id"]

    with SessionLocal() as db:
        record = db.get(TimeTask, record_id)
        assert record.is_planned is False
        assert record.duration_seconds == 1800
        assert record.planned_date == date(2026, 11, 2)

    duplicate = client.post("/schedule/timer/finish", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["id"] == record_id
    with SessionLocal() as db:
        assert db.query(TimeTask).count() == 1

    records = client.get("/schedule/timer/records")
    assert "临时专注" in records.text
    assert "0:30" in records.text


def test_timer_finish_planned_task_updates_original(client):
    task_id = _create_task(client, title="计划任务")
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
        task = db.get(TimeTask, task_id)
        assert task.is_planned is False
        assert task.completed_at is not None
        assert task.duration_seconds == 3600
        assert db.query(TimeTask).count() == 1

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
            "project_id": "",
            "date": "2026-11-02",
            "start_time": "10:00",
            "end_time": "11:15",
            "note": "重新计时",
        },
    )
    assert updated.status_code == 200
    with SessionLocal() as db:
        record = db.get(TimeTask, record_id)
        assert record.title == "改后的记录"
        assert record.duration_seconds == 4500

    deleted = client.post(f"/schedule/records/{record_id}/delete")
    assert deleted.status_code == 200
    with SessionLocal() as db:
        assert db.get(TimeTask, record_id) is None


def test_due_countdown_and_memos(client):
    client.post(
        "/schedule/due/new",
        data={"title": "今天截止", "due_date": today().isoformat(), "note": "", "project_id": ""},
    )
    client.post(
        "/schedule/due/new",
        data={
            "title": "十天后截止",
            "due_date": (today() + timedelta(days=10)).isoformat(),
            "note": "",
            "project_id": "",
        },
    )
    content = client.get("/schedule/content?tab=timeline").text
    assert "今天到期" in content
    assert "due-chip--red" in content
    assert "due-chip--yellow" in content

    with SessionLocal() as db:
        due = db.query(DueItem).filter(DueItem.title == "今天截止").one()
        due_id = due.id
    client.post(f"/schedule/due/{due_id}/toggle")
    with SessionLocal() as db:
        assert db.get(DueItem, due_id).done is True

    client.post("/schedule/memos/new", data={"content": "记得预约会议室"})
    with SessionLocal() as db:
        memo = db.query(ScheduleMemo).one()
        memo_id = memo.id
    client.post(f"/schedule/memos/{memo_id}/pin")
    with SessionLocal() as db:
        assert db.get(ScheduleMemo, memo_id).pinned is True
    client.post(f"/schedule/memos/{memo_id}/delete")
    with SessionLocal() as db:
        assert db.query(ScheduleMemo).count() == 0


def test_stats_aggregation_and_escaping(client):
    project_name = "<script>alert(1)</script>"
    project_id = _create_project(client, project_name, "#0071e3")
    created = client.post(
        "/schedule/timer/finish",
        json={
            "title": "统计任务",
            "project_id": project_id,
            "started_at": f"{today().isoformat()}T09:00:00",
            "ended_at": f"{today().isoformat()}T11:00:00",
            "duration_seconds": 7200,
        },
    )
    assert created.status_code == 200

    content = client.get("/schedule/content?tab=stats").text
    assert "统计任务" not in content
    assert "2.0 h" in content
    assert project_name not in content
    assert "&lt;script&gt;" in content
    assert 'id="schedule-stats-data"' in content

    with SessionLocal() as db:
        assert db.query(Project).filter(Project.name == project_name).count() == 1
