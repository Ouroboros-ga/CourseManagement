"""显式资源范围进入 SQL、计数和写事务；不能依靠角色与学院分别并集。"""

import pytest
from app.common.pagination import PageParams
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import AdministrativeClass, Student, TeachingClassStudent
from app.modules.audit.models import AuditLog
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_campus_ownership import legacy


@pytest.fixture(name="campus")
def scoped_fixture():
    yield from campus_fixture.__wrapped__()


def service(db, actor, cid):
    from app.modules.academic.scoped_service import ScopedAcademicService

    return ScopedAcademicService(db, actor, int(cid))


def test_student_page_uses_batch_enrollment_and_class_names(campus, monkeypatch):
    from app.modules.academic.enrollment_service import EnrollmentService

    config, db, admin, teacher, a, b = campus
    records(db, a, b)
    grant(config, admin, teacher, a, ["student.read"])
    monkeypatch.setattr(
        EnrollmentService, "at", lambda *_: pytest.fail("已批量查询学籍，不应逐行补查")
    )
    original_get = db.get

    def no_per_row_class(model, *args, **kwargs):
        if model is AdministrativeClass:
            pytest.fail("列表的班级名称应批量查询")
        return original_get(model, *args, **kwargs)

    monkeypatch.setattr(db, "get", no_per_row_class)
    page = service(db, teacher, a["id"]).list_rows("students", PageParams(1, 50))
    assert page["items"] and page["items"][0]["administrative_class_name"]


def records(db, a, b):
    one, teaching, schedule, task = legacy(db)
    one.college_id = int(a["id"])
    teaching.college_id = int(a["id"])
    schedule.college_id = int(a["id"])
    task.college_id = int(a["id"])
    two = AdministrativeClass(class_code="B", class_name="乙院班", college_id=int(b["id"]))
    unknown = AdministrativeClass(class_code="UNKNOWN", class_name="未知归属")
    db.add_all([two, unknown])
    db.flush()
    student_a = Student(student_no="A", name="甲学生", administrative_class_id=one.id)
    student_b = Student(student_no="B", name="乙学生", administrative_class_id=two.id)
    db.add_all([student_a, student_b])
    db.commit()
    return one, two, unknown, teaching, schedule, student_a, student_b


def test_scope_filters_rows_counts_unknown_and_cached_foreign_detail(campus):
    config, db, admin, teacher, a, b = campus
    one, two, unknown, _, _, _, _ = records(db, a, b)
    grant(config, admin, teacher, a, ["academic.read"])
    scoped = service(db, teacher, a["id"])
    result = scoped.list_rows("administrative_classes", PageParams(1, 20))
    assert result["total"] == 1
    assert result["items"][0]["id"] == str(one.id)
    # Foreign objects are already in the same Session identity map: use scoped SQL, not Session.get.
    for row in (two, unknown):
        with pytest.raises(NotFoundError):
            scoped.get_row("administrative_classes", row.id)


def test_a_manage_and_b_read_do_not_grant_b_write(campus):
    config, db, admin, teacher, a, b = campus
    grant(config, admin, teacher, a, ["academic.read", "academic.manage"])
    grant(config, admin, teacher, b, ["academic.read"])
    first = service(db, teacher, a["id"]).create_admin_class(
        {"class_code": "X", "class_name": "甲"}
    )
    assert first["college_id"] == a["id"]
    assert isinstance(first["id"], str)
    with pytest.raises(PermissionDeniedError):
        service(db, teacher, b["id"]).create_admin_class({"class_code": "Y", "class_name": "越院"})


