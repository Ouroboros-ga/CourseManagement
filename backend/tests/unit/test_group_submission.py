from dataclasses import replace

import pytest
from app.modules.academic.models import Student, VolunteerQualification
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.seed import sync_registry
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.schemas import SubmissionCreateRequest
from app.modules.inspection.service import InspectionService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_legacy_cross_college_assignee_can_finish_existing_task(campus, monkeypatch):
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    sync_registry(db)
    foreign = db.scalar(select(Student).where(Student.student_no == "B"))
    volunteer = UserAccount(display_name="支援志愿者", student_id=foreign.id, status="ACTIVE")
    db.add(volunteer)
    db.flush()
    for code in ("STUDENT", "VOLUNTEER"):
        db.add(
            UserRole(
                user_id=volunteer.id, role_id=db.scalar(select(Role.id).where(Role.code == code))
            )
        )
    db.add(
        VolunteerQualification(
            student_id=foreign.id, semester_id=sem.id, college_id=int(campus[5]["id"]), enabled=True
        )
    )
    db.commit()
    from datetime import date

    from app.modules.volunteer.member_models import VolunteerGroupMember

    db.add(
        VolunteerGroupMember(
            college_id=int(a["id"]),
            group_id=int(group["id"]),
            student_id=foreign.id,
            semester_id=sem.id,
            effective_from=date(2026, 9, 1),
            effective_to=date(2027, 1, 30),
            status="INACTIVE",
        )
    )
    db.commit()
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    request = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "support-submit",
        "require_photo": False,
    }
    generated = sampling.generate(request, sampling.preview(request)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    db.add(
        InspectionAssignment(
            task_id=task.id,
            volunteer_user_id=volunteer.id,
            assign_method="MANUAL",
            assigned_by=admin.id,
        )
    )
    db.commit()
    # 仅验证历史既有受派可履行；不通过已退役的支援能力新建成员或排班。
    if db.get_bind().dialect.name != "mysql":
        from app.modules.report.source_revision import SourceRevisionService

        # SQLite 不验证 MySQL UPSERT；服务器同一用例执行真实源修订写入。
        monkeypatch.setattr(SourceRevisionService, "bump_for_task", lambda *_: None)
    actor = replace(
        admin, id=volunteer.id, roles=["STUDENT", "VOLUNTEER"], permissions=["submission.create"]
    )
    result = InspectionService(db).create_submission(
        actor, task.id, SubmissionCreateRequest(result="NORMAL"), None
    )
    assert result.review_status == "APPROVED"
    attendance = list(
        db.scalars(select(AttendanceRecord).where(AttendanceRecord.task_id == task.id))
    )
    assert [row.student_id for row in attendance] == [own.id]
