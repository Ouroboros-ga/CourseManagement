from datetime import date
from types import SimpleNamespace

import pytest
from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.inspection.schemas import CourseOccurrenceScope
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_type_filter_is_enforced_before_occurrence_planning(campus, monkeypatch):
    from app.modules.inspection.course_occurrences import build_scope
    from app.modules.inspection.scoped_service import ScopedInspectionService

    db, admin, college, sem, _, _, teaching, other = arrange(campus, monkeypatch)
    service = ScopedInspectionService(db, admin, int(college["id"]))
    service._require(admin.id, "inspection.generate")
    scope = CourseOccurrenceScope(
        date_from=date(2026, 9, 7),
        date_to=date(2026, 9, 7),
        teaching_class_ids=[teaching.id],
        course_type_id=other["id"],
    )
    items, revision = build_scope(service, sem, scope)
    assert items == []
    scope.course_type_id = str(teaching.course_type_id)
    items, new_revision = build_scope(service, sem, scope)
    assert items
    assert new_revision != revision


def test_occurrence_route_supplies_semester_to_group_preparation(campus, monkeypatch):
    from app.modules.inspection.router import get_course_occurrences
    from app.modules.inspection.scoped_service import ScopedInspectionService

    db, admin, college, sem, group, _, _, _ = arrange(campus, monkeypatch)
    result = get_course_occurrences(
        actor=admin,
        service=ScopedInspectionService(db, admin, int(college["id"])),
        request=SimpleNamespace(state=SimpleNamespace(request_id=None)),
        semester_id=sem.id,
        date_from=date(2026, 9, 7),
        date_to=date(2026, 9, 7),
        teaching_class_ids=None,
        administrative_class_id=None,
        page=1,
        page_size=200,
        require_photo=False,
        execution_group_id=int(group["id"]),
    )
    assert result["data"]["items"]


def test_explicit_group_is_not_ignored_when_scheduler_is_off(monkeypatch):
    from app.modules.inspection.execution_group import prepare

    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", False)
    with pytest.raises(ConflictError, match="未启用"):
        prepare(SimpleNamespace(), None, SimpleNamespace(execution_group_id="1"))


def test_smart_sample_respects_type_and_group_semester(campus, monkeypatch):
    from app.modules.inspection.router import smart_sample_course_occurrences
    from app.modules.inspection.schemas import SmartSampleRequest
    from app.modules.inspection.scoped_service import ScopedInspectionService

    db, admin, college, sem, group, _, teaching, other = arrange(campus, monkeypatch)
    service = ScopedInspectionService(db, admin, int(college["id"]))
    request = SimpleNamespace(state=SimpleNamespace(request_id=None))
    body = SmartSampleRequest(
        semester_id=sem.id, week_no=2, execution_group_id=group["id"], course_type_id=other["id"]
    )
    result = smart_sample_course_occurrences(body, admin, service, request)
    assert result["data"]["sampled_count"] == 0
    body.course_type_id = str(teaching.course_type_id)
    result = smart_sample_course_occurrences(body, admin, service, request)
    assert result["data"]["sampled_count"] > 0


def test_published_but_unused_group_can_be_deleted(campus):
    from app.modules.volunteer.models import GroupConfigVersion, VolunteerGroup

    service, db, admin, _, a, _ = campus
    kind = service.create_type(admin, int(a["id"]), {"name": "课"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "误建", "owner_user_id": str(admin.id)}
    )
    group = service.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"lock_version": group["lock_version"], "course_type_ids": [kind["id"]]},
    )
    service.delete_group(admin, int(a["id"]), int(group["id"]), group["lock_version"])
    assert db.get(VolunteerGroup, int(group["id"])) is None
    assert (
        db.scalar(
            select(GroupConfigVersion.id).where(GroupConfigVersion.group_id == int(group["id"]))
        )
        is None
    )


def test_members_can_be_prepared_before_scheduler_activation(monkeypatch):
    from app.modules.academic.time_router import require_scheduling_enabled
    from app.modules.volunteer.member_router import router

    assert all(dep.dependency is not require_scheduling_enabled for dep in router.dependencies)


def test_student_volunteer_filter_applies_to_rows_and_total(campus):
    from app.common.pagination import PageParams
    from app.modules.academic.models import Student, VolunteerQualification
    from app.modules.academic.scoped_service import ScopedAcademicService

    from tests.unit.test_group_business import prepare

    _, db, admin, a, _, sem, _, _, own, _ = prepare(campus)
    db.add(
        Student(
            student_no="another",
            name="非志愿者",
            administrative_class_id=own.administrative_class_id,
        )
    )
    db.add(VolunteerQualification(student_id=own.id, semester_id=sem.id, enabled=True))
    db.commit()
    page = ScopedAcademicService(db, admin, int(a["id"])).list_rows(
        "students", PageParams(1, 10), semester_id=sem.id, is_volunteer=True
    )
    assert page["total"] == 1
    assert [row["id"] for row in page["items"]] == [str(own.id)]


def test_delete_group_with_member_preserves_records(campus):
    from app.modules.volunteer.member_models import VolunteerGroupMember
    from app.modules.volunteer.member_service import GroupMemberService
    from app.modules.volunteer.models import VolunteerGroup

    from tests.unit.test_group_business import prepare

    config, db, admin, a, _, sem, group, _, own, _ = prepare(campus)
    GroupMemberService(db, admin, int(a["id"]), int(group["id"])).create(
        {
            "student_id": str(own.id),
            "semester_id": str(sem.id),
            "effective_from": "2026-09-07",
            "effective_to": "2027-01-31",
        }
    )
    row = db.get(VolunteerGroup, int(group["id"]))
    with pytest.raises(ConflictError, match="预览"):
        config.delete_group(admin, int(a["id"]), row.id, row.lock_version)
    assert db.scalar(select(VolunteerGroupMember.id)) is not None


def test_course_type_filter_rejects_overflow_id():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CourseOccurrenceScope(
            date_from=date(2026, 9, 7), date_to=date(2026, 9, 7), course_type_id=str(2**63)
        )
