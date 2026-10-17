"""班主任/辅导员责任班级异议聚合与一次审核（T05）。

固定口径（docs/development/STAFF_ARCHITECTURE_CONTRACT_20261017.md §2、§3）：
- 读取按**任务名单快照行政班**收窄，同学院不等于全部班级；
- 审核必须同时命中本人责任关系与任务真实负责学院，外院任务没有审核动作；
- 与教师更正共用同一考勤行和唯一审核状态机，过期请求 409，异议不自动结案；
- 交接生效后旧负责人下一次读取/审核即被拒绝。
"""

from datetime import date, timedelta

import pytest
from app.models import Base
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.models import UserAccount
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_deps import CurrentStaff
from app.modules.inspection.models import InspectionTask, TaskRosterMember
from app.modules.objection.models import (
    Objection,
    ObjectionFinalStatus,
    ObjectionInitialStatus,
)
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

TASK_DAY = date(2026, 10, 19)
SINCE = date(2026, 1, 1)


@pytest.fixture(name="source_bumps", autouse=True)
def patch_source_revision(monkeypatch):
    """报表源修订用 MySQL 方言 UPSERT；内存库只核对触发次数与所属任务。"""
    from app.modules.report.source_revision import SourceRevisionService

    seen: list[int] = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: seen.append(tid)
    )
    return seen