def test_schedule_requires_matching_parent_college(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, _, schedule, _, _ = records(db, a, b)
    grant(config, admin, teacher, b, ["academic.read"])
    schedule.college_id = int(b["id"])
    db.commit()
    assert service(db, teacher, b["id"]).list_rows("schedules", PageParams(1, 20))["total"] == 0


def test_course_catalog_excludes_other_college_after_lifecycle_upgrade(campus):
    from app.modules.academic.models import Course

    config, db, admin, teacher, a, b = campus
    db.add_all(
        [
            Course(course_code="SHARED", course_name="共享课程"),
            Course(course_code="A", course_name="甲院课程", college_id=int(a["id"])),
            Course(course_code="B", course_name="乙院课程", college_id=int(b["id"])),
        ]
    )
    db.commit()
    grant(config, admin, teacher, a, ["academic.read"])
    visible = service(db, teacher, a["id"]).list_rows("courses", PageParams(1, 20))
    assert visible["total"] == 2
    assert {row["course_code"] for row in visible["items"]} == {"SHARED", "A"}


def test_roster_mixed_college_batch_is_atomic(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, student_a, student_b = records(db, a, b)
    grant(config, admin, teacher, a, ["student.read", "student.manage"])
    scoped = service(db, teacher, a["id"])
    db.add(TeachingClassStudent(teaching_class_id=teaching.id, student_id=student_a.id))
    db.commit()
    with pytest.raises(NotFoundError):
        scoped.replace_roster(teaching.id, [str(student_a.id), str(student_b.id)], 1)
    assert list(db.scalars(select(TeachingClassStudent.student_id))) == [student_a.id]
    assert db.get(type(teaching), teaching.id).ownership_version == 1


def test_update_version_audit_and_revoke_rechecked_on_reused_service(campus):
    config, db, admin, teacher, a, b = campus
    one, *_ = records(db, a, b)
    delegation = grant(config, admin, teacher, a, ["academic.read", "academic.manage"])
    scoped = service(db, teacher, a["id"])
    saved = scoped.update_admin_class(one.id, {"class_name": "新名称", "ownership_version": 1})
    assert saved["ownership_version"] == 2
    with pytest.raises(ConflictError):
        scoped.update_admin_class(one.id, {"class_name": "过期", "ownership_version": 1})
    assert (
        db.scalar(
            select(AuditLog).where(AuditLog.action == "academic.admin_class.update")
        ).after_json["college_id"]
        == a["id"]
    )
    config.revoke_grant(admin, int(a["id"]), int(delegation["id"]), 1)
    with pytest.raises(NotFoundError):
        scoped.list_rows("administrative_classes", PageParams(1, 20))


def test_student_list_follows_verified_class_not_legacy_text(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, _, _, student_a, _ = records(db, a, b)
    grant(config, admin, teacher, a, ["student.read"])
    result = service(db, teacher, a["id"]).list_rows("students", PageParams(1, 20))
    assert result["total"] == 1
    assert result["items"][0]["id"] == str(student_a.id)


def test_class_optional_fields_can_clear_but_name_cannot_be_null(campus):
    from app.core.exceptions import AppError

    config, db, admin, teacher, a, b = campus
    one, *_ = records(db, a, b)
    one.grade_year = 2026
    db.commit()
    grant(config, admin, teacher, a, ["academic.manage"])
    scoped = service(db, teacher, a["id"])
    saved = scoped.update_admin_class(one.id, {"grade_year": None, "ownership_version": 1})
    assert saved["grade_year"] is None
    with pytest.raises(AppError):
        scoped.update_admin_class(one.id, {"class_name": None, "ownership_version": 2})


def test_qualification_read_does_not_auto_create_accounts_or_roles(campus):
    from app.modules.academic.models import VolunteerQualification
    from app.modules.identity.models import UserAccount, UserRole

    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, student_a, student_b = records(db, a, b)
    large_actor = UserAccount(id=9007199254740993, display_name="大标识测试账号", status="ACTIVE")
    db.add(large_actor)
    db.flush()
    db.add_all(
        [
            VolunteerQualification(
                semester_id=teaching.semester_id,
                student_id=student_a.id,
                college_id=int(a["id"]),
                enabled=True,
                created_by=large_actor.id,
            ),
            VolunteerQualification(
                semester_id=teaching.semester_id, student_id=student_b.id,
                college_id=int(b["id"]), enabled=True
            ),
        ]
    )
    db.commit()
    grant(config, admin, teacher, a, ["volunteer.read"])
    before_accounts = list(db.scalars(select(UserAccount.id)))
    before_roles = list(db.execute(select(UserRole.user_id, UserRole.role_id)))
    result = service(db, teacher, a["id"]).list_rows(
        "qualifications", PageParams(1, 20), semester_id=teaching.semester_id
    )
    assert result["total"] == 1
    assert result["items"][0]["student_id"] == str(student_a.id)
    assert result["items"][0]["created_by"] == "9007199254740993"
    assert list(db.scalars(select(UserAccount.id))) == before_accounts
    assert list(db.execute(select(UserRole.user_id, UserRole.role_id))) == before_roles


def test_explicit_scope_is_required_and_unknown_resource_never_means_all(campus):
    from app.modules.academic.scoped_repository import ScopedAcademicRepository
    from app.modules.identity.resource_scope import ResourceScope

    _, db, admin, _, a, _ = campus
    with pytest.raises(ValueError):
        ResourceScope(admin.id, 0, "academic.read", 1)
    repo = ScopedAcademicRepository(db, ResourceScope(admin.id, int(a["id"]), "academic.read", 1))
    with pytest.raises(PermissionDeniedError):
        repo.page("user_accounts", PageParams(1, 20))


def test_repository_cannot_reuse_type_configuration_scope_for_students(campus):
    from app.modules.academic.scoped_repository import ScopedAcademicRepository
    from app.modules.identity.resource_scope import ResourceScope

    _, db, admin, _, a, _ = campus
    repo = ScopedAcademicRepository(
        db, ResourceScope(admin.id, int(a["id"]), "academic.course_type.read", 1)
    )
    with pytest.raises(PermissionDeniedError):
        repo.page("students", PageParams(1, 20))


def test_http_scoped_read_write_and_old_url_gate(campus, monkeypatch):
    from dataclasses import replace

    from app.core.config import get_settings
    from app.core.database import get_db
    from app.core.exceptions import AppError
    from app.modules.academic.router import router as old_router
    from app.modules.academic.scoped_router import router
    from app.modules.academic.scoped_write_router import router as write_router
    from app.modules.identity.deps import get_current_user
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    config, db, admin, teacher, a, b = campus
    _, two, _, _, _, _, _ = records(db, a, b)
    grant(config, admin, teacher, a, ["academic.read", "academic.manage"])
    grant(config, admin, teacher, b, ["academic.read"])
    settings = get_settings()
    monkeypatch.setattr(settings, "campus_configuration_enabled", True)
    monkeypatch.setattr(settings, "campus_academic_scoped_enabled", True)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(write_router, prefix="/api/v1")
    app.include_router(old_router, prefix="/api/v1/academic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: teacher

    @app.exception_handler(AppError)
    async def handle(request: Request, error: AppError):
        return JSONResponse({"code": error.code.value}, status_code=error.http_status)

    with TestClient(app) as client:
        base = f"/api/v1/colleges/{a['id']}/academic/administrative-classes"
        first_page = client.get(base).json()["data"]
        assert first_page["total"] == 1 and first_page["page_size"] == 50
        second_page = client.get(base, params={"page": 2, "page_size": 50}).json()["data"]
        assert second_page["items"] == [] and second_page["total"] == 1
        assert client.get(base, params={"student_ids": -1}).status_code == 422
        assert client.get(f"{base}/{two.id}").status_code == 404
        assert client.get("/api/v1/academic/administrative-classes").status_code == 403
        assert (
            client.post(
                base, json={"class_code": "FAKE", "class_name": "越院", "college_id": b["id"]}
            ).status_code
            == 422
        )
        row = client.post(base, json={"class_code": "NEW", "class_name": "新班"}).json()["data"]
        assert row["college_id"] == a["id"]
        assert (
            client.patch(
                f"{base}/{row['id']}", json={"class_name": "改名", "ownership_version": 1}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"{base}/{row['id']}", json={"class_name": "旧写", "ownership_version": 1}
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/v1/colleges/{b['id']}/academic/administrative-classes",
                json={"class_code": "NO", "class_name": "越院"},
            ).status_code
            == 403
        )
        # 单独验证共享只读旧目录和关闭开关后的原接口兼容性。
        app.dependency_overrides[get_current_user] = lambda: replace(
            admin, permissions=["academic.read"]
        )
        assert client.get("/api/v1/academic/semesters").status_code == 200
        assert client.get("/api/v1/academic/administrative-classes").status_code == 403
        monkeypatch.setattr(settings, "campus_academic_scoped_enabled", False)
        assert client.get("/api/v1/academic/administrative-classes").status_code == 200
        assert client.get(base).status_code == 503


def test_master_timetable_loads_with_in_memory_index(campus):
    from app.modules.academic.models import TeachingClassStudent
    from app.modules.academic.scoped_timetable import master_timetable

    config, db, admin, teacher, a, b = campus
    one, two, unknown, teaching, schedule, student_a, student_b = records(db, a, b)
    one.head_teacher = "郑班主任"
    teaching.teacher_name = "张授课老师"
    db.add(TeachingClassStudent(teaching_class_id=teaching.id, student_id=student_a.id))
    db.commit()
    grant(config, admin, teacher, a, ["academic.read"])
    scoped = service(db, teacher, a["id"])
    result = master_timetable(scoped, schedule.semester_id)
    assert result["total"] >= 1
    item = next(r for r in result["items"] if r["id"] == str(schedule.id))
    assert item["teaching_class_id"] == str(teaching.id)
    assert item["teacher_name"] == "张授课老师"
    assert item["head_teacher"] == "郑班主任"
    assert one.class_name in item["administrative_classes"]


def test_master_timetable_page_has_full_count_and_only_builds_page_rosters(campus):
    from app.modules.academic.models import CourseSchedule, CourseScheduleWeek
    from app.modules.academic.scoped_timetable import master_timetable

    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, schedule, *_ = records(db, a, b)
    for i in range(61):
        row = CourseSchedule(
            semester_id=schedule.semester_id,
            teaching_class_id=teaching.id,
            college_id=int(a["id"]),
            weekday=i % 7 + 1,
            start_period=1,
            end_period=2,
            status="ACTIVE",
        )
        db.add(row)
        db.flush()
        db.add(CourseScheduleWeek(schedule_id=row.id, week_no=i // 7 + 1))
    db.commit()
    grant(config, admin, teacher, a, ["academic.read"])
    scoped = service(db, teacher, a["id"])
    first = master_timetable(scoped, schedule.semester_id, params=PageParams(1, 50))
    second = master_timetable(scoped, schedule.semester_id, params=PageParams(2, 50))
    assert first["total"] == second["total"] == 62
    assert len(first["items"]) == 50 and len(second["items"]) == 12
    assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
