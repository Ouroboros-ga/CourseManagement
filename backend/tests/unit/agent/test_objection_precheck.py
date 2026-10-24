"""预审建议独立保存；真实领域事实变化后不接纳迟到结果。"""

from contextlib import suppress

import pytest
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.models import Role, UserRole
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.objection.precheck_schemas import PrecheckResult
from app.modules.objection.precheck_service import ObjectionPrecheckService
from app.modules.objection.schemas import ObjectionFinalReviewRequest
from pydantic import ValidationError
from sqlalchemy import select
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_objection import prepare
from tests.unit.test_scoped_objection import service as objection_service


@pytest.fixture(name="case")
def case_fixture(monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", True)
    yield_from = campus_fixture.__wrapped__()
    campus = next(yield_from)
    db, teacher, a, b, one, two = prepare(campus)
    role = Role(code="TEACHER_ADMIN", name="教师")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=teacher.id, role_id=role.id))
    db.commit()
    yield db, teacher, int(a["id"]), int(b["id"]), one, two
    with suppress(StopIteration):
        next(yield_from)


def result():
    return PrecheckResult(
        recommendation="NEEDS_VERIFICATION", summary="请人工核对请假情况", evidence=[]
    )


def queue(case):
    db, teacher, cid, _, obj, _ = case
    svc = ObjectionPrecheckService(db, cid)
    svc.set_policy(teacher, enabled=True, current_version=0)
    job = svc.enqueue(obj.id, teacher.id)
    db.commit()
    return svc, job


def test_event_idempotent_and_result_cannot_change_formal_decision(case):
    db, teacher, _, _, obj, _ = case
    svc, job = queue(case)
    assert svc.enqueue(obj.id, teacher.id).id == job.id
    record = db.get(AttendanceRecord, obj.attendance_record_id)
    before = (record.effective_type, record.current_version, obj.final_status, obj.initial_status)
    attempt = svc.begin(job.id)
    assert svc.finish(job.id, attempt, result()) == "SUCCEEDED"
    assert (
        record.effective_type,
        record.current_version,
        obj.final_status,
        obj.initial_status,
    ) == before
    assert svc.read(teacher, job.id)["result"]["summary"] == "请人工核对请假情况"
    assert db.scalars(select(ObjectionPrecheckJob)).all() == [job]


def test_missing_policy_is_visible_failure_not_fake_precheck(case):
    db, teacher, cid, _, obj, _ = case
    job = ObjectionPrecheckService(db, cid).enqueue(obj.id, teacher.id)
    assert job.status == "FAILED" and job.error_code == "POLICY_UNAVAILABLE"
    assert obj.final_status == "PENDING"


@pytest.mark.parametrize("change", ["attendance", "reason", "review", "withdrawn"])
def test_changed_facts_or_human_review_fence_late_result(case, change, monkeypatch):
    db, teacher, cid, _, obj, _ = case
    svc, job = queue(case)
    attempt = svc.begin(job.id)
    record = db.get(AttendanceRecord, obj.attendance_record_id)
    if change == "attendance":
        record.current_version += 1
    elif change == "reason":
        obj.reason = "补充了新理由"
    elif change == "withdrawn":
        record.effect_state = "WITHDRAWN"
    else:
        # A legacy-mode human decision must still fence a result arriving after
        # the precheck feature is enabled again; enabled-mode pending review blocks.
        with monkeypatch.context() as patch:
            patch.setattr(get_settings(), "agent_objection_precheck_enabled", False)
            objection_service(db, teacher, cid).final_review(
                teacher,
                obj.id,
                ObjectionFinalReviewRequest(decision="REJECTED", current_version=1),
                None,
            )
    db.commit()
    assert svc.finish(job.id, attempt, result()) == "STALE"
    assert job.result_json is None


def test_policy_disabled_or_authorizer_demoted_blocks_result(case):
    db, teacher, _, _, _, _ = case
    svc, job = queue(case)
    attempt = svc.begin(job.id)
    svc.set_policy(teacher, enabled=False, current_version=1)
    with pytest.raises(PermissionDeniedError):
        svc.finish(job.id, attempt, result())
    assert db.get(ObjectionPrecheckJob, job.id).result_json is None


