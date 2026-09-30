"""校历来源教学日与排班周上限的集成回归；需隔离 MySQL 测试库。"""

from __future__ import annotations

import threading
from datetime import date, timedelta

import pytest
from app.core.config import get_settings
from app.core.permissions import RoleCode
from app.modules.academic.models import Semester
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.scheduling.loader import load_snapshot
from app.modules.inspection.service import InspectionService
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .test_inspection_assignment import (
    _ACA,
    _AUTO,
    _TASKS,
    _admin_headers,
    _assign_worker,
    _create_admin_class,
    _create_course,
    _create_tc,
    _enroll,
    _make_user,
    _make_volunteer,
    _one_task_scene,
    _post,
    _schedule,
)

pytestmark = pytest.mark.integration


def _clone_task(session: Session, source: InspectionTask, day: date, key: str) -> InspectionTask:
    clone = InspectionTask(
        task_key=key,
        semester_id=source.semester_id,
        inspection_date=day,
        week_no=(day - date(2026, 9, 7)).days // 7 + 1,
        inspection_type="COURSE",
        start_period=source.start_period,
        end_period=source.end_period,
        roster_version=1,
        expected_count_snapshot=0,
        expected_count_current=0,
        require_photo_snapshot=False,
    )
    session.add(clone)
    session.commit()
    return clone


def test_makeup_source_week_and_weekday_change_loader_and_manual_conflict(
    client: TestClient, session: Session,
) -> None:
    h = _admin_headers(client, session)
    scene = _one_task_scene(client, h)
    other_class = _create_admin_class(client, h, "VOL-CALENDAR")
    vol = _make_volunteer(
        client, h, session, sem_id=scene["sem_id"], username="cal-vol",
        student_no="CAL-VOL", admin_class_id=other_class,
    )
    assert vol.student_id is not None
    student_id = vol.student_id
    # 志愿者仅在教学第 3 周周五 1-2 节有课，实际 9 月 20 日为第 2 周周日。
    course = _create_course(client, h, "CAL-COURSE")
    own_tc = _create_tc(client, h, scene["sem_id"], course, "CAL-TC")
    _enroll(client, h, own_tc, [student_id])
    _schedule(client, h, own_tc, 1, 2, "CAL-ROOM", weeks=[3], weekday=5)
    source = session.get(InspectionTask, int(scene["task"]["id"]))
    assert source is not None
    task = _clone_task(session, source, date(2026, 9, 20), "calendar:makeup")
    semester = session.get(Semester, scene["sem_id"])
    assert semester is not None
    assert load_snapshot(session, semester, [task], [vol.id]).tasks[0].candidates == {vol.id}
    assert not InspectionService(session)._own_class_conflict(student_id, semester, task)
    # _own_class_conflict 使用锁定读；释放缺失 override 的键间隙锁后再由 HTTP 写入。
    session.commit()

    created = _post(
        client, h, f"{_ACA}/semesters/{scene['sem_id']}/calendar-overrides",
        {"date": "2026-09-20", "override_type": "MAKEUP",
         "source_teaching_week": 3, "source_teaching_weekday": 5},
    )
    assert created["source_teaching_week"] == 3
    # 首次快照已在本 Session 建立 RR 视图；重启只读事务以观察另一个请求的提交。
    session.rollback()
    session.expire_all()
    assert load_snapshot(session, semester, [task], [vol.id]).tasks[0].candidates == frozenset()
    assert InspectionService(session)._own_class_conflict(student_id, semester, task)


