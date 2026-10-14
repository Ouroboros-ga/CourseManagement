"""Acceptance without printing credentials or personal records. Live mode only reads."""

import json
import os
import sys

from app.core.database import get_session_factory
from app.main import create_app
from app.modules.academic.enrollment_models import College, TeacherCollegeBinding
from app.modules.academic.enrollment_schemas import EnrollmentChangeRequest
from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.repository import IdentityRepository
from sqlalchemy import select, text
from sqlalchemy.engine import make_url


def main():
    clone = len(sys.argv) > 1 and sys.argv[1] == "clone"
    database = make_url(os.environ["DATABASE_URL"]).database
    assert database.endswith("_test") if clone else database == "course_management"
    with get_session_factory()() as db:
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version")) == "f26a1014e001"
        )
        repo = IdentityRepository(db)
        admin = repo.get_user_by_username("admin")
        assert (
            admin
            and "administrator_account.manage"
            in repo.list_effective_permissions(admin.id)
        )
        teacher = db.get(TeacherCollegeBinding, 9)
        assert (
            teacher
            and db.get(College, teacher.college_id).name
            == "人工智能学院（低空技术与工程学院）"
        )
        assert "administrator_account.manage" not in repo.list_effective_permissions(9)
        test = db.scalar(select(College).where(College.code == "SOFTWARE_TEST"))
        assert (
            test
            and db.scalar(
                select(text("COUNT(*)"))
                .select_from(AdministrativeClass)
                .where(AdministrativeClass.college_id == test.id)
            )
            == 2
        )
        baseline = db.scalar(
            text(
                "SELECT COUNT(*) FROM student_enrollment WHERE revision=0 AND historical_confirmed=0"
            )
        )
        assert baseline == db.scalar(text("SELECT COUNT(*) FROM student"))
        assert (
            db.scalar(
                text("SELECT COUNT(*) FROM student WHERE history_until IS NOT NULL")
            )
            == 0
        )
        paths = create_app().openapi()["paths"]
        assert "/api/v1/administrator-accounts" in paths
        assert "/api/v1/academic/student-data/preview-file" in paths
        assert "/api/v1/academic/enrollment-handoff/tasks" in paths
        summary = {
            "checks": [
                "platform_grant",
                "teacher_single_college",
                "test_college_two_classes_preserved",
                "current_only_baselines",
                "lifecycle_routes",
            ],
            "students": baseline,
            "staff_college": str(teacher.college_id),
            "test_college": str(test.id),
            "mode": "clone" if clone else "live_readonly",
        }
        if clone:
            # Synthetic change against a rollback-capable dedicated clone, never live.
            from datetime import timedelta

            college_id = teacher.college_id
            old = db.scalar(
                select(AdministrativeClass).where(
                    AdministrativeClass.college_id == college_id
                )
            )
            target = AdministrativeClass(
                class_code="ENROLLMENT_ACCEPTANCE_ONLY",
                class_name="隔离验收班",
                college_id=college_id,
            )
            db.add(target)
            db.flush()
            student = Student(
                student_no="ENROLLMENT_ACCEPTANCE_ONLY",
                name="隔离验收学生",
                administrative_class_id=old.id,
            )
            db.add(student)
            db.flush()
            sid, target_id, original_class = student.id, target.id, old.id
            db.commit()
            service = EnrollmentService(db)
            when = service.today + timedelta(days=7)
            result = service.commit(
                admin.id,
                sid,
                EnrollmentChangeRequest(
                    kind="TRANSFER",
                    effective_date=when,
                    target_class_id=target_id,
                    lock_version=0,
                    idempotency_key="clone-transfer",
                ),
                request_id=None,
            )
            assert result["state"] == "SCHEDULED"
            assert db.get(Student, sid).administrative_class_id == original_class
            service.cancel(admin.id, sid, int(result["id"]), result["lock_version"])
            assert service.at(sid, when).administrative_class_id == original_class
            summary["checks"].append(
                "mysql_future_change_cancel_and_current_projection"
            )
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
