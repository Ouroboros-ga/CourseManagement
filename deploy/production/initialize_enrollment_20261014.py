"""Confirmed initial organization and account binding; current-only ownership proof.

Run once with migration credentials after e001, from the locally built release.
No other label is treated as an alias; unknown ownership remains school-managed.
"""

import json

from app.core.database import get_session_factory
from app.modules.academic.college_service import CollegeService
from app.modules.academic.enrollment_models import (
    TeacherCollegeBinding,
    TeachingClassAudience,
)
from app.modules.academic.models import AdministrativeClass
from app.modules.identity.bootstrap_admin_management import (
    grant_administrator_management,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser, IdentityService
from app.modules.organization.models import College, School
from app.modules.organization.ownership import OwnershipService
from app.modules.organization.service import CampusService
from sqlalchemy import select


def main():
    with get_session_factory()() as db:
        from app.modules.identity.seed import sync_registry

        sync_registry(db)
        db.commit()
        repo = IdentityRepository(db)
        admin = repo.get_user_by_username("admin")
        if (
            admin is None
            or not admin.is_active
            or "SUPER_ADMIN" not in repo.list_role_codes(admin.id)
        ):
            raise RuntimeError("Confirmed admin unavailable")
        actor = CurrentUser(
            admin.id,
            admin.username,
            admin.display_name,
            admin.status,
            repo.list_role_codes(admin.id),
            repo.list_effective_permissions(admin.id),
        )
        school = db.scalar(select(School))
        campus = CampusService(db)
        if school is None:
            school_result = campus.create_school(
                actor, {"name": "绍兴理工学院", "code": "SXLG"}
            )
            school = db.get(School, int(school_result["id"]))
        if school.name != "绍兴理工学院":
            raise RuntimeError(
                "Existing school differs from confirmed name; no overwrite"
            )
        college = db.scalar(
            select(College).where(
                College.school_id == school.id, College.code == "AI_LOW_ALTITUDE"
            )
        )
        if college is None:
            result = campus.create_college(
                actor,
                school.id,
                {
                    "name": "人工智能学院（低空技术与工程学院）",
                    "code": "AI_LOW_ALTITUDE",
                },
            )
            college = db.get(College, int(result["id"]))
        if (
            college.name != "人工智能学院（低空技术与工程学院）"
            or college.status != "ACTIVE"
        ):
            raise RuntimeError("Existing college differs from confirmation")
        cid = college.id
        test_college = db.scalar(
            select(College).where(
                College.school_id == school.id, College.code == "SOFTWARE_TEST"
            )
        )
        if test_college is None:
            result = campus.create_college(
                actor, school.id, {"name": "软件学院（测试）", "code": "SOFTWARE_TEST"}
            )
            test_college = db.get(College, int(result["id"]))
        if test_college.name != "软件学院（测试）" or test_college.status != "ACTIVE":
            raise RuntimeError("Existing test college differs from confirmation")
        labels = {"人工智能学院": cid, "软件学院": test_college.id}
        mappings = {
            "administrative_class": {
                str(ac.id): str(labels[ac.college])
                for ac in db.scalars(
                    select(AdministrativeClass).where(
                        AdministrativeClass.college.in_(labels)
                    )
                )
            }
        }
        approved_classes = {
            int(key): int(value)
            for key, value in mappings["administrative_class"].items()
        }
        source_classes = {}
        for tcid, acid in db.execute(
            select(
                TeachingClassAudience.teaching_class_id,
                TeachingClassAudience.administrative_class_id,
            )
        ):
            source_classes.setdefault(tcid, set()).add(acid)
        mappings["teaching_class"] = {}
        for tcid, sources in source_classes.items():
            owners = {approved_classes.get(acid) for acid in sources}
            if sources and None not in owners and len(owners) == 1:
                mappings["teaching_class"][str(tcid)] = str(next(iter(owners)))
        ownership = OwnershipService(db)
        preview = ownership.preview(actor, mappings)
        if preview["conflicts"]:
            raise RuntimeError("Ownership proof conflicts; nothing guessed")
        result = ownership.apply(actor, mappings, preview["revision"])
        teacher = repo.get_user_by_id(9)
        if teacher is None or "TEACHER_ADMIN" not in repo.list_role_codes(9):
            raise RuntimeError("Confirmed teacher ID 9 unavailable")
        binding = db.get(TeacherCollegeBinding, 9)
        if binding is None or binding.college_id != cid:
            CollegeService(db).set_teacher_college(
                admin.id, 9, cid, teacher.lock_version, request_id=None
            )
        manager = repo.get_user_by_id(40)
        if manager and "STUDENT_AFFAIRS_MANAGER" in repo.list_role_codes(40):
            from app.modules.academic.enrollment_service import EnrollmentService
            from app.modules.identity.authorization import (
                active_manager_appointment,
                business_today,
            )

            enrollment = (
                EnrollmentService(db).at(manager.student_id, business_today())
                if manager.student_id
                else None
            )
            if (
                enrollment is not None
                and enrollment.status == "ENROLLED"
                and enrollment.college_id in {cid, test_college.id}
                and active_manager_appointment(db, 40, business_today()) is None
            ):
                IdentityService(db).assign_roles(
                    actor_user_id=admin.id,
                    target_user_id=40,
                    desired_codes=repo.list_role_codes(40),
                    expected_version=manager.lock_version,
                    reason="已确认当前学院归属后的负责人任命初始化",
                    request_id=None,
                )
        granted = grant_administrator_management(db, admin.id)
        db.commit()
        print(
            json.dumps(
                {
                    "school": school.name,
                    "college_id": str(cid),
                    "college": college.name,
                    "teacher_id": "9",
                    "administrator": "admin",
                    "platform_grant_changed": granted,
                    "ownership": result,
                    "unconfirmed_label_policy": "KEEP_UNKNOWN",
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
