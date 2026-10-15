"""学籍异动、日期预览、历史归档与任务/身份交接，同事务写入。"""

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, ErrorCode, NotFoundError, PermissionDeniedError
from app.modules.academic.enrollment_models import (
    CourseParticipation,
    EnrollmentChange,
    StudentEnrollment,
)
from app.modules.academic.enrollment_schemas import EnrollmentChangeRequest
from app.modules.academic.models import (
    AdministrativeClass,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClassStudent,
    VolunteerQualification,
)
from app.modules.audit.models import AuditLog
from app.modules.identity.role_scope import require_resource_scope, resolve_scope
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.inspection.models import (
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    TaskDeadlineAssessment,
    TaskRosterMember,
    TaskRosterVersion,
)

STATES = {
    "TRANSFER": "ENROLLED",
    "RETURN": "ENROLLED",
    "SUSPEND": "SUSPENDED",
    "GRADUATE": "GRADUATED",
    "WITHDRAW": "WITHDRAWN",
}


def ten_years_after(value: date) -> date:
    try:
        return value.replace(year=value.year + 10)
    except ValueError:
        return value.replace(year=value.year + 10, day=28)


def class_snapshot(ac: AdministrativeClass | None) -> dict[str, Any]:
    from sqlalchemy.orm import object_session

    from app.modules.organization.models import College

    db = object_session(ac) if ac else None
    college = db.get(College, ac.college_id) if db and ac and ac.college_id else None
    return {
        "class_id": str(ac.id) if ac else None,
        "class_name": ac.class_name if ac else None,
        "class_code": ac.class_code if ac else None,
        "college_id": str(ac.college_id) if ac and ac.college_id else None,
        "college_name": college.name if college else ac.college if ac else None,
        "major_name": ac.major_name if ac else None,
        "grade_year": ac.grade_year if ac else None,
    }