@pytest.fixture(name="db")
def objection_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add_all(
            [
                College(id=1, school_id=1, code="C1", name="计算机学院"),
                College(id=2, school_id=1, code="C2", name="外语学院"),
            ]
        )
        db.flush()
        db.add(
            Semester(
                id=1,
                code="F2026",
                name="2026秋",
                status="ACTIVE",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 31),
                first_monday=date(2026, 8, 31),
                total_weeks=22,
            )
        )
        db.add_all(
            [
                Course(id=1, college_id=1, course_code="A", course_name="高等数学"),
                Course(id=2, college_id=2, course_code="B", course_name="英语"),
            ]
        )
        db.add_all(
            [
                TeachingClass(
                    id=1, college_id=1, semester_id=1, course_id=1,
                    class_code="T1", class_name="高数一班",
                ),
                TeachingClass(
                    id=2, college_id=2, semester_id=1, course_id=2,
                    class_code="T2", class_name="英语二班",
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                AdministrativeClass(id=1, college_id=1, class_code="A1", class_name="计算机1班"),
                AdministrativeClass(id=2, college_id=1, class_code="A2", class_name="计算机2班"),
                AdministrativeClass(id=3, college_id=2, class_code="B1", class_name="外语1班"),
            ]
        )
        db.flush()
        db.add_all(
            [
                Student(id=1, student_no="S001", name="张三", administrative_class_id=1),
                Student(id=2, student_no="S002", name="李四", administrative_class_id=1),
                Student(id=3, student_no="S003", name="王五", administrative_class_id=2),
                Student(id=4, student_no="S004", name="赵六", administrative_class_id=3),
            ]
        )
        db.flush()
        db.add_all(
            [
                UserAccount(id=20, display_name="王辅导员", status="ACTIVE"),
                UserAccount(id=21, display_name="陈辅导员", status="ACTIVE"),
                UserAccount(id=22, display_name="接班辅导员", status="ACTIVE"),
            ]
        )
        db.flush()
        db.add_all(
            [
                FacultyStaff(
                    id=102, school_id=1, college_id=1, staff_no="C001",
                    name="王辅导员", user_id=20, status="ACTIVE",
                ),
                FacultyStaff(
                    id=103, school_id=1, college_id=1, staff_no="C002",
                    name="陈辅导员", user_id=21, status="ACTIVE",
                ),
                FacultyStaff(
                    id=104, school_id=1, college_id=1, staff_no="C003",
                    name="接班辅导员", user_id=22, status="ACTIVE",
                ),
            ]
        )
        db.flush()

        # 任务 1 由本院负责，名单同时含本班(1)与同院他班(2)学生；任务 2 由外院负责，
        # 但名单里也有本班学生——读取可见、审核不可见。
        db.add_all(
            [
                InspectionTask(
                    id=1, task_key="K1", college_id=1, semester_id=1,
                    inspection_date=TASK_DAY, week_no=8, inspection_type="COURSE",
                    start_period=1, end_period=2, teaching_class_id=1,
                    course_name_snapshot="高等数学", classroom_snapshot="教101",
                    roster_version=1, expected_count_snapshot=3, expected_count_current=3,
                ),
                InspectionTask(
                    id=2, task_key="K2", college_id=2, semester_id=1,
                    inspection_date=TASK_DAY, week_no=8, inspection_type="COURSE",
                    start_period=3, end_period=4, teaching_class_id=2,
                    course_name_snapshot="英语", classroom_snapshot="教202",
                    roster_version=1, expected_count_snapshot=2, expected_count_current=2,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                _member(1, 1, "S001", "张三", 1, "计算机1班"),
                _member(1, 2, "S002", "李四", 1, "计算机1班"),
                _member(1, 3, "S003", "王五", 2, "计算机2班"),
                _member(2, 1, "S001", "张三", 1, "计算机1班"),
                _member(2, 4, "S004", "赵六", 3, "外语1班"),
            ]
        )
        db.add_all(
            [
                AttendanceRecord(
                    id=1, task_id=1, student_id=1, effective_type="ABSENT", current_version=1
                ),
                AttendanceRecord(
                    id=2, task_id=1, student_id=2, effective_type="LATE", current_version=1
                ),
                AttendanceRecord(
                    id=3, task_id=1, student_id=3, effective_type="ABSENT", current_version=1
                ),
                AttendanceRecord(
                    id=4, task_id=2, student_id=1, effective_type="LEAVE", current_version=1
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                _objection(1, 1, 1),
                _objection(2, 2, 2),
                _objection(3, 3, 3),
                _objection(4, 4, 1),
            ]
        )
        db.add_all(
            [
                ClassStaffResponsibility(
                    id=501, staff_id=102, administrative_class_id=1,
                    duty="COUNSELOR", effective_from=SINCE,
                ),
                ClassStaffResponsibility(
                    id=502, staff_id=103, administrative_class_id=2,
                    duty="HEAD_TEACHER", effective_from=SINCE,
                ),
            ]
        )
        db.commit()
        yield db
    engine.dispose()


def _member(task_id, student_id, sno, name, class_id, class_name):
    return TaskRosterMember(
        task_id=task_id,
        roster_version=1,
        student_id=student_id,
        student_no=sno,
        name=name,
        class_name_snapshot=class_name,
        administrative_class_id_snapshot=class_id,
    )


def _objection(objection_id, record_id, student_id):
    return Objection(
        id=objection_id,
        attendance_record_id=record_id,
        student_id=student_id,
        base_attendance_version=1,
        reason="现场已签到",
        desired_type="NORMAL",
        initial_status=ObjectionInitialStatus.PENDING.value,
        final_status=ObjectionFinalStatus.PENDING.value,
    )


def staff_ref(db, user_id):
    row = db.scalar(select(FacultyStaff).where(FacultyStaff.user_id == user_id))
    return CurrentStaff(
        user=CurrentUser(
            id=row.user_id,
            username=None,
            display_name=row.name,
            status="ACTIVE",
            roles=[],
            permissions=[],
            pre_binding=False,
        ),
        staff_id=row.id,
        staff_no=row.staff_no,
        name=row.name,
        school_id=row.school_id,
        college_id=row.college_id,
        lock_version=row.lock_version,
    )


def service(db, user_id):
    from app.modules.objection.staff_service import StaffResponsibleObjectionService

    return StaffResponsibleObjectionService(db, staff_ref(db, user_id))


def page_params(page=1, page_size=20):
    from app.common.pagination import PageParams

    return PageParams(page=page, page_size=page_size)


def objection_ids(data):
    return {int(item.objection.id) for item in data["items"]}


def review_body(version, decision="APPROVED", final_type="NORMAL", comment=None):
    from app.modules.objection.schemas import ObjectionFinalReviewRequest

    return ObjectionFinalReviewRequest(
        decision=decision, final_type=final_type, comment=comment, current_version=version
    )


# --------------------------------------------------------------------------- #
# 读取范围：责任班级 + 名单快照，不串班、同院不等于全部
# --------------------------------------------------------------------------- #
def test_list_only_covers_own_responsible_class_students(db):
    data = service(db, 20).list_responsible(page_params())
    ids = {int(item.objection.id) for item in data["items"]}
    # 1(本班张三)、2(本班李四)、4(本班学生被外院查课) 可见；3(同院他班王五) 不可见。
    assert ids == {1, 2, 4}
    assert data["total"] == 3


def test_counselor_of_other_class_cannot_read_or_review(db):
    from app.core.exceptions import NotFoundError

    other = service(db, 21)
    assert objection_ids(other.list_responsible(page_params())) == {3}
    with pytest.raises(NotFoundError):
        other.get_responsible(1)
    with pytest.raises(NotFoundError):
        other.review(1, review_body(1), None)
    assert db.scalar(select(Objection).where(Objection.id == 1)).final_status == "PENDING"


def test_detail_exposes_responsible_college_and_reviewability(db):
    detail = service(db, 20).get_responsible(1)
    assert detail.responsible_college_id == "1"
    assert detail.responsible_college_name == "计算机学院"
    assert detail.can_review is True
    foreign = service(db, 20).get_responsible(4)
    assert foreign.responsible_college_id == "2"
    assert foreign.can_review is False
    assert foreign.review_block_reason is not None


def test_status_filter_keeps_reviewed_items_out_of_the_todo_list(db):
    service(db, 20).review(1, review_body(1, decision="REJECTED", final_type=None), "REQ-R")
    pending = service(db, 20).list_responsible(page_params(), final_status="PENDING")
    assert {int(item.objection.id) for item in pending["items"]} == {2, 4}


# --------------------------------------------------------------------------- #
# 外院任务：可见但没有改判入口
# --------------------------------------------------------------------------- #
def test_foreign_college_task_cannot_be_reviewed_even_with_copied_request(db):
    from app.core.exceptions import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        service(db, 20).review(4, review_body(1), "REQ-F")
    obj = db.scalar(select(Objection).where(Objection.id == 4))
    record = db.get(AttendanceRecord, 4)
    assert obj.final_status == ObjectionFinalStatus.PENDING.value
    assert obj.final_reviewed_by is None
    assert (record.effective_type, record.current_version) == ("LEAVE", 1)


# --------------------------------------------------------------------------- #
# 与教师更正共用考勤行与版本链
# --------------------------------------------------------------------------- #
def _teacher_correction(db, record_id=1, target="LATE"):
    from app.modules.attendance.staff_service import StaffTeachingAttendanceService

    db.add(
        TeachingStaffAssignment(
            staff_id=102, semester_id=1, anchor_type="LOCAL", teaching_class_id=1,
            effective_from=SINCE,
        )
    )
    db.commit()
    from app.modules.attendance.schemas import AttendanceCorrectionRequest

    return StaffTeachingAttendanceService(db).correct_teaching(
        staff_ref(db, 20).user,
        staff_ref(db, 20),
        record_id,
        AttendanceCorrectionRequest(
            current_version=1, attendance_type=target, reason="教师核对签到表"
        ),
        "REQ-T",
    )


def test_teacher_correction_makes_stale_review_conflict_and_open_objection_survives(db):
    from app.core.exceptions import ConflictError, ErrorCode

    _teacher_correction(db)
    with pytest.raises(ConflictError) as exc:
        service(db, 20).review(1, review_body(1), "REQ-S")
    assert exc.value.code == ErrorCode.VERSION_CONFLICT
    obj = db.scalar(select(Objection).where(Objection.id == 1))
    assert obj.final_status == ObjectionFinalStatus.PENDING.value
    assert obj.base_attendance_version == 1


def test_review_after_rechecking_baselines_on_current_version(db, source_bumps):
    from app.modules.attendance.models import AttendanceRecordVersion, AttendanceSourceType
    from app.modules.audit.models import AuditLog

    _teacher_correction(db)
    result = service(db, 20).review(1, review_body(2), "REQ-A")
    assert result.final_status == "APPROVED"
    assert result.attendance.current_version == 3
    assert db.get(AttendanceRecord, 1).effective_type == "NORMAL"

    chain = db.scalars(
        select(AttendanceRecordVersion).order_by(AttendanceRecordVersion.version_no)
    ).all()
    assert [(c.version_no, c.source_type) for c in chain] == [
        (2, AttendanceSourceType.CORRECTION.value),
        (3, AttendanceSourceType.OBJECTION_FINAL.value),
    ]
    # 教师更正与辅导员改判各自修订原任务学院的数据源。
    assert source_bumps == [1, 1]
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "objection.final_review", AuditLog.resource_id == "1"
        )
    )
    assert audit.after_json["attendance_changed_since_filing"] is True
    assert audit.after_json["base_attendance_version"] == 1


def test_second_review_of_the_same_objection_is_rejected(db):
    from app.core.exceptions import ConflictError, ErrorCode

    service(db, 20).review(1, review_body(1), "REQ-1")
    with pytest.raises(ConflictError) as exc:
        service(db, 20).review(1, review_body(2), "REQ-2")
    assert exc.value.code == ErrorCode.STATE_CONFLICT


def test_rejection_keeps_attendance_and_records_the_operator(db, source_bumps):
    result = service(db, 20).review(
        2, review_body(1, decision="REJECTED", final_type=None, comment="证据不足"), "REQ-J"
    )
    record = db.get(AttendanceRecord, 2)
    assert result.final_status == "REJECTED"
    assert result.final_reviewed_by == "20"
    assert (record.effective_type, record.current_version) == ("LATE", 1)
    assert source_bumps == []


# --------------------------------------------------------------------------- #
# 交接：旧负责人下一次请求即失效
# --------------------------------------------------------------------------- #
def test_handover_revokes_the_predecessor_and_authorizes_the_successor(db):
    from app.core.exceptions import NotFoundError
    from app.modules.identity.role_scope import business_today

    today = business_today()
    assert today > SINCE
    db.scalar(
        select(ClassStaffResponsibility).where(ClassStaffResponsibility.id == 501)
    ).effective_to = today
    db.add(
        ClassStaffResponsibility(
            staff_id=104, administrative_class_id=1, duty="COUNSELOR", effective_from=today
        )
    )
    db.commit()

    predecessor = service(db, 20)
    assert predecessor.list_responsible(page_params())["items"] == []
    with pytest.raises(NotFoundError):
        predecessor.review(1, review_body(1), "REQ-P")
    assert db.scalar(select(Objection).where(Objection.id == 1)).final_status == "PENDING"

    successor = service(db, 22)
    assert objection_ids(successor.list_responsible(page_params())) == {1, 2, 4}
    assert successor.review(1, review_body(1), "REQ-N").final_status == "APPROVED"


def test_inactive_profile_or_account_blocks_every_staff_entry(db):
    from app.core.exceptions import PermissionDeniedError

    db.scalar(select(FacultyStaff).where(FacultyStaff.id == 102)).status = "INACTIVE"
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service(db, 20).list_responsible(page_params())
    with pytest.raises(PermissionDeniedError):
        service(db, 20).review(1, review_body(1), None)


def test_expired_relation_beyond_today_still_counts_while_active(db):
    """半开区间：结束日当天已失效，读取与审核同时收回，不保留只读后门。"""
    from app.core.exceptions import NotFoundError
    from app.modules.identity.role_scope import business_today

    db.scalar(
        select(ClassStaffResponsibility).where(ClassStaffResponsibility.id == 501)
    ).effective_to = business_today() + timedelta(days=1)
    db.commit()
    assert objection_ids(service(db, 20).list_responsible(page_params())) == {1, 2, 4}
    db.scalar(
        select(ClassStaffResponsibility).where(ClassStaffResponsibility.id == 501)
    ).effective_to = business_today()
    db.commit()
    assert service(db, 20).list_responsible(page_params())["items"] == []
    with pytest.raises(NotFoundError):
        service(db, 20).get_responsible(1)


# --------------------------------------------------------------------------- #
# 材料签名与读取/审核同源
# --------------------------------------------------------------------------- #
def test_handover_revokes_material_signing_as_well(db):
    """签名口径与读取/审核同源：交接生效后旧负责人不能再取异议证明材料。"""
    from app.core.database import utcnow
    from app.modules.file.models import FileCategory, FileObject, FileStatus
    from app.modules.file.staff_access import can_staff_access_file
    from app.modules.identity.role_scope import business_today
    from app.modules.objection.models import ObjectionFile

    proof = FileObject(
        id=201,
        object_key="proofs/obj1.jpg",
        category=FileCategory.OBJECTION_PROOF.value,
        content_type="image/jpeg",
        size_bytes=1024,
        sha256="0" * 64,
        uploader_user_id=20,
        status=FileStatus.READY.value,
        expires_at=utcnow() + timedelta(days=7),
    )
    db.add(proof)
    db.flush()
    db.add(ObjectionFile(objection_id=1, file_id=201))
    db.commit()
    assert can_staff_access_file(db, 20, proof) is True

    today = business_today()
    db.scalar(
        select(ClassStaffResponsibility).where(ClassStaffResponsibility.id == 501)
    ).effective_to = today
    db.add(
        ClassStaffResponsibility(
            staff_id=104, administrative_class_id=1, duty="COUNSELOR", effective_from=today
        )
    )
    db.commit()
    assert can_staff_access_file(db, 20, proof) is False
    successor = db.scalar(select(FacultyStaff).where(FacultyStaff.id == 104))
    assert can_staff_access_file(db, successor.user_id, proof) is True


# --------------------------------------------------------------------------- #
# HTTP 接线：路由挂载、依赖注入与状态码口径
# --------------------------------------------------------------------------- #
def _client(db, user_id):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient

    def actor():
        return CurrentUser(
            id=user_id,
            username=None,
            display_name="辅导员",
            status="ACTIVE",
            roles=[],
            permissions=[],
            pre_binding=False,
        )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = actor
    return TestClient(app)


def test_http_list_detail_and_review_round_trip(db):
    with _client(db, 20) as client:
        listed = client.get("/api/v1/me/responsible-objections")
        assert listed.status_code == 200, listed.text
        items = listed.json()["data"]["items"]
        assert {item["objection"]["id"] for item in items} == {"1", "2", "4"}
        assert {item["objection"]["id"] for item in items if not item["can_review"]} == {"4"}

        stale = client.post(
            "/api/v1/me/responsible-objections/1/review",
            json={"decision": "APPROVED", "final_type": "NORMAL", "current_version": 9},
        )
        assert stale.status_code == 409, stale.text
        assert client.get("/api/v1/me/responsible-objections/1").json()["data"][
            "objection"
        ]["final_status"] == "PENDING"

        ok = client.post(
            "/api/v1/me/responsible-objections/1/review",
            json={
                "decision": "APPROVED",
                "final_type": "NORMAL",
                "current_version": 1,
                "comment": "已核对签到表",
            },
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["final_status"] == "APPROVED"


def test_http_foreign_college_review_is_forbidden(db):
    with _client(db, 20) as client:
        res = client.post(
            "/api/v1/me/responsible-objections/4/review",
            json={"decision": "APPROVED", "final_type": "NORMAL", "current_version": 1},
        )
        assert res.status_code == 403, res.text
        assert (
            client.get("/api/v1/me/responsible-objections/4").json()["data"]["can_review"]
            is False
        )


def test_http_account_without_staff_profile_is_rejected(db):
    with _client(db, 30) as client:
        assert client.get("/api/v1/me/responsible-objections").status_code == 403
        assert (
            client.post(
                "/api/v1/me/responsible-objections/1/review",
                json={"decision": "REJECTED", "current_version": 1},
            ).status_code
            == 403
        )
