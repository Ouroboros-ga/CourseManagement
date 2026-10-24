"""批量锁定执行日期资格资料；候选×任务循环只做内存判断。"""

from collections import defaultdict

from sqlalchemy import select

from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.volunteer.member_models import VolunteerGroupMember


class EligibilityIndex:
    def __init__(self, db, student_ids, tasks, *, lock=False):
        def rows(statement):
            if lock:
                statement = statement.with_for_update(read=True).execution_options(
                    populate_existing=True
                )
            return db.execute(statement)

        self.timelines = defaultdict(list)
        for row in rows(
            select(StudentEnrollment)
            .where(StudentEnrollment.student_id.in_(student_ids))
            .order_by(StudentEnrollment.effective_from, StudentEnrollment.revision)
        ).scalars():
            self.timelines[row.student_id].append(row)
        self.students = {
            row.id: row
            for row in rows(
                select(
                    Student.id,
                    Student.status,
                    Student.administrative_class_id,
                    AdministrativeClass.college_id,
                )
                .outerjoin(
                    AdministrativeClass, AdministrativeClass.id == Student.administrative_class_id
                )
                .where(Student.id.in_(student_ids))
            )
        }
        self.members = defaultdict(list)
        grouped = [task for task in tasks if task.group_id]
        if grouped:
            for row in rows(
                select(VolunteerGroupMember).where(
                    VolunteerGroupMember.student_id.in_(student_ids),
                    VolunteerGroupMember.group_id.in_({task.group_id for task in grouped}),
                    VolunteerGroupMember.semester_id.in_({task.semester_id for task in grouped}),
                    VolunteerGroupMember.status == "ACTIVE",
                    VolunteerGroupMember.effective_from
                    <= max(task.inspection_date for task in grouped),
                    VolunteerGroupMember.effective_to
                    > min(task.inspection_date for task in grouped),
                )
            ).scalars():
                self.members[row.student_id].append(row)

    def enrollment(self, student_id, day):
        return next(
            (
                row
                for row in reversed(self.timelines[student_id])
                if not row.superseded
                and row.effective_from <= day
                and (row.effective_to is None or day < row.effective_to)
            ),
            None,
        )

    def origin(self, student_id, day):
        enrolled = self.enrollment(student_id, day)
        if enrolled:
            return enrolled.college_id if enrolled.status == "ENROLLED" else None
        student = self.students.get(student_id)
        return (
            student.college_id
            if not self.timelines[student_id] and student and student.status == "ACTIVE"
            else None
        )

    def class_id(self, student_id, day):
        enrolled = self.enrollment(student_id, day)
        if enrolled:
            return enrolled.administrative_class_id if enrolled.status == "ENROLLED" else None
        student = self.students.get(student_id)
        return (
            student.administrative_class_id
            if not self.timelines[student_id] and student and student.status == "ACTIVE"
            else None
        )

    def qualified(self, qualification, day, college_id=None):
        if qualification is None or not qualification.enabled:
            return False
        origin = self.origin(qualification.student_id, day)
        return (
            origin is not None
            and qualification.college_id == origin
            and (college_id is None or college_id == origin)
        )

    @staticmethod
    def _covers(row, task):
        return (
            row.college_id == task.college_id
            and row.group_id == task.group_id
            and row.semester_id == task.semester_id
            and row.effective_from <= task.inspection_date < row.effective_to
        )

    def member_allowed(self, task, student_id):
        return self.origin(student_id, task.inspection_date) == task.college_id and any(
            self._covers(row, task) for row in self.members[student_id]
        )
