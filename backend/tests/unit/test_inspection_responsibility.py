from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from app.core.exceptions import AppError
from app.modules.academic.models import AdministrativeClass, Semester, Student
from app.modules.inspection.models import InspectionTask, TaskRosterMember
from app.modules.inspection.responsibility import InspectionResponsibility, sync_responsibility
from app.modules.organization.models import College
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def setup(campus):
    _, db, _, _, a, b = campus
    semester = Semester(
        code="2026-F",
        name="秋季",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 31),
        first_monday=date(2026, 8, 31),
        total_weeks=22,
    )
    administrative = AdministrativeClass(
        college_id=int(a["id"]), class_code="A1", class_name="甲班"
    )
    db.add_all([semester, administrative])
    db.flush()
    students = [
        Student(student_no=str(n), name="fixture", administrative_class_id=administrative.id)
        for n in (1, 2)
    ]
    db.add_all(students)
    db.commit()
    return db, semester.id, int(a["id"]), int(b["id"]), [s.id for s in students]


def create_task(db, sid, cid, key, students):
    db.scalar(select(College.id).where(College.id == cid).with_for_update())
    task = InspectionTask(
        college_id=cid,
        task_key=key,
        semester_id=sid,
        inspection_date=date(2026, 11, 2),
        week_no=10,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        occurrence_keys_snapshot=["shared-meeting|2026-11-02"],
        expected_count_snapshot=len(students),
        expected_count_current=len(students),
        roster_version=1,
        lock_version=1,
    )
    db.add(task)
    db.flush()
    db.add_all(
        [
            TaskRosterMember(
                task_id=task.id, roster_version=1, student_id=s, student_no=str(s), name="fixture"
            )
            for s in students
        ]
    )
    db.flush()
    sync_responsibility(db, task)
    return task


def test_disjoint_targets_and_different_colleges_are_independent(campus):
    db, sid, a, b, students = setup(campus)
    create_task(db, sid, a, "one", [students[0]])
    create_task(db, sid, a, "disjoint", [students[1]])
    create_task(db, sid, b, "other-college", students)
    db.commit()
    with pytest.raises(AppError) as error:
        create_task(db, sid, a, "overlap", list(reversed(students)))
    assert (
        error.value.http_status == 409
        and error.value.field_errors["conflicting_student_count"] == 2
    )
    db.rollback()
    assert len(list(db.scalars(select(InspectionResponsibility)))) == 4


def test_mysql_concurrent_overlapping_rosters_only_one_writer_commits(campus):
    db, sid, a, _, students = setup(campus)
    if db.get_bind().dialect.name != "mysql":
        pytest.skip("requires server MySQL")
    barrier = Barrier(2)
    engine = db.get_bind()
    db.commit()

    def write(number):
        with Session(engine, expire_on_commit=False) as writer:
            barrier.wait(timeout=10)
            try:
                create_task(writer, sid, a, f"writer-{number}", students)
                writer.commit()
                return "created"
            except AppError as exc:
                writer.rollback()
                assert exc.http_status == 409
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(write, (1, 2)))
    assert sorted(results) == ["conflict", "created"]
    assert len(list(db.scalars(select(InspectionResponsibility)))) == 2
