"""异议与考勤同学院；审核＋改判能力不能从不同学院拼合。"""

import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError
from app.modules.objection.models import Objection
from app.modules.objection.schemas import ObjectionFinalReviewRequest

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_attendance import prepare as attendance_records


@pytest.fixture(name="campus")
def objection_fixture():
    yield from campus_fixture.__wrapped__()


def prepare(campus):
    config, db, admin, teacher, a, b = campus
    db, _, _, _, record, foreign_record = attendance_records(campus)
    one = Objection(
        attendance_record_id=record.id,
        student_id=record.student_id,
        base_attendance_version=1,
        reason="",
        desired_type="NORMAL",
    )
    two = Objection(
        attendance_record_id=foreign_record.id,
        student_id=foreign_record.student_id,
        base_attendance_version=1,
        reason="",
        desired_type="NORMAL",
    )
    db.add_all([one, two])
    db.commit()
    grant(config, admin, teacher, a, ["objection.read", "objection.final_review"])
    grant(config, admin, teacher, b, ["objection.read", "objection.final_review"])
    return db, teacher, a, b, one, two


def service(db, actor, cid):
    from app.modules.objection.scoped_service import ScopedObjectionService

    return ScopedObjectionService(db, actor, int(cid))


def test_foreign_list_count_detail_and_review_are_hidden(campus):
    db, teacher, a, _, one, two = prepare(campus)
    scoped = service(db, teacher, a["id"])
    result = scoped.list_objections(
        teacher,
        PageParams(1, 20),
        attendance_record_id=None,
        final_status=None,
        initial_status=None,
    )
    assert result["total"] == 1 and result["items"][0]["id"] == str(one.id)
    with pytest.raises(NotFoundError):
        scoped.get_objection(teacher, two.id)
    with pytest.raises(NotFoundError):
        scoped.final_review(
            teacher,
            two.id,
            ObjectionFinalReviewRequest(decision="REJECTED", current_version=1),
            None,
        )
    assert two.final_status == "PENDING"


def test_review_permission_includes_correction_only_inside_authorized_college(campus, monkeypatch):
    db, teacher, a, b, one, two = prepare(campus)
    from app.modules.report.source_revision import SourceRevisionService

    revisions = []
    from app.modules.attendance.models import AttendanceRecord

    expected_task_id = db.get(AttendanceRecord, two.attendance_record_id).task_id
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda _, tid: revisions.append(tid)
    )
    service(db, teacher, b["id"]).final_review(
        teacher,
        two.id,
        ObjectionFinalReviewRequest(decision="APPROVED", final_type="NORMAL", current_version=1),
        None,
    )
    assert two.final_status == "APPROVED"
    assert one.final_status == "PENDING"
    assert revisions == [expected_task_id]
    with pytest.raises(NotFoundError):
        service(db, teacher, a["id"]).final_review(
            teacher,
            two.id,
            ObjectionFinalReviewRequest(decision="REJECTED", current_version=2),
            None,
        )
