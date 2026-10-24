import pytest
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.objection.models import Objection
from app.modules.objection.precheck_service import ObjectionPrecheckService
from app.modules.objection.schemas import ObjectionFinalReviewRequest
from tests.unit.test_staff_objections import objection_db, service


@pytest.fixture(name="db")
def fixture():
    yield from objection_db.__wrapped__()


def test_staff_readability_remains_but_ordinary_staff_cannot_final_review_with_ai_enabled(
    db, monkeypatch
):
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", True)
    detail = service(db, 20).get_responsible(1)
    assert not detail.can_review and "教务" in detail.review_block_reason
    with pytest.raises(PermissionDeniedError):
        service(db, 20).review(
            1, ObjectionFinalReviewRequest(decision="REJECTED", current_version=1)
        )
    assert db.get(Objection, 1).final_status == "PENDING"
    with pytest.raises(NotFoundError):
        service(db, 20).review(
            3, ObjectionFinalReviewRequest(decision="REJECTED", current_version=1)
        )


def test_staff_legacy_flow_remains_when_precheck_feature_is_disabled(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", False)
    assert service(db, 20).get_responsible(1).can_review
    service(db, 20).review(1, ObjectionFinalReviewRequest(decision="REJECTED", current_version=1))
    assert db.get(Objection, 1).final_status == "REJECTED"


def test_staff_with_real_academic_role_and_college_scope_uses_the_same_final_guard(db, monkeypatch):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding
    from app.modules.identity.models import Role, UserRole

    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", True)
    role = Role(code="TEACHER_ADMIN", name="教务管理员")
    db.add(role)
    db.flush()
    db.add_all(
        [UserRole(user_id=20, role_id=role.id), TeacherCollegeBinding(user_id=20, college_id=1)]
    )
    db.commit()
    job = ObjectionPrecheckService(db, 1).enqueue(1, 20)
    db.commit()
    assert service(db, 20).get_responsible(1).can_review
    service(db, 20).review(
        1,
        ObjectionFinalReviewRequest(
            decision="REJECTED",
            current_version=1,
            precheck_job_id=str(job.id),
            manual_precheck_reason="已人工核验请假材料",
        ),
    )
    assert db.get(Objection, 1).final_status == "REJECTED"