class EnrollmentService:
    def __init__(self, session: Session, *, today: date | None = None, college_id: int | None = None):
        self.db = session
        self.college_id = college_id
        from app.modules.identity.role_scope import business_today
        self.today = today or business_today()

    def _required_enrollment(self, enrollment_id: int) -> StudentEnrollment:
        row = self.db.get(StudentEnrollment, enrollment_id)
        if row is None:
            raise ConflictError(message="学籍关联记录不完整，请管理员检查")
        return row

    def _lock_semesters(self) -> None:
        # 沿用排班/导入的账号→学期→学生→任务锁序。
        self.db.execute(select(Semester.id).order_by(Semester.id).with_for_update()).all()

    def has_timeline(self, student_id: int) -> bool:
        return (
            self.db.scalar(
                select(StudentEnrollment.id)
                .where(StudentEnrollment.student_id == student_id)
                .limit(1)
            )
            is not None
        )

    def at(self, student_id: int, on_date: date, *, lock: bool = False) -> StudentEnrollment | None:
        statement = (
            select(StudentEnrollment)
            .where(
                StudentEnrollment.student_id == student_id,
                StudentEnrollment.superseded.is_(False),
                StudentEnrollment.effective_from <= on_date,
                or_(
                    StudentEnrollment.effective_to.is_(None),
                    StudentEnrollment.effective_to > on_date,
                ),
            )
            .order_by(StudentEnrollment.effective_from.desc())
            .execution_options(populate_existing=True)
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update(read=True)
        return self.db.scalar(statement)

    def _baseline(self, student: Student) -> StudentEnrollment:
        existing = self.db.scalar(
            select(StudentEnrollment)
            .where(
                StudentEnrollment.student_id == student.id, StudentEnrollment.superseded.is_(False)
            )
            .order_by(StudentEnrollment.effective_from)
            .limit(1)
        )
        if existing:
            return existing
        ac = (
            self.db.get(AdministrativeClass, student.administrative_class_id)
            if student.administrative_class_id
            else None
        )
        row = StudentEnrollment(
            student_id=student.id,
            administrative_class_id=student.administrative_class_id,
            college_id=ac.college_id if ac else None,
            effective_from=self.today,
            status="ENROLLED" if student.status == "ACTIVE" else "SUSPENDED",
            revision=0,
            historical_confirmed=False,
            snapshot=class_snapshot(ac),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _source(self, student: Student, on_date: date) -> StudentEnrollment:
        source = self.at(student.id, on_date)
        if source is not None:
            return source
        first = self._baseline(student)
        source = self.at(student.id, on_date)
        if source is not None:
            return source
        if (
            not first.historical_confirmed
            and first.revision == 0
            and on_date <= first.effective_from
        ):
            return first
        raise ConflictError(message="该日期学籍未知，不能用当前班级推断历史；请先核实历史归属")

    def _check(
        self,
        actor_id: int,
        student: Student,
        source: StudentEnrollment,
        body: EnrollmentChangeRequest,
    ) -> AdministrativeClass | None:
        scope = resolve_scope(self.db, actor_id, "student.manage")
        require_resource_scope(scope, source.college_id)
        current = self.at(student.id, self.today)
        if current is not None:
            require_resource_scope(scope, current.college_id)
        if student.lock_version != body.lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "学生资料或学籍已变化，请重新预览")
        target = (
            self.db.get(AdministrativeClass, body.target_class_id) if body.target_class_id else None
        )
        if body.target_class_id and (target is None or target.status != "ACTIVE"):
            raise NotFoundError("目标班级不存在或已停用")
        if target:
            require_resource_scope(scope, target.college_id)
        if scope.kind == "SELF":
            raise PermissionDeniedError("学生不能自行修改正式学籍")
        if body.kind == "TRANSFER" and source.status != "ENROLLED":
            raise ConflictError(message="非在读学生应办理复学，不能通过转班重新启用")
        if body.kind == "RETURN" and source.status == "ENROLLED":
            raise ConflictError(message="在读学生无需复学")
        if body.correct_existing and body.effective_date > self.today:
            raise ConflictError(message="未来计划应先撤销再重新办理，不能作为历史更正")
        if (
            self.db.scalar(
                select(EnrollmentChange.id)
                .where(
                    EnrollmentChange.student_id == student.id,
                    EnrollmentChange.state != "CANCELED",
                    EnrollmentChange.effective_date > body.effective_date,
                )
                .limit(1)
            )
            is not None
            and not body.correct_existing
        ):
            raise ConflictError(message="存在后续学籍异动，须先处理后续计划；不会自动覆盖后续事实")
        if (
            source.historical_confirmed
            and body.effective_date == source.effective_from
            and not body.correct_existing
        ):
            raise ConflictError(message="同日已有学籍事实，请使用更正流程核对后处理")
        return target

    def preview(
        self, actor_id: int, student_id: int, body: EnrollmentChangeRequest
    ) -> dict[str, Any]:
        student = self.db.get(Student, student_id)
        if student is None:
            raise NotFoundError("学生不存在")
        # 预览只读，不建立迁移基线或写任何变更。
        source = self.at(student_id, body.effective_date)
        if source is None:
            source = self.db.scalar(
                select(StudentEnrollment)
                .where(
                    StudentEnrollment.student_id == student_id,
                    StudentEnrollment.superseded.is_(False),
                )
                .order_by(StudentEnrollment.effective_from)
                .limit(1)
            )
            if source is None:
                ac = (
                    self.db.get(AdministrativeClass, student.administrative_class_id)
                    if student.administrative_class_id
                    else None
                )
                source = StudentEnrollment(
                    student_id=student.id,
                    administrative_class_id=student.administrative_class_id,
                    college_id=ac.college_id if ac else None,
                    effective_from=self.today,
                    status="ENROLLED" if student.status == "ACTIVE" else "SUSPENDED",
                    revision=0,
                    historical_confirmed=False,
                    snapshot=class_snapshot(ac),
                )
            elif source.historical_confirmed:
                raise ConflictError(message="该日期学籍未知，请先核实历史")
        target = self._check(actor_id, student, source, body)
        return {
            "student_id": str(student.id),
            "student_no": student.student_no,
            "lock_version": student.lock_version,
            "source": source.snapshot,
            "source_history_confirmed": source.historical_confirmed,
            "target": class_snapshot(target) if target else source.snapshot,
            "effective_date": body.effective_date.isoformat(),
            "kind": body.kind,
            "impact": self._impact(student_id, body.effective_date),
            "warnings": [
                "已完成、已开始及已有截止考核的任务保留原名单；异议有效期不会因异动延长",
                "旧名单不得覆盖本次学籍；选修课仅按明确退课清单结束",
            ],
        }

    def _impact(self, student_id: int, on_date: date) -> dict[str, Any]:
        users = list(
            self.db.scalars(select(UserAccount.id).where(UserAccount.student_id == student_id))
        )
        tasks = list(
            self.db.scalars(
                select(TaskRosterMember.task_id)
                .join(InspectionTask, InspectionTask.id == TaskRosterMember.task_id)
                .where(
                    TaskRosterMember.student_id == student_id,
                    TaskRosterMember.roster_version == InspectionTask.roster_version,
                    InspectionTask.inspection_date >= on_date,
                )
            )
        )
        return {
            "bound_user_ids": [str(i) for i in users],
            "existing_roster_task_ids": [str(i) for i in sorted(set(tasks))],
            "historical_facts_policy": "KEEP",
            "binding_policy": "KEEP",
            "elective_policy": "EXPLICIT_LEAVE_ONLY",
        }

    def commit(
        self,
        actor_id: int,
        student_id: int,
        body: EnrollmentChangeRequest,
        *,
        request_id: str | None,
        _owns_transaction: bool = True,
        _refresh_task_state: bool = True,
    ) -> dict[str, Any]:
        if _owns_transaction:
            from app.modules.academic.lifecycle_transaction import begin_lifecycle_write

            begin_lifecycle_write(self.db)
        # 身份锚点先锁，学生锁串行化时间轴、版本和绑定交接。
        ids = set(
            self.db.scalars(select(UserAccount.id).where(UserAccount.student_id == student_id))
        ) | {actor_id}
        repo = IdentityRepository(self.db)
        for uid in sorted(ids):
            repo.get_user_by_id_for_update(uid)
        self._lock_semesters()
        student = self.db.scalar(
            select(Student)
            .where(Student.id == student_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if student is None:
            raise NotFoundError("学生不存在")
        payload_hash = hashlib.sha256(
            body.model_dump_json(exclude={"lock_version"}).encode()
        ).hexdigest()
        if body.idempotency_key:
            old = self.db.scalar(
                select(EnrollmentChange).where(
                    EnrollmentChange.student_id == student_id,
                    EnrollmentChange.idempotency_key == body.idempotency_key,
                )
            )
            if old:
                scope = resolve_scope(self.db, actor_id, "student.manage")
                require_resource_scope(
                    scope, self._required_enrollment(old.target_enrollment_id).college_id
                )
                if old.payload_hash != payload_hash:
                    raise ConflictError(
                        ErrorCode.IDEMPOTENCY_KEY_REUSED, "幂等键已用于不同的异动内容"
                    )
                return self._view(student, old)
        source = self._source(student, body.effective_date)
        class_ids = {
            cid
            for cid in (
                student.administrative_class_id,
                source.administrative_class_id,
                body.target_class_id,
            )
            if cid is not None
        }
        self.db.execute(
            select(AdministrativeClass)
            .where(AdministrativeClass.id.in_(class_ids))
            .order_by(AdministrativeClass.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        target = self._check(actor_id, student, source, body)
        before = {
            "class_id": str(student.administrative_class_id)
            if student.administrative_class_id
            else None,
            "status": student.status,
            "lock_version": student.lock_version,
        }
        interval_end = source.effective_to
        if body.effective_date <= source.effective_from:
            source.superseded = True
        else:
            source.effective_to = body.effective_date
        revision = student.lock_version + 1
        row = StudentEnrollment(
            student_id=student.id,
            administrative_class_id=target.id if target else source.administrative_class_id,
            college_id=target.college_id if target else source.college_id,
            effective_from=body.effective_date,
            effective_to=interval_end,
            status=STATES[body.kind],
            revision=revision,
            historical_confirmed=True,
            snapshot=class_snapshot(target) if target else dict(source.snapshot),
        )
        self.db.add(row)
        self.db.flush()
        event = EnrollmentChange(
            student_id=student.id,
            actor_user_id=actor_id,
            kind=body.kind,
            effective_date=body.effective_date,
            source_enrollment_id=source.id,
            target_enrollment_id=row.id,
            state="SCHEDULED" if body.effective_date > self.today else "APPLIED",
            idempotency_key=body.idempotency_key,
            payload_hash=payload_hash,
            reason=body.reason,
            impact=self._impact(student.id, body.effective_date),
        )
        self.db.add(event)
        student.lock_version = revision
        event.impact = {
            **event.impact,
            "ended_participations": self._end_electives(student.id, body),
            "source_interval_before": {
                "from": source.effective_from.isoformat(),
                "to": interval_end.isoformat() if interval_end else None,
                "historical_confirmed": source.historical_confirmed,
            },
            "correct_existing": body.correct_existing,
        }
        self.db.flush()
        if body.effective_date <= self.today:
            self._project(student, event)
        if _refresh_task_state:
            event.impact = {
                **event.impact,
                **self._refresh_tasks(student.id, body.effective_date, actor_id),
            }
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="academic.enrollment.change",
                resource_type="student",
                resource_id=str(student.id),
                before_json=before,
                after_json={
                    "change_kind": body.kind,
                    "effective_date": body.effective_date.isoformat(),
                    "enrollment_id": str(row.id),
                    "lock_version": revision,
                    "impact": event.impact,
                },
                reason=body.reason,
                request_id=request_id,
            )
        )
        if _owns_transaction:
            self.db.commit()
        else:
            self.db.flush()
        return self._view(student, event)

    def _end_electives(self, student_id: int, body: EnrollmentChangeRequest) -> list[dict]:
        ended = []
        for tcid in sorted(set(body.leave_teaching_class_ids)):
            memberships = list(
                self.db.scalars(
                    select(CourseParticipation)
                    .where(
                        CourseParticipation.student_id == student_id,
                        CourseParticipation.teaching_class_id == tcid,
                    )
                    .with_for_update()
                )
            )
            if not memberships:
                legacy = self.db.get(TeachingClassStudent, (tcid, student_id))
                if legacy is None:
                    raise ConflictError(message="退课清单包含未参加的教学班")
                # 旧名单起点未知，保留日期前已有成员，明确结束日期。
                if body.effective_date == date.min:
                    raise ConflictError(message="退课日期超出支持范围")
                memberships = [
                    CourseParticipation(
                        student_id=student_id,
                        teaching_class_id=tcid,
                        effective_from=date(1000, 1, 1),
                        source="LEGACY_UNCONFIRMED",
                    )
                ]
                self.db.add(memberships[0])
            for member in memberships:
                if member.effective_from < body.effective_date and (
                    member.effective_to is None or member.effective_to > body.effective_date
                ):
                    self.db.flush()
                    ended.append(
                        {
                            "id": str(member.id),
                            "previous_end": member.effective_to.isoformat()
                            if member.effective_to
                            else None,
                        }
                    )
                    member.effective_to = body.effective_date
                elif member.effective_from >= body.effective_date:
                    raise ConflictError(message="退课日期与后续选课冲突，请先核对选课历史")
        return ended

    def cancel(
        self,
        actor_id: int,
        student_id: int,
        change_id: int,
        expected_version: int,
        *,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        from app.modules.academic.lifecycle_transaction import begin_lifecycle_write

        begin_lifecycle_write(self.db)
        ids = set(
            self.db.scalars(select(UserAccount.id).where(UserAccount.student_id == student_id))
        ) | {actor_id}
        repo = IdentityRepository(self.db)
        for uid in sorted(ids):
            repo.get_user_by_id_for_update(uid)
        scope = resolve_scope(self.db, actor_id, "student.manage")
        self._lock_semesters()
        student = self.db.scalar(
            select(Student)
            .where(Student.id == student_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        event = self.db.get(EnrollmentChange, change_id)
        if student is None or event is None or event.student_id != student_id:
            raise NotFoundError("学籍计划不存在")
        target = self._required_enrollment(event.target_enrollment_id)
        source = self.db.scalar(
            select(StudentEnrollment)
            .where(
                StudentEnrollment.student_id == student_id,
                StudentEnrollment.superseded.is_(False),
                StudentEnrollment.effective_to == event.effective_date,
                StudentEnrollment.effective_from < event.effective_date,
            )
            .order_by(StudentEnrollment.effective_from.desc())
            .with_for_update()
            .limit(1)
        )
        if source is None:
            raise ConflictError(message="计划前继学籍已变化，请管理员核对，未撤销或覆盖现有事实")
        require_resource_scope(scope, source.college_id)
        require_resource_scope(scope, target.college_id)
        if student.lock_version != expected_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT)
        if event.state != "SCHEDULED" or event.effective_date <= self.today:
            raise ConflictError(message="只能撤销尚未生效的学籍计划")
        if self.db.scalar(
            select(EnrollmentChange.id)
            .where(
                EnrollmentChange.student_id == student_id,
                EnrollmentChange.state != "CANCELED",
                EnrollmentChange.effective_date > event.effective_date,
            )
            .limit(1)
        ):
            raise ConflictError(message="请先撤销后续计划")
        source.effective_to = target.effective_to
        target.superseded = True
        event.state = "CANCELED"
        for item in event.impact.get("ended_participations", []):
            member = self.db.get(CourseParticipation, int(item["id"]))
            if member:
                member.effective_to = (
                    date.fromisoformat(item["previous_end"]) if item["previous_end"] else None
                )
        student.lock_version += 1
        self.db.flush()
        event.impact = {
            **event.impact,
            "cancel_refresh": self._refresh_tasks(student_id, event.effective_date, actor_id),
        }
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="academic.enrollment.cancel",
                resource_type="enrollment_change",
                resource_id=str(event.id),
                before_json={"state": "SCHEDULED"},
                after_json={"state": "CANCELED", "lock_version": student.lock_version},
                reason=reason,
                request_id=request_id,
            )
        )
        self.db.commit()
        return self._view(student, event)

    def apply_due(self) -> int:
        """定时器维护兼容投影；权限/正式名单始终按日期解析，不依赖定时器时效。"""
        ids = list(
            self.db.scalars(
                select(EnrollmentChange.id)
                .where(
                    EnrollmentChange.state == "SCHEDULED",
                    EnrollmentChange.effective_date <= self.today,
                )
                .order_by(EnrollmentChange.effective_date, EnrollmentChange.id)
            )
        )
        self.db.rollback()
        count = 0
        for eid in ids:
            event = self.db.get(EnrollmentChange, eid)
            if event is None:
                continue
            sid = event.student_id
            repo = IdentityRepository(self.db)
            for uid in self.db.scalars(
                select(UserAccount.id).where(UserAccount.student_id == sid).order_by(UserAccount.id)
            ):
                repo.get_user_by_id_for_update(uid)
            self._lock_semesters()
            student = self.db.scalar(
                select(Student)
                .where(Student.id == sid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            self.db.refresh(event, with_for_update=True)
            if student is None:
                raise ConflictError(message="生效计划的学生关联缺失")
            if event.state == "SCHEDULED":
                self._project(student, event)
                student.lock_version += 1
                self.db.add(
                    AuditLog(
                        action="academic.enrollment.effective",
                        resource_type="enrollment_change",
                        resource_id=str(event.id),
                        before_json={"state": "SCHEDULED"},
                        after_json={"state": "APPLIED", "student_id": str(sid)},
                    )
                )
                self.db.commit()
                count += 1
            else:
                self.db.rollback()
        return count

    def _project(self, student: Student, event: EnrollmentChange) -> None:
        enrollment = self._required_enrollment(event.target_enrollment_id)
        current = self.at(student.id, self.today)
        if current is not None and current.id != enrollment.id:
            event.state = "APPLIED"  # 回溯更正只影响其原区间，当前投影沿用后续有效事实。
            return
        student.administrative_class_id = enrollment.administrative_class_id
        student.status = (
            "ACTIVE"
            if enrollment.status == "ENROLLED"
            else "ARCHIVED"
            if enrollment.status in {"GRADUATED", "WITHDRAWN"}
            else "SUSPENDED"
        )
        if enrollment.status in {"GRADUATED", "WITHDRAWN"}:
            student.history_until = ten_years_after(event.effective_date)
        elif enrollment.status == "ENROLLED":
            student.history_until = None
        source = self._required_enrollment(event.source_enrollment_id)
        end_authorities = (
            enrollment.status != "ENROLLED" or source.college_id != enrollment.college_id
        )
        if end_authorities:
            from app.modules.academic.enrollment_models import StudentManagerAppointment

            for qualification in self.db.scalars(
                select(VolunteerQualification)
                .where(VolunteerQualification.student_id == student.id)
                .with_for_update()
            ):
                qualification.enabled = False
            repo = IdentityRepository(self.db)
            role = repo.get_role_by_code("STUDENT_AFFAIRS_MANAGER")
            for user in self.db.scalars(
                select(UserAccount)
                .where(UserAccount.student_id == student.id)
                .order_by(UserAccount.id)
            ):
                for appointment in self.db.scalars(
                    select(StudentManagerAppointment).where(
                        StudentManagerAppointment.user_id == user.id,
                        StudentManagerAppointment.effective_to.is_(None),
                    )
                ):
                    processing_date = (
                        event.created_at + timedelta(hours=get_settings().app_utc_offset_hours)
                    ).date()
                    end_date = (
                        max(event.effective_date, processing_date)
                        if event.effective_date < processing_date
                        else event.effective_date
                    )
                    appointment.effective_to = max(appointment.effective_from, end_date)
                if role:
                    repo.revoke_role(user.id, role.id)
                repo.clear_optional_grants(user.id)
                # 保留绑定和 STUDENT；旧管理会话撤销后本人可重新登录查询历史。
                repo.revoke_active_sessions(user.id, utcnow())
                user.lock_version += 1
        event.state = "APPLIED"

    def _editable(self, task: InspectionTask) -> bool:
        if task.canceled_at is not None:
            return False
        now = utcnow()
        offset = timedelta(hours=get_settings().app_utc_offset_hours)
        start = self.db.scalar(
            select(PeriodDefinition.start_time).where(
                PeriodDefinition.semester_id == task.semester_id,
                PeriodDefinition.period_no == task.start_period,
            )
        )
        if task.inspection_date < max(self.today, (now + offset).date()):
            return False
        if task.inspection_date == (now + offset).date() and (
            start is None or datetime.combine(task.inspection_date, start) - offset <= now
        ):
            return False
        return not any(
            self.db.scalar(select(model.id).where(model.task_id == task.id).limit(1)) is not None
            for model in (InspectionSubmission, TaskDeadlineAssessment)
        )

    def _refresh_tasks(
        self,
        student_id: int,
        effective_date: date,
        actor_id: int,
        *,
        teaching_class_id: int | None = None,
        student_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        from app.modules.academic.participation import rosters_at
        from app.modules.inspection.models import TaskScheduleSource

        changed, protected, withdrawn, manual_review = [], [], [], []
        subjects = student_ids if student_ids is not None else {student_id}
        bound_students: dict[int, int] = {
            uid: sid
            for uid, sid in self.db.execute(
                select(UserAccount.id, UserAccount.student_id).where(
                    UserAccount.student_id.in_(subjects)
                )
            )
            if sid is not None
        }
        user_ids = list(bound_students)
        task_query = select(InspectionTask).where(
            InspectionTask.inspection_date >= max(effective_date, self.today)
        )
        if teaching_class_id is not None:
            task_query = task_query.where(
                or_(
                    InspectionTask.teaching_class_id == teaching_class_id,
                    InspectionTask.id.in_(
                        select(TaskScheduleSource.task_id).where(
                            TaskScheduleSource.teaching_class_id == teaching_class_id
                        )
                    ),
                )
            )
        tasks = list(self.db.scalars(task_query.order_by(InspectionTask.id).with_for_update()))
        for task in tasks:
            old_members = list(
                self.db.scalars(
                    select(TaskRosterMember).where(
                        TaskRosterMember.task_id == task.id,
                        TaskRosterMember.roster_version == task.roster_version,
                    )
                )
            )
            source_ids = list(
                self.db.scalars(
                    select(TaskScheduleSource.teaching_class_id).where(
                        TaskScheduleSource.task_id == task.id
                    )
                )
            )
            legacy_merge = "|grp" in task.task_key and not source_ids
            if legacy_merge:
                if subjects & {m.student_id for m in old_members}:
                    manual_review.append(str(task.id))
                students = list(
                    self.db.scalars(
                        select(Student).where(Student.id.in_([m.student_id for m in old_members]))
                    )
                )
            else:
                tids = source_ids or ([task.teaching_class_id] if task.teaching_class_id else [])
                try:
                    dated = rosters_at(self.db, tids, task.inspection_date)
                except ConflictError:
                    manual_review.append(str(task.id))
                    if (
                        subjects & {m.student_id for m in old_members}
                        and self._editable(task)
                        and not task.roster_review_required
                    ):
                        task.roster_review_required = True
                        task.lock_version += 1
                    continue
                students = list({s.id: s for roster in dated.values() for s in roster}.values())
            if task.administrative_class_id and not task.teaching_class_id:
                students = [
                    s
                    for s in self.db.scalars(select(Student))
                    if (e := self.at(s.id, task.inspection_date)) is not None
                    and e.status == "ENROLLED"
                    and e.administrative_class_id == task.administrative_class_id
                    or not self.has_timeline(s.id)
                    and s.status == "ACTIVE"
                    and s.administrative_class_id == task.administrative_class_id
                ]
            old_ids, new_ids = {m.student_id for m in old_members}, {s.id for s in students}
            relevant = teaching_class_id is not None or bool(subjects & (old_ids | new_ids))
            own = (
                list(
                    self.db.scalars(
                        select(InspectionAssignment).where(
                            InspectionAssignment.task_id == task.id,
                            InspectionAssignment.volunteer_user_id.in_(user_ids),
                            InspectionAssignment.revoked_at.is_(None),
                        )
                    )
                )
                if user_ids
                else []
            )
            if not relevant and not own:
                continue
            if not self._editable(task):
                protected.append(str(task.id))
                continue
            if legacy_merge:
                # 未知合并来源不允许据部分可见学生重建名单；保留全部原成员并交给教师复核。
                if relevant and not task.roster_review_required:
                    task.roster_review_required = True
                    task.lock_version += 1
                new_ids = old_ids
            version_changed = False
            if str(task.id) in manual_review:
                task.roster_review_required = True
                version_changed = True
            snapshots = {}
            for s in students:
                record = self.at(s.id, task.inspection_date)
                class_id = record.administrative_class_id if record else s.administrative_class_id
                ac = self.db.get(AdministrativeClass, class_id) if class_id else None
                snapshots[s.id] = {
                    "student_no": s.student_no,
                    "name": s.name,
                    "class_name_snapshot": ac.class_name if ac else None,
                    "grade_year_snapshot": ac.grade_year if ac else None,
                    "administrative_class_id_snapshot": class_id,
                    "college_id_snapshot": record.college_id
                    if record
                    else ac.college_id
                    if ac
                    else None,
                    "major_name_snapshot": ac.major_name if ac else None,
                }
            metadata_changed = any(
                m.student_id in snapshots
                and any(getattr(m, key) != value for key, value in snapshots[m.student_id].items())
                for m in old_members
            )
            if relevant and not legacy_merge and (old_ids != new_ids or metadata_changed):
                task.roster_version += 1
                self.db.add(
                    TaskRosterVersion(
                        task_id=task.id,
                        version_no=task.roster_version,
                        created_by=actor_id,
                        reason="学籍异动同步未来正式名单",
                    )
                )
                for student in students:
                    self.db.add(
                        TaskRosterMember(
                            task_id=task.id,
                            roster_version=task.roster_version,
                            student_id=student.id,
                            **snapshots[student.id],
                        )
                    )
                if old_ids != new_ids:
                    if task.expected_count_current == len(old_members):
                        task.expected_count_current = len(students)
                    else:
                        task.expected_count_review_required = True
                        manual_review.append(str(task.id))
                version_changed = True
                changed.append(str(task.id))
            assigned_student = bound_students.get(own[0].volunteer_user_id) if own else student_id
            e = self.at(assigned_student, task.inspection_date) if assigned_student else None
            # 转院/离校后旧资格退出；院内转班也可能引入本班回避，撤销后由老师重新排班。
            own_class = e.administrative_class_id if e else None
            roster_classes = set()
            for s in students:
                record = self.at(s.id, task.inspection_date)
                roster_classes.add(
                    record.administrative_class_id if record else s.administrative_class_id
                )
            if (
                own
                and e
                and (
                    e.status != "ENROLLED"
                    or task.college_id is not None
                    and e.college_id != task.college_id
                    or own_class in roster_classes
                )
            ):
                for assignment in own:
                    assignment.revoked_at = utcnow()
                withdrawn.append(str(task.id))
                version_changed = True
            if version_changed:
                task.lock_version += 1
        self.db.flush()
        from app.modules.inspection.responsibility import sync_responsibility
        for task in tasks:
            if str(task.id) in changed:
                sync_responsibility(self.db, task)
        return {
            "refreshed_task_ids": changed,
            "protected_task_ids": protected,
            "withdrawn_assignment_task_ids": withdrawn,
            "manual_roster_review_task_ids": manual_review,
        }

    def _view(self, student: Student, event: EnrollmentChange) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "student_id": str(student.id),
            "student_no": student.student_no,
            "lock_version": student.lock_version,
            "state": event.state,
            "kind": event.kind,
            "effective_date": event.effective_date.isoformat(),
            "history_until": student.history_until.isoformat() if student.history_until else None,
            "impact": event.impact,
        }

    def _handoff_query(self, actor_id, action, *, write=False):
        if self.college_id is not None:
            from app.modules.identity.resource_scope import resolve_scope as resource_scope
            from app.modules.identity.role_scope import DefaultRoleScope
            from app.modules.identity.service import CurrentUser
            from app.modules.identity.repository import IdentityRepository
            resource_scope(self.db, CurrentUser(actor_id, None, "", "ACTIVE", [], []), self.college_id, action, write=write)
            root = "SUPER_ADMIN" in IdentityRepository(self.db).list_role_codes(actor_id)
            scope = DefaultRoleScope("SCHOOL" if root else "COLLEGE", self.college_id)
            return scope, select(InspectionTask).where(InspectionTask.college_id == self.college_id)
        scope = resolve_scope(self.db, actor_id, action)
        statement = select(InspectionTask)
        if scope.kind != "SCHOOL":
            colleges = set(scope.authorized_college_ids)
            if scope.college_id is not None:
                colleges.add(scope.college_id)
            statement = statement.where(InspectionTask.college_id.in_(colleges))
        return scope, statement

    def handoff_tasks(self, actor_id: int) -> dict[str, Any]:
        _, statement = self._handoff_query(actor_id, "inspection.roster.manage")
        tasks = self.db.scalars(
            statement
            .where(
                or_(
                    InspectionTask.roster_review_required.is_(True),
                    InspectionTask.expected_count_review_required.is_(True),
                ),
                InspectionTask.canceled_at.is_(None),
            )
            .order_by(InspectionTask.inspection_date, InspectionTask.id)
            .limit(500)
        )
        return {
            "items": [
                {
                    "id": str(t.id),
                    "college_id": str(t.college_id) if t.college_id else None,
                    "inspection_date": t.inspection_date.isoformat(),
                    "course_name": t.course_name_snapshot,
                    "class_name": t.class_name_snapshot,
                    "roster_review_required": t.roster_review_required,
                    "expected_count_review_required": t.expected_count_review_required,
                    "expected_count_current": t.expected_count_current,
                    "roster_version": t.roster_version,
                    "lock_version": t.lock_version,
                }
                for t in tasks
            ]
        }

    def review_task(
        self,
        actor_id: int,
        task_id: int,
        version: int,
        *,
        confirm_roster: bool,
        confirm_expected_count: bool,
        reason: str | None = None,
        request_id: str | None = None,
    ):
        self.db.rollback()
        scope, statement = self._handoff_query(actor_id, "inspection.roster.manage", write=True)
        task = self.db.scalar(
            statement.where(InspectionTask.id == task_id).with_for_update().execution_options(populate_existing=True)
        )
        if task is None:
            raise NotFoundError("任务不存在")
        if task.lock_version != version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT)
        if not confirm_roster and not confirm_expected_count:
            raise ConflictError(message="请明确确认名单或应到人数")
        if confirm_expected_count:
            _, expected_scope = self._handoff_query(actor_id, "attendance.expected_count_adjust", write=True)
            if self.db.scalar(expected_scope.with_only_columns(InspectionTask.id).where(InspectionTask.id == task.id)) is None:
                raise PermissionDeniedError("没有此任务应到人数复核权限")
        from app.modules.academic.qualification_policy import enrollment_on

        members = list(
            self.db.scalars(
                select(TaskRosterMember).where(
                    TaskRosterMember.task_id == task.id,
                    TaskRosterMember.roster_version == task.roster_version,
                )
            )
        )
        if scope.kind != "SCHOOL":
            for member in members:
                e = enrollment_on(self.db, member.student_id, task.inspection_date)
                if e is not None and e.college_id != task.college_id:
                    raise PermissionDeniedError("跨学院正式名单需管理员统筹复核")
        before = {
            "roster_review_required": task.roster_review_required,
            "expected_count_review_required": task.expected_count_review_required,
        }
        if confirm_roster:
            task.roster_review_required = False
        if confirm_expected_count:
            task.expected_count_review_required = False
        task.lock_version += 1
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="academic.enrollment.task_review",
                resource_type="inspection_task",
                resource_id=str(task.id),
                before_json=before,
                after_json={
                    "roster_version": task.roster_version,
                    "expected_count_current": task.expected_count_current,
                    "confirm_roster": confirm_roster,
                    "confirm_expected_count": confirm_expected_count,
                    "snapshot_policy": "KEEP_EXISTING",
                    **({"_workspace_college_id": str(task.college_id)} if task.college_id is not None else {}),
                },
                reason=reason,
                request_id=request_id,
            )
        )
        self.db.commit()
        return {
            "id": str(task.id),
            "lock_version": task.lock_version,
            "roster_review_required": task.roster_review_required,
            "expected_count_review_required": task.expected_count_review_required,
        }

    def history(self, actor_id: int, student_id: int) -> dict[str, Any]:
        user = self.db.get(UserAccount, actor_id, populate_existing=True)
        if user and user.student_id == student_id:
            from app.modules.identity.query_scope import activate_query_scope

            activate_query_scope(self.db, actor_id, personal=True)
        student = self.db.get(Student, student_id)
        if student is None:
            raise NotFoundError("学生不存在")
        if not user or not user.is_active:
            raise PermissionDeniedError()
        if user.student_id == student_id:
            if student.history_until and self.today > student.history_until:
                raise PermissionDeniedError("本人离校历史查询期限已届满")
        else:
            scope = resolve_scope(self.db, actor_id, "student.read")
            e = self.at(student_id, self.today)
            ac = (
                self.db.get(AdministrativeClass, student.administrative_class_id)
                if student.administrative_class_id
                else None
            )
            require_resource_scope(scope, e.college_id if e else ac.college_id if ac else None)
        changes = list(
            self.db.scalars(
                select(EnrollmentChange)
                .where(EnrollmentChange.student_id == student_id)
                .order_by(EnrollmentChange.effective_date.desc(), EnrollmentChange.id.desc())
            )
        )
        enrollments = list(
            self.db.scalars(
                select(StudentEnrollment)
                .where(StudentEnrollment.student_id == student_id)
                .order_by(StudentEnrollment.revision)
            )
        )
        return {
            "student_id": str(student.id),
            "student_no": student.student_no,
            "lock_version": student.lock_version,
            "changes": [self._view(student, c) for c in changes],
            "enrollments": [
                {
                    "id": str(e.id),
                    "effective_from": e.effective_from.isoformat(),
                    "effective_to": e.effective_to.isoformat() if e.effective_to else None,
                    "status": e.status,
                    "historical_confirmed": e.historical_confirmed,
                    "superseded": e.superseded,
                    "snapshot": e.snapshot,
                }
                for e in enrollments
            ],
        }