def test_three_existing_dates_reject_fourth_auto_and_manual_next_week_allowed(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _admin_headers(client, session)
    scene = _one_task_scene(client, h)
    other_class = _create_admin_class(client, h, "VOL-CAP")
    vol = _make_volunteer(
        client, h, session, sem_id=scene["sem_id"], username="cap-week",
        student_no="CAP-WEEK", admin_class_id=other_class,
    )
    source = session.get(InspectionTask, int(scene["task"]["id"]))
    assert source is not None
    tasks = [source] + [
        _clone_task(session, source, date(2026, 9, 7) + timedelta(days=i), f"week-cap:{i}")
        for i in (1, 2, 3, 7)
    ]
    monkeypatch.setenv("ASSIGNMENT_MAX_TASKS_PER_WEEK", "3")
    get_settings.cache_clear()
    try:
        for task in tasks[:3]:
            response = client.put(
                f"{_TASKS}/{task.id}/assignment", headers=h,
                json={"volunteer_user_id": vol.id, "lock_version": 0},
            )
            assert response.status_code == 200, response.text
        fourth = tasks[3]
        auto = client.post(
            _AUTO, headers=h,
            json={"semester_id": scene["sem_id"], "task_ids": [fourth.id],
                  "candidate_user_ids": [vol.id]},
        )
        assert auto.status_code == 200, auto.text
        assert auto.json()["data"]["assigned_count"] == 0
        assert auto.json()["data"]["unassigned"][0]["reason_code"] == "WEEK_CAP_EXCEEDED"
        manual = client.put(
            f"{_TASKS}/{fourth.id}/assignment", headers=h,
            json={"volunteer_user_id": vol.id, "lock_version": 0},
        )
        assert manual.status_code == 422, manual.text
        assert manual.json()["fieldErrors"]["reason_code"] == "WEEK_CAP_EXCEEDED"
        next_week = client.put(
            f"{_TASKS}/{tasks[4].id}/assignment", headers=h,
            json={"volunteer_user_id": vol.id, "lock_version": 0},
        )
        assert next_week.status_code == 200, next_week.text
    finally:
        get_settings.cache_clear()


def test_concurrent_manual_requests_compete_for_last_week_slot(
    client: TestClient, session: Session, engine: Engine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _admin_headers(client, session)
    scene = _one_task_scene(client, h)
    other_class = _create_admin_class(client, h, "VOL-RACE")
    vol = _make_volunteer(
        client, h, session, sem_id=scene["sem_id"], username="race-week",
        student_no="RACE-WEEK", admin_class_id=other_class,
    )
    source = session.get(InspectionTask, int(scene["task"]["id"]))
    assert source is not None
    tasks = [source] + [
        _clone_task(session, source, date(2026, 9, 7) + timedelta(days=i), f"week-race:{i}")
        for i in (1, 2, 3)
    ]
    monkeypatch.setenv("ASSIGNMENT_MAX_TASKS_PER_WEEK", "3")
    get_settings.cache_clear()
    try:
        for task in tasks[:2]:
            response = client.put(
                f"{_TASKS}/{task.id}/assignment", headers=h,
                json={"volunteer_user_id": vol.id, "lock_version": 0},
            )
            assert response.status_code == 200, response.text
        admin = session.execute(
            select(UserAccount).where(UserAccount.username == "admin")
        ).scalar_one()
        second_admin = _make_user(session, "admin-race-2", [RoleCode.SUPER_ADMIN.value])
        actor_ids = [admin.id, second_admin.id]
        task_ids = [task.id for task in tasks[2:]]
        session.commit()  # 释放夹具会话快照与读锁，供独立连接竞争。
        barrier = threading.Barrier(2)
        out: dict[int, object] = {}
        workers = [
            threading.Thread(
                target=_assign_worker,
                args=(engine, actor_ids[i], task_id, vol.id, 0, barrier, out, i),
            )
            for i, task_id in enumerate(task_ids)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        assert not any(worker.is_alive() for worker in workers), out
        assert len(out) == 2, out
        assert sum(result == ("ok",) for result in out.values()) == 1, out
        session.rollback()
        committed = session.scalars(
            select(InspectionAssignment)
            .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
            .where(InspectionAssignment.volunteer_user_id == vol.id,
                   InspectionTask.semester_id == scene["sem_id"])
        ).all()
        assert len(committed) == 3, out
        assert len({row.task_id for row in committed if row.task_id in task_ids}) == 1
    finally:
        get_settings.cache_clear()


def test_loader_batch_query_count_includes_calendar_lookup(
    client: TestClient, session: Session,
) -> None:
    h = _admin_headers(client, session)
    scene = _one_task_scene(client, h)
    other_class = _create_admin_class(client, h, "VOL-QUERY")
    volunteers = [
        _make_volunteer(
            client, h, session, sem_id=scene["sem_id"], username=f"query-{i}",
            student_no=f"QUERY-{i}", admin_class_id=other_class,
        ) for i in range(3)
    ]
    source = session.get(InspectionTask, int(scene["task"]["id"]))
    assert source is not None
    targets = [source] + [
        _clone_task(session, source, date(2026, 9, 7) + timedelta(days=i), f"query:{i}")
        for i in range(1, 6)
    ]
    _post(
        client, h, f"{_ACA}/semesters/{scene['sem_id']}/calendar-overrides",
        {"date": "2026-09-10", "override_type": "MAKEUP",
         "source_teaching_week": 2, "source_teaching_weekday": 5},
    )
    semester = session.get(Semester, scene["sem_id"])
    assert semester is not None
    statements: list[str] = []

    def record_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    assert session.bind is not None
    event.listen(session.bind, "before_cursor_execute", record_sql)
    try:
        load_snapshot(session, semester, targets[:1], [v.id for v in volunteers[:1]])
        single = len(statements)
        statements.clear()
        load_snapshot(session, semester, targets, [v.id for v in volunteers])
        assert len(statements) == single
        assert single <= 10
        assert sum("calendar_override" in sql.lower() for sql in statements) == 1
    finally:
        event.remove(session.bind, "before_cursor_execute", record_sql)
