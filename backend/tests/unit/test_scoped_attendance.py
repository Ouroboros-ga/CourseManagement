"""院级考勤的列表、计数、详情、版本和更正必须共享范围谓词。"""

import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord
from app.modules.attendance.schemas import AttendanceCorrectionRequest
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def attendance_fixture():
    yield from campus_fixture.__wrapped__()


def prepare(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, schedule, student, other = records(db, a, b)
    task_a = db.scalar(select(InspectionTask).where(InspectionTask.college_id == int(a["id"])))
    task_b = InspectionTask(
        task_key="OTHER",
        semester_id=teaching.semester_id,
        inspection_date=task_a.inspection_date,
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        college_id=int(b["id"]),
    )
    db.add(task_b)
    db.flush()
    own = AttendanceRecord(
        task_id=task_a.id, student_id=student.id, effective_type="LATE", current_version=1
    )
    foreign = AttendanceRecord(
        task_id=task_b.id, student_id=other.id, effective_type="ABSENT", current_version=1
    )
    db.add_all([own, foreign])
    db.commit()
    grant(config, admin, teacher, a, ["attendance.read", "attendance.correct"])
    grant(config, admin, teacher, b, ["attendance.read"])
    return db, teacher, a, b, own, foreign


def service(db, actor, cid):
    from app.modules.attendance.scoped_service import ScopedAttendanceService

    return ScopedAttendanceService(db, actor, int(cid))


def test_scoped_count_cached_foreign_detail_and_foreign_correction(campus):
    db, teacher, a, b, own, foreign = prepare(campus)
    scoped = service(db, teacher, a["id"])
    result = scoped.list_attendance(
        teacher, PageParams(1, 20), task_id=None, semester_id=None, effective_type=None
    )
    assert result["total"] == 1 and result["items"][0]["id"] == str(own.id)
    with pytest.raises(NotFoundError):
        scoped.get_attendance(teacher, foreign.id)
    with pytest.raises(NotFoundError):
        scoped.list_versions(teacher, foreign.id)
    with pytest.raises(NotFoundError):
        scoped.correct(
            teacher,
            foreign.id,
            AttendanceCorrectionRequest(current_version=1, attendance_type="NORMAL"),
            None,
        )
    with pytest.raises(PermissionDeniedError):
        service(db, teacher, b["id"]).correct(
            teacher,
            foreign.id,
            AttendanceCorrectionRequest(current_version=1, attendance_type="NORMAL"),
            None,
        )
    assert db.get(AttendanceRecord, foreign.id).effective_type == "ABSENT"


def test_old_manage_entry_is_closed_but_own_read_remains(campus, monkeypatch):
    from app.core.config import get_settings
    from app.modules.attendance.service import AttendanceService

    db, teacher, a, b, own, _ = prepare(campus)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    legacy = AttendanceService(db)
    # 数据库真实授权由 scoped 服务验证；旧方法不能借角色走全校旁路。
    monkeypatch.setattr(legacy, "_require", lambda *_: None)
    with pytest.raises(PermissionDeniedError):
        legacy.list_attendance(
            teacher, PageParams(1, 20), task_id=None, semester_id=None, effective_type=None
        )
    with pytest.raises(NotFoundError):
        legacy.get_attendance(teacher, own.id)


def test_scoped_correction_retains_version_transaction_and_revocation(campus, monkeypatch):
    from app.core.exceptions import ConflictError
    from app.modules.attendance.models import AttendanceRecordVersion
    from app.modules.organization.models import ScopedGrant
    from app.modules.report.source_revision import SourceRevisionService

    config, _, admin, teacher, a, _ = campus
    db, _, _, _, own, _ = prepare(campus)
    # 正式源修订使用 MySQL upsert；这里只验证调用及同一 Session，实际锁语义留给独立 MySQL。
    bumps = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append((session, tid))
    )
    scoped = service(db, teacher, a["id"])
    saved = scoped.correct(
        teacher,
        own.id,
        AttendanceCorrectionRequest(current_version=1, attendance_type="NORMAL"),
        None,
    )
    assert saved.current_version == 2 and saved.effective_type == "NORMAL"
    assert bumps == [(db, own.task_id)]
    assert (
        db.scalar(
            select(AttendanceRecordVersion.attendance_type).where(
                AttendanceRecordVersion.attendance_record_id == own.id
            )
        )
        == "NORMAL"
    )
    with pytest.raises(ConflictError):
        scoped.correct(
            teacher,
            own.id,
            AttendanceCorrectionRequest(current_version=1, attendance_type="ABSENT"),
            None,
        )
    delegation = db.scalar(
        select(ScopedGrant).where(
            ScopedGrant.user_id == teacher.id, ScopedGrant.college_id == int(a["id"])
        )
    )
    config.revoke_grant(admin, int(a["id"]), delegation.id, delegation.lock_version)
    with pytest.raises(NotFoundError):
        scoped.get_attendance(teacher, own.id)
