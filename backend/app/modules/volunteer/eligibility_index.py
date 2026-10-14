"""批量锁定执行日期资格资料；候选×任务循环只做内存判断。"""

from collections import defaultdict

from sqlalchemy import select

from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.inspection.models import InspectionTask, TaskRosterMember
from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport


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
        self.members, self.supports = defaultdict(list), defaultdict(list)
        grouped = [task for task in tasks if task.group_id]
        if grouped:
            for model, destination in [
                (VolunteerGroupMember, self.members),
                (VolunteerGroupSupport, self.supports),
            ]:
                for row in rows(
                    select(model).where(
                        model.student_id.in_(student_ids),
                        model.group_id.in_({task.group_id for task in grouped}),
                        model.semester_id.in_({task.semester_id for task in grouped}),
                        model.status == "ACTIVE",
                        model.effective_from <= max(task.inspection_date for task in grouped),
                        model.effective_to > min(task.inspection_date for task in grouped),
                    )
                ).scalars():
                    destination[row.student_id].append(row)
        self.task_classes = defaultdict(set)
        if any(
            (row.scope_snapshot or {}).get("class_mode") == "SPECIFIC"
            for supports in self.supports.values()
            for row in supports
        ):
            for task_id, class_id in rows(
                select(TaskRosterMember.task_id, TaskRosterMember.administrative_class_id_snapshot)
                .join(InspectionTask, InspectionTask.id == TaskRosterMember.task_id)
                .where(
                    TaskRosterMember.task_id.in_([task.id for task in grouped if task.id]),
                    TaskRosterMember.roster_version == InspectionTask.roster_version,
                )
            ):
                self.task_classes[task_id].add(class_id)

    @staticmethod
    def support_covers_scope(support, task, classes):
        scope = support.scope_snapshot or {}
        if str(task.course_type_id_snapshot) not in scope.get("course_type_ids", []):
            return False
        if scope.get("class_mode") == "ALL_AUTHORIZED":
            return True
        classes = set(classes)
        if task.administrative_class_id is not None:
            classes.add(task.administrative_class_id)
        return (
            bool(classes)
            and None not in classes
            and classes.issubset({int(value) for value in scope.get("class_ids", [])})
        )

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
        origin = self.origin(student_id, task.inspection_date)
        return (
            origin is not None
            and any(self._covers(row, task) for row in self.members[student_id])
            and (
                origin == task.college_id
                or any(
                    self._covers(row, task)
                    and self.support_covers_scope(row, task, self.task_classes[task.id])
                    for row in self.supports[student_id]
                )
            )
        )