def test_foreign_college_hidden_and_wrong_attempt_rejected(case):
    db, teacher, _, other, _, foreign = case
    svc, job = queue(case)
    with pytest.raises(NotFoundError):
        svc.enqueue(foreign.id, teacher.id)
    attempt = svc.begin(job.id)
    with pytest.raises(ConflictError):
        svc.finish(job.id, "wrong", result())
    with pytest.raises(NotFoundError):
        ObjectionPrecheckService(db, other).read(teacher, job.id)
    assert svc.finish(job.id, attempt, result()) == "SUCCEEDED"


def test_advice_schema_rejects_final_action_and_fabricated_proof(case):
    svc, job = queue(case)
    attempt = svc.begin(job.id)
    with pytest.raises(ValidationError):
        PrecheckResult(**result().model_dump(), final_status="APPROVED")
    forged = PrecheckResult(
        recommendation="SUPPORT",
        summary="建议核对",
        evidence=[{"source": "PROOF", "file_id": "123", "observation": "材料日期"}],
    )
    with pytest.raises(NotFoundError):
        svc.finish(job.id, attempt, forged)


def test_read_hides_previous_advice_after_source_changes(case):
    db, teacher, _, _, obj, _ = case
    svc, job = queue(case)
    svc.finish(job.id, svc.begin(job.id), result())
    obj.reason = "新的情况"
    db.commit()
    view = svc.read(teacher, job.id)
    assert view["status"] == "STALE" and view["result"] is None
    assert job.result_json is not None  # 历史原文留存，但不作为当前建议显示。


def test_revoked_actual_teacher_role_is_not_replaced_by_cached_actor(case):
    from sqlalchemy import delete

    db, teacher, _, _, _, _ = case
    svc, job = queue(case)
    attempt = svc.begin(job.id)
    role = db.scalar(select(Role).where(Role.code == "TEACHER_ADMIN"))
    db.execute(delete(UserRole).where(UserRole.user_id == teacher.id, UserRole.role_id == role.id))
    db.commit()
    with pytest.raises(PermissionDeniedError):
        svc.finish(job.id, attempt, result())


def test_material_facts_change_invalidates_attempt(case):
    from app.modules.file.models import FileObject
    from app.modules.objection.models import ObjectionFile

    db, teacher, _, _, obj, _ = case
    proof = FileObject(
        object_key="synthetic-proof",
        category="OBJECTION_PROOF",
        original_name="proof.png",
        content_type="image/png",
        size_bytes=10,
        sha256="a" * 64,
        uploader_user_id=teacher.id,
        status="READY",
    )
    db.add(proof)
    db.flush()
    db.add(ObjectionFile(objection_id=obj.id, file_id=proof.id))
    db.commit()
    svc, job = queue(case)
    attempt = svc.begin(job.id)
    proof.sha256 = "b" * 64
    db.commit()
    assert svc.finish(job.id, attempt, result()) == "STALE"


def student_case(case, monkeypatch):
    from app.modules.identity.models import Permission, RolePermission, UserAccount
    from app.modules.identity.service import CurrentUser
    from app.modules.objection.service import ObjectionService

    db, _, _, _, obj, _ = case
    record_id, sid = obj.attendance_record_id, obj.student_id
    db.delete(obj)
    role = Role(code="STUDENT", name="学生")
    perm = Permission(code="objection.create", name="创建申诉")
    user = UserAccount(display_name="测试学生", status="ACTIVE", student_id=sid)
    db.add_all([role, perm, user])
    db.flush()
    db.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            RolePermission(role_id=role.id, permission_id=perm.id),
        ]
    )
    db.commit()
    monkeypatch.setattr(get_settings(), "objection_window_days", 0)
    actor = CurrentUser(user.id, None, "测试学生", "ACTIVE", ["STUDENT"], ["objection.create"])
    return ObjectionService(db), actor, record_id


