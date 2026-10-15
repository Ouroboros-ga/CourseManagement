import pytest
from app.core.database import utcnow
from app.core.exceptions import ConflictError
from app.modules.academic.archive import SemesterArchiveService
from app.modules.attendance.schemas import AttendanceCorrectionRequest
from app.modules.attendance.scoped_service import ScopedAttendanceService
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserRole
from app.modules.inspection.models import InspectionSubmission, InspectionTask, TaskRosterMember
from app.modules.report.campus_dimensions import CampusDimensionsService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_attendance import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_explicit_archive_and_teacher_correction_preserve_independent_college_results(campus):
    db, teacher, a, b, own, foreign = prepare(campus)
    admin = campus[2]
    tasks = list(db.scalars(select(InspectionTask)))
    sid = tasks[0].semester_id
    archive = SemesterArchiveService(db, admin, sid)
    request = {"reason": "学期业务已结算"}
    unfinished = archive.preview(request)
    assert not unfinished["can_archive"] and unfinished["blockers"]["unfinished_task_ids"]
    with pytest.raises(ConflictError):
        archive.confirm({**request, "revision": unfinished["revision"]})
    foreign.student_id = own.student_id
    for task in tasks:
        task.occurrence_keys_snapshot = ["confirmed-shared-meeting|2026-09-07"]
        db.add(
            InspectionSubmission(
                task_id=task.id,
                attempt_no=1,
                volunteer_user_id=admin.id,
                roster_version=task.roster_version,
                result="NORMAL",
                review_status="APPROVED",
                submitted_at=utcnow(),
            )
        )
        db.add(
            TaskRosterMember(
                task_id=task.id,
                roster_version=task.roster_version,
                student_id=own.student_id,
                student_no="fixture",
                name="fixture",
                college_id_snapshot=int(a["id"]),
            )
        )
    role = Role(code="TEACHER_ADMIN", name="教师")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=teacher.id, role_id=role.id))
    db.commit()
    summary = CampusDimensionsService(db, admin, sid).summary()
    assert summary["check_person_times"] == 2 and summary["distinct_student_count"] == 1
    assert summary["distinct_student_occurrence_count"] == 1
    assert {d["responsible_college_id"] for d in summary["dimensions"]} == {a["id"], b["id"]}
    ready = archive.preview(request)
    assert ready["can_archive"]
    archive.confirm({**request, "revision": ready["revision"]})
    service = ScopedAttendanceService(db, teacher, int(a["id"]))
    correction = AttendanceCorrectionRequest(
        current_version=1, attendance_type="NORMAL", reason="按已核实证明更正"
    )
    with pytest.raises(ConflictError, match="归档"):
        service.correct(teacher, own.id, correction, None)
    result = service.correct_archived(teacher, own.id, correction)
    assert result.effective_type == "NORMAL" and result.current_version == 2
    assert result.task.responsible_college_id == a["id"]
    assert foreign.effective_type == "ABSENT"
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "attendance.archived.correct"))
