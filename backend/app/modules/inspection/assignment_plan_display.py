"""Display-only projections for an already authorized, frozen assignment preview."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.academic.models import AdministrativeClass, Semester, Student
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionTask
from app.modules.volunteer.models import VolunteerGroup


def plan_display(
    db: Session,
    semester: Semester,
    group: VolunteerGroup,
    tasks: Sequence[InspectionTask],
    assignments: Mapping[int, int],
) -> dict[str, Any]:
    # Only proposed assignees are projected; never return the complete candidate pool.
    volunteers = {}
    if assignments:
        statement = (
            select(
                UserAccount.id,
                UserAccount.display_name,
                Student.name,
                Student.student_no,
                AdministrativeClass.class_name,
            )
            .outerjoin(Student, Student.id == UserAccount.student_id)
            .outerjoin(
                AdministrativeClass, AdministrativeClass.id == Student.administrative_class_id
            )
            .where(UserAccount.id.in_(set(assignments.values())))
        )
        for uid, account_name, name, number, class_name in db.execute(statement):
            volunteers[str(uid)] = {
                "name": name or account_name,
                "student_no": number,
                "administrative_class_name": class_name,
            }
    return {
        "group_name": group.name,
        "semester_name": semester.name,
        "tasks": {
            str(task.id): {
                "course_name": task.course_name_snapshot,
                "teaching_class_name": task.class_name_snapshot,
                "classroom": task.classroom_snapshot,
                "inspection_date": task.inspection_date.isoformat(),
                "start_period": task.start_period,
                "end_period": task.end_period,
                "time_snapshot": task.time_snapshot,
            }
            for task in tasks
        },
        "volunteers": volunteers,
    }
