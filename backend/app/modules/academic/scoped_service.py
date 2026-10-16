"""基础数据院级入口；迁移期间与旧全局 Service 分离，逐项接入而非隐式放行。"""

from pydantic import Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.academic.models import AdministrativeClass
from app.modules.academic.schemas import (
    AdministrativeClassCreateRequest,
    AdministrativeClassUpdateRequest,
)
from app.modules.academic.scoped_repository import ScopedAcademicRepository
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import CampusService, atomic_write, validated

READ_ACTIONS = {"students": "student.read", "qualifications": "volunteer.read"}


class ScopedClassCreate(AdministrativeClassCreateRequest):
    model_config = StrictModel.model_config


class ScopedClassUpdate(AdministrativeClassUpdateRequest):
    model_config = StrictModel.model_config
    ownership_version: int = Field(ge=1)

    @model_validator(mode="after")
    def non_nullable_fields(self):
        if any(
            key in self.model_fields_set and getattr(self, key) is None
            for key in ("class_name", "status")
        ):
            raise ValueError("名称和状态不能为 null")
        return self


class ScopedAcademicService:
    def __init__(
        self, db: Session, actor: CurrentUser, college_id: int, request_id: str | None = None
    ):
        self.db = db
        self.actor = actor
        self.college_id = college_id
        self.request_id = request_id
        self.campus = CampusService(db, request_id)

    def _repo(self, action: str, *, write=False):
        scope = resolve_scope(self.db, self.actor, self.college_id, action, write=write)
        return ScopedAcademicRepository(self.db, scope)

    def _dto(self, row, *, as_of=None, enrollment=None, week_nos=None):
        result = self.campus._dto(row)
        if row.__tablename__ == "student":
            from app.modules.identity.role_scope import business_today

            day = as_of or business_today()
            if enrollment is None:
                from app.modules.academic.enrollment_service import EnrollmentService

                enrollment = EnrollmentService(self.db).at(row.id, day)
            result["as_of"] = day.isoformat()
            result["enrollment_snapshot"] = enrollment.snapshot if enrollment else None
            result["enrollment_source"] = "DATED" if enrollment else "CURRENT_LEGACY"
            if enrollment:
                result["administrative_class_id"] = (
                    str(enrollment.administrative_class_id)
                    if enrollment.administrative_class_id
                    else None
                )
                result["college_id"] = (
                    str(enrollment.college_id) if enrollment.college_id else None
                )
                result["enrollment_status"] = enrollment.status
                result["status"] = (
                    "ACTIVE" if enrollment.status == "ENROLLED" else enrollment.status
                )
            ac_id = (
                enrollment.administrative_class_id
                if enrollment and enrollment.administrative_class_id
                else row.administrative_class_id
            )
            if ac_id:
                ac = self.db.get(AdministrativeClass, ac_id)
                if ac:
                    result["administrative_class_name"] = ac.class_name
        if row.__tablename__ == "course_schedule":
            if week_nos is not None:
                result["week_nos"] = week_nos
            else:
                from sqlalchemy import select

                from app.modules.academic.models import CourseScheduleWeek

                result["week_nos"] = list(
                    self.db.scalars(
                        select(CourseScheduleWeek.week_no)
                        .where(CourseScheduleWeek.schedule_id == row.id)
                        .order_by(CourseScheduleWeek.week_no)
                    )
                )
        return result

    def list_rows(self, kind: str, params: PageParams, **filters):
        if filters.get("as_of") is not None and kind != "students":
            raise AppError(ErrorCode.VALIDATION_ERROR, "日期学籍筛选仅适用于学生列表", 422)
        try:
            repo = self._repo(READ_ACTIONS.get(kind, "academic.read"))
        except (PermissionDeniedError, NotFoundError):
            if kind != "teaching_classes":
                raise
            # 名单维护者需要选择教学班；仓储已明确允许该动作，不授予课表等其他读取。
            repo = self._repo("student.manage")
        rows, total = repo.page(kind, params, **filters)
        if kind == "students" and rows:
            from sqlalchemy import or_, select

            from app.modules.academic.enrollment_models import StudentEnrollment
            from app.modules.identity.role_scope import business_today

            day = filters.get("as_of") or business_today()
            student_ids = [r.id for r in rows]
            enrollments = list(
                self.db.scalars(
                    select(StudentEnrollment)
                    .where(
                        StudentEnrollment.student_id.in_(student_ids),
                        StudentEnrollment.superseded.is_(False),
                        StudentEnrollment.effective_from <= day,
                        or_(
                            StudentEnrollment.effective_to.is_(None),
                            StudentEnrollment.effective_to > day,
                        ),
                    )
                    .order_by(
                        StudentEnrollment.effective_from.desc(),
                        StudentEnrollment.revision.desc(),
                    )
                )
            )
            enrollment_map = {}
            for e in enrollments:
                if e.student_id not in enrollment_map:
                    enrollment_map[e.student_id] = e
            items = [
                self._dto(
                    row,
                    as_of=filters.get("as_of"),
                    enrollment=enrollment_map.get(row.id),
                )
                for row in rows
            ]
        elif kind == "schedules" and rows:
            from collections import defaultdict

            from sqlalchemy import select

            from app.modules.academic.models import CourseScheduleWeek

            schedule_ids = [r.id for r in rows]
            weeks_map = defaultdict(list)
            for sid, wno in self.db.execute(
                select(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
                .where(CourseScheduleWeek.schedule_id.in_(schedule_ids))
                .order_by(CourseScheduleWeek.week_no)
            ):
                weeks_map[sid].append(wno)
            items = [self._dto(row, week_nos=weeks_map[row.id]) for row in rows]
        else:
            items = [self._dto(row, as_of=filters.get("as_of")) for row in rows]
        return {
            "items": items,
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }

    def get_row(self, kind: str, rid: int):
        return self._dto(self._repo(READ_ACTIONS.get(kind, "academic.read")).get(kind, rid))

    @atomic_write
    def set_course_type(self, teaching_class_id: int, type_id: int, version: int, future_impact_revision=""):
        from sqlalchemy import select

        from app.modules.academic.campus_models import CourseType
        from app.modules.academic.models import TeachingClass

        repo = self._repo("academic.manage", write=True)
        repo.get("teaching_classes", teaching_class_id)
        teaching = self.db.scalar(
            select(TeachingClass)
            .where(
                TeachingClass.id == teaching_class_id, TeachingClass.college_id == self.college_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        course_type = self.db.scalar(
            select(CourseType)
            .where(
                CourseType.id == type_id,
                CourseType.college_id == self.college_id,
                CourseType.status == "ACTIVE",
            )
            .with_for_update()
        )
        if teaching is None:
            raise NotFoundError("教学班不属于本院")
        if course_type is None:
            raise NotFoundError("课程类型不在本院或已停用")
        if teaching.classification_revision != version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "教学班分类已变化")
        from app.modules.organization.future_impact import confirm_impact
        impact = confirm_impact(self.db, self.college_id, "teaching_class", teaching, future_impact_revision)
        before = self._dto(teaching)
        teaching.course_type_id = course_type.id
        teaching.classification_revision += 1
        college = self.campus.repo.college(self.college_id, lock=True)
        if college is None:
            raise NotFoundError("学院不存在")
        college.configuration_revision += 1
        from app.modules.organization.impact_service import capture_impacts
        capture_impacts(self.db, self.college_id, "teaching_class", teaching.id, teaching.classification_revision,
                        task_ids=[int(value) for value in impact["retained_future_task_ids"]],
                        before=before, after=self._dto(teaching))
        return self._audit("academic.teaching_class.classify", teaching, before)

    def list_roster(self, teaching_class_id: int):
        return [self._dto(row) for row in self._repo("student.read").roster(teaching_class_id)]

    def classification_impact(self, rid):
        from app.modules.organization.future_impact import future_impact
        row = self._repo("academic.read").get("teaching_classes", rid)
        return future_impact(self.db, self.college_id, "teaching_class", row.id, row.classification_revision)

    def _audit(self, action, row, before, reason=None, *, after_extra=None):
        after = self._dto(row)
        if after_extra:
            after.update(after_extra)
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action=action,
                resource_type=row.__tablename__,
                resource_id=str(row.id),
                before_json=before,
                after_json=scoped_snapshot(after, self.college_id),
                reason=reason,
                request_id=self.request_id,
            )
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            raise ConflictError(message="编码重复或关联已变化，未保存") from exc
        return after

    def _class_college_text(self, text):
        college = self.campus.repo.college(self.college_id)
        if text is not None and text != college.name:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "所属学院由工作区确定，不能通过文本修改", 422
            )
        return college.name

    @atomic_write
    def create_admin_class(self, data):
        self._repo("academic.manage", write=True)
        body = validated(ScopedClassCreate, data)
        row = AdministrativeClass(
            **body.model_dump(exclude={"reason", "college"}),
            college=self._class_college_text(body.college),
            college_id=self.college_id,
        )
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(message="编码重复，未保存") from exc
        return self._audit("academic.admin_class.create", row, None, body.reason)

    @atomic_write
    def update_admin_class(self, rid: int, data):
        repo = self._repo("academic.manage", write=True)
        body = validated(ScopedClassUpdate, data)
        row = repo.get("administrative_classes", rid, lock=True)
        if row.ownership_version != body.ownership_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "班级已变化，请刷新")
        if body.status is not None and body.status not in {"ACTIVE", "DISABLED"}:
            raise AppError(ErrorCode.VALIDATION_ERROR, "班级状态无效", 422)
        before = self._dto(row)
        if body.college is not None:
            self._class_college_text(body.college)
        for key, value in body.model_dump(
            exclude_unset=True, exclude={"reason", "college", "ownership_version"}
        ).items():
            setattr(row, key, value)
        row.ownership_version += 1
        self.db.flush()
        return self._audit("academic.admin_class.update", row, before, body.reason)

    @atomic_write
    def replace_roster(
        self,
        teaching_class_id: int,
        student_ids: list[str],
        ownership_version: int,
        reason: str | None = None,
    ):
        repo = self._repo("student.manage", write=True)
        from app.modules.academic.enrollment_service import EnrollmentService

        lifecycle = EnrollmentService(self.db)
        lifecycle._lock_semesters()
        teaching = repo.get("teaching_classes", teaching_class_id, lock=True)
        if repo.get("semesters", teaching.semester_id).status != "ACTIVE":
            raise ConflictError(message="学期已归档，不能替换名单")
        if teaching.ownership_version != ownership_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "教学班名单已变化，请刷新")
        try:
            ids = [int(value) for value in student_ids]
            if any(
                str(value) != raw or not 0 < value < 2**63
                for value, raw in zip(ids, student_ids, strict=True)
            ):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学生标识格式无效", 422) from exc
        if len(ids) > 5000:
            raise AppError(ErrorCode.VALIDATION_ERROR, "单批名单最多 5000 人", 422)
        if {row.id for row in repo.students(ids)} != set(ids):
            raise NotFoundError()
        # 对现有外院名单亦拒绝，不能借替换悄悄擦除历史混合名单。
        previous_students = repo.roster(teaching_class_id)
        before = self._dto(teaching)
        before["roster_student_ids"] = [str(row.id) for row in previous_students]
        from app.modules.academic.roster_lifecycle import record_roster_replacement

        record_roster_replacement(self.db, teaching_class_id, ids, lifecycle.today)
        repo.replace_roster(teaching_class_id, ids)
        teaching.ownership_version += 1
        self.db.flush()
        lifecycle._refresh_tasks(
            0, lifecycle.today, self.actor.id, teaching_class_id=teaching_class_id
        )
        self._audit(
            "academic.roster.replace",
            teaching,
            before,
            reason,
            after_extra={"roster_student_ids": [str(sid) for sid in sorted(set(ids))]},
        )
        return [self._dto(row) for row in repo.roster(teaching_class_id)]
