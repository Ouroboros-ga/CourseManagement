from datetime import date, datetime

import pytest
from app.common.pagination import PageParams
from app.modules.academic.models import Semester
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    InspectionAssignment,
    InspectionTask,
)
from app.modules.inspection.scoped_service import ScopedInspectionService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_management_change_request_page_has_context_and_filters_before_pagination(campus):
    config, db, admin, teacher, a, b = campus
    records(db, a, b)
    source = db.scalar(select(InspectionTask).where(InspectionTask.college_id == int(a["id"])))
    source.course_name_snapshot = "高等数学"
    source.class_name_snapshot = "计算机2601"
    applicant = UserAccount(display_name="志愿者甲", status="ACTIVE")
    db.add(applicant)
    db.flush()
    assignment = InspectionAssignment(
        task_id=source.id,
        volunteer_user_id=applicant.id,
        assign_method="MANUAL",
        assigned_by=admin.id,
    )
    db.add(assignment)
    db.flush()
    for i in range(105):
        db.add(
            AssignmentChangeRequest(
                assignment_id=assignment.id,
                request_user_id=applicant.id,
                status="PENDING",
                reason=f"申请{i}",
            )
        )
    other_sem = Semester(
        code="NEXT",
        name="下一学期",
        first_monday=date(2027, 2, 1),
        start_date=date(2027, 2, 1),
        end_date=date(2027, 7, 1),
        total_weeks=20,
        status="ACTIVE",
    )
    db.add(other_sem)
    db.flush()
    for cid, sid, key in [
        (int(b["id"]), source.semester_id, "foreign"),
        (int(a["id"]), other_sem.id, "next"),
    ]:
        task = InspectionTask(
            task_key=key,
            semester_id=sid,
            college_id=cid,
            inspection_date=source.inspection_date,
            week_no=2,
            inspection_type="COURSE",
            start_period=1,
            end_period=2,
        )
        db.add(task)
        db.flush()
        assignee = InspectionAssignment(
            task_id=task.id,
            volunteer_user_id=applicant.id,
            assigned_by=admin.id,
            assign_method="MANUAL",
        )
        db.add(assignee)
        db.flush()
        db.add(
            AssignmentChangeRequest(
                assignment_id=assignee.id,
                request_user_id=applicant.id,
                status="PENDING",
                reason=key,
            )
        )
    db.commit()
    service = ScopedInspectionService(db, admin, int(a["id"]))
    first = service.list_change_requests(
        admin, PageParams(1, 50), status="PENDING", semester_id=source.semester_id
    )
    second = service.list_change_requests(
        admin, PageParams(2, 50), status="PENDING", semester_id=source.semester_id
    )
    assert first["total"] == second["total"] == 105
    assert len(first["items"]) == len(second["items"]) == 50
    assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
    item = first["items"][0]
    assert item["requester_name"] == "志愿者甲"
    assert item["course_name"] == "高等数学"
    assert item["class_name"] == "计算机2601"
    assert item["can_process"] is True
    assert int(first["items"][0]["id"]) > int(second["items"][0]["id"])
    source.exception_reported_at = datetime.now()
    db.commit()
    blocked = service.list_change_requests(
        admin, PageParams(1, 50), status="PENDING", semester_id=source.semester_id
    )
    assert blocked["items"][0]["can_process"] is False

    source.exception_reported_at = None
    db.commit()
    from app.modules.inspection.schemas import ChangeRequestReviewRequest

    version = source.lock_version
    service.review_change_request(
        admin,
        int(item["id"]),
        ChangeRequestReviewRequest(decision="REJECTED", comment="保留原排班"),
        None,
    )
    assert db.get(InspectionTask, source.id).lock_version == version + 1
    rejected = service.list_change_requests(
        admin, PageParams(1, 50), status="REJECTED", semester_id=source.semester_id
    )
    assert rejected["total"] == 1
    assert rejected["items"][0]["processor_name"] == "超管"
    db.get(Semester, source.semester_id).status = "ARCHIVED"
    db.commit()
    assert (
        service.list_change_requests(
            admin, PageParams(1, 50), status="REJECTED", semester_id=source.semester_id
        )["total"]
        == 1
    )
