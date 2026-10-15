"""正式名单的批量日期索引；调用方先验证教学班范围，不使用个人显示课表。"""

from collections import defaultdict
from datetime import date

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.modules.academic.enrollment_models import (
    CourseParticipation,
    StudentEnrollment,
    TeachingClassAudience,
)
from app.modules.academic.models import Student, TeachingClassStudent


class RosterIndex:
    def __init__(
        self,
        db: Session,
        teaching_class_ids: list[int],
        *,
        lock=False,
        student_ids: set[int] | None = None,
    ):
        self.ids = set(teaching_class_ids)
        self.audiences: dict[int, set[int]] = defaultdict(set)
        self.dated: dict[int, list[CourseParticipation]] = defaultdict(list)
        self.dated_ids: dict[int, set[int]] = defaultdict(set)
        self.legacy: dict[int, set[int]] = defaultdict(set)
        self.enrollments: dict[int, list[StudentEnrollment]] = defaultdict(list)

        def rows(stmt):
            if lock:
                stmt = stmt.with_for_update()
            return db.execute(stmt.execution_options(populate_existing=True))

        for tid, cid in rows(
            select(
                TeachingClassAudience.teaching_class_id,
                TeachingClassAudience.administrative_class_id,
            ).where(TeachingClassAudience.teaching_class_id.in_(self.ids))
        ):
            self.audiences[tid].add(cid)
        for member in rows(
            select(CourseParticipation).where(
                CourseParticipation.teaching_class_id.in_(self.ids),
                CourseParticipation.student_id.in_(student_ids)
                if student_ids is not None
                else true(),
            )
        ).scalars():
            self.dated[member.teaching_class_id].append(member)
            self.dated_ids[member.teaching_class_id].add(member.student_id)
        for tid, sid in rows(
            select(TeachingClassStudent.teaching_class_id, TeachingClassStudent.student_id).where(
                TeachingClassStudent.teaching_class_id.in_(self.ids),
                TeachingClassStudent.student_id.in_(student_ids)
                if student_ids is not None
                else true(),
            )
        ):
            if sid not in self.dated_ids[tid] and not self.audiences[tid]:
                self.legacy[tid].add(sid)
        candidates = set().union(*self.dated_ids.values(), *self.legacy.values())
        class_ids = set().union(*self.audiences.values())
        if class_ids:
            historical = select(StudentEnrollment.student_id).where(
                StudentEnrollment.administrative_class_id.in_(class_ids)
            )
            candidates.update(
                rows(
                    select(Student.id).where(
                        Student.id.in_(historical) | Student.administrative_class_id.in_(class_ids),
                        Student.id.in_(student_ids) if student_ids is not None else true(),
                    )
                ).scalars()
            )
        self.students = list(
            rows(select(Student).where(Student.id.in_(candidates)).order_by(Student.id)).scalars()
        )
        for enrollment in rows(
            select(StudentEnrollment)
            .where(StudentEnrollment.student_id.in_(candidates))
            .order_by(StudentEnrollment.effective_from.desc(), StudentEnrollment.revision.desc())
        ).scalars():
            self.enrollments[enrollment.student_id].append(enrollment)

    def for_personal_timetable(self, on_date: date) -> dict[int, list[Student]]:
        """个人显示可投影迁移基线之前的整班课表，不作为历史学籍证据。

        仅适用尚未核实历史、没有任何变更的单一迁移基线。正式名单调用 at()，
        选修课的带日期参与记录不放宽，已核实或转班等真实历史不投影。
        """
        result = self.at(on_date)
        for student in self.students:
            timeline = self.enrollments[student.id]
            if student.status != "ACTIVE" or len(timeline) != 1:
                continue
            baseline = timeline[0]
            if (
                baseline.superseded
                or baseline.historical_confirmed
                or baseline.revision != 0
                or baseline.status != "ENROLLED"
                or baseline.effective_to is not None
                or baseline.effective_from <= on_date
                or (baseline.snapshot or {}).get("origin") != "MIGRATION_CURRENT_ONLY"
                or baseline.administrative_class_id != student.administrative_class_id
            ):
                continue
            for tid in self.ids:
                if (
                    baseline.administrative_class_id in self.audiences[tid]
                    and student.id not in self.dated_ids[tid]
                ):
                    result[tid].append(student)
        return result

    def at(self, on_date: date) -> dict[int, list[Student]]:
        result: dict[int, list[Student]] = {tid: [] for tid in self.ids}
        explicit = {
            tid: {
                m.student_id
                for m in members
                if m.effective_from <= on_date
                and (m.effective_to is None or on_date < m.effective_to)
            }
            for tid, members in self.dated.items()
        }
        for student in self.students:
            timeline = self.enrollments[student.id]
            enrollment = next(
                (
                    e
                    for e in timeline
                    if not e.superseded
                    and e.effective_from <= on_date
                    and (e.effective_to is None or on_date < e.effective_to)
                ),
                None,
            )
            if enrollment is not None:
                if enrollment.status != "ENROLLED":
                    continue
                class_id = enrollment.administrative_class_id
            else:
                if timeline or student.status != "ACTIVE":
                    continue
                class_id = student.administrative_class_id
            for tid in self.ids:
                if (
                    student.id in explicit.get(tid, set())
                    or student.id in self.legacy[tid]
                    or class_id in self.audiences[tid]
                ):
                    result[tid].append(student)
        return result