def test_real_student_creation_registers_precheck_in_same_transaction(case, monkeypatch):
    from app.modules.objection.schemas import ObjectionCreateRequest

    db = case[0]
    svc, actor, rid = student_case(case, monkeypatch)
    created = svc.create(
        actor, rid, ObjectionCreateRequest(reason="因病误记", desired_type="NORMAL"), None
    )
    job = db.scalar(select(ObjectionPrecheckJob))
    assert job is not None and str(job.objection_id) == str(created.id)
    assert job.initiated_by_user_id == actor.id and job.error_code == "POLICY_UNAVAILABLE"


def test_creation_event_failure_cannot_leave_partial_objection(case, monkeypatch):
    from app.modules.objection.models import Objection
    from app.modules.objection.schemas import ObjectionCreateRequest

    db = case[0]
    svc, actor, rid = student_case(case, monkeypatch)

    original_enqueue = ObjectionPrecheckService.enqueue

    def fail(*args):
        original_enqueue(*args)
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(ObjectionPrecheckService, "enqueue", fail)
    with pytest.raises(RuntimeError, match="synthetic event"):
        svc.create(actor, rid, ObjectionCreateRequest(reason="误记", desired_type="NORMAL"), None)
    db.commit()
    assert db.scalar(select(Objection).where(Objection.attendance_record_id == rid)) is None
    assert db.scalar(select(ObjectionPrecheckJob)) is None


def test_precheck_migration_roundtrip_and_history_guard(case):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.core.database import utcnow
    from sqlalchemy import inspect, text

    db, teacher, cid, _, _, _ = case
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a007_objection_precheck.py"
    spec = importlib.util.spec_from_file_location("precheck_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE objection_precheck_job"))
        connection.execute(text("DROP TABLE objection_precheck_policy"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
            connection.execute(
                text(
                    "INSERT INTO objection_precheck_policy "
                    "(college_id, authorizer_user_id, enabled, version, created_at, updated_at) "
                    "VALUES (:cid, :uid, 0, 1, :now, :now)"
                ),
                {"cid": cid, "uid": teacher.id, "now": utcnow()},
            )
            with pytest.raises(RuntimeError, match="precheck"):
                migration.downgrade()
            assert "objection_precheck_job" in inspect(connection).get_table_names()


def test_legacy_unknown_college_is_failed_without_guessing_scope(case):
    from app.modules.inspection.models import InspectionTask

    db, teacher, _, _, obj, _ = case
    record = db.get(AttendanceRecord, obj.attendance_record_id)
    task = db.get(InspectionTask, record.task_id)
    task.college_id = None
    db.commit()
    job = ObjectionPrecheckService(db, None).enqueue(obj.id, teacher.id)
    assert job.status == "FAILED" and job.error_code == "SOURCE_SCOPE_UNRESOLVED"
    assert job.college_id is None and job.authorizer_user_id is None


def test_feature_off_preserves_original_student_creation(case, monkeypatch):
    from app.modules.objection.schemas import ObjectionCreateRequest

    db = case[0]
    svc, actor, rid = student_case(case, monkeypatch)
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", False)
    svc.create(actor, rid, ObjectionCreateRequest(reason="误记", desired_type="NORMAL"), None)
    assert db.scalar(select(ObjectionPrecheckJob)) is None


def test_changed_source_before_claim_is_closed_without_model_work(case):
    db, _, _, _, obj, _ = case
    svc, job = queue(case)
    obj.reason = "新的申诉材料说明"
    db.commit()
    assert svc.begin(job.id) is None
    assert job.status == "STALE" and job.attempt_token is None


def test_archived_semester_cannot_begin_queued_precheck(case):
    from app.modules.academic.models import Semester
    from app.modules.inspection.models import InspectionTask

    db, _, _, _, obj, _ = case
    svc, job = queue(case)
    task = db.get(InspectionTask, db.get(AttendanceRecord, obj.attendance_record_id).task_id)
    db.get(Semester, task.semester_id).status = "ARCHIVED"
    db.commit()
    with pytest.raises(ConflictError):
        svc.begin(job.id)
    assert db.get(ObjectionPrecheckJob, job.id).status == "QUEUED"
