"""院级基础数据写入；范围、父链、版本与历史依赖必须在整批写前核验。"""

from datetime import timedelta

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import Base
from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.enrollment_service import class_snapshot
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    Student,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.academic.scoped_service import ScopedAcademicService
from app.modules.academic.scoped_write_schemas import CREATE_SCHEMAS, UPDATE_SCHEMAS
from app.modules.academic.time_service import TimeResolver
from app.modules.audit.models import AuditLog
from app.modules.identity.role_scope import business_today
from app.modules.organization.service import atomic_write, validated

MODELS = {
    "administrative_classes": AdministrativeClass,
    "students": Student,
    "courses": Course,
    "teaching_classes": TeachingClass,
    "schedules": CourseSchedule,
}


class ScopedAcademicWriteService(ScopedAcademicService):
    @atomic_write
    def batch_elective(self, data):
        from app.modules.academic.scoped_elective import create
        from app.modules.academic.scoped_write_schemas import ElectiveBatch

        return create(self, validated(ElectiveBatch, data))

    @atomic_write
    def batch_self_study(self, data):
        from app.modules.academic.scoped_self_study import create_self_study
        from app.modules.academic.scoped_write_schemas import SelfStudyBatchCreate

        return create_self_study(self, validated(SelfStudyBatchCreate, data))

    @atomic_write
    def reset_semester(self, sid, data):
        from app.modules.academic.scoped_reset import reset, snapshot
        from app.modules.academic.scoped_write_schemas import SemesterReset

        body = validated(SemesterReset, data)
        self._repo("academic.manage", write=True)
        # 重置涉及教学、任务和资格，逐项验证，不能用单一教学动作扩大权限。
        for action in ("inspection.cancel", "student.manage", "volunteer.manage"):
            self._repo(action, write=True)
        semester = self._semester(sid)
        if body.confirm_name.strip() != semester.name.strip():
            raise ConflictError(message="确认学期名称不匹配，整批未重置")
        if body.source_revision != snapshot(self, semester)["source_revision"]:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT, "业务资料已变化或缺少预览修订，请重新预览后确认"
            )
        return reset(self, semester, body)

    def reset_preview(self, sid):
        from app.modules.academic.scoped_reset import snapshot

        for action in (
            "academic.manage",
            "inspection.cancel",
            "student.manage",
            "volunteer.manage",
        ):
            self._repo(action, write=True)
        return snapshot(self, self._semester(sid))

    @atomic_write
    def upsert_qualification(self, body):
        from app.modules.academic.scoped_write_schemas import QualificationUpsert
        from app.modules.academic.service import AcademicService

        body = validated(QualificationUpsert, body)
        repo = self._repo("volunteer.manage", write=True)
        self._semester(body.semester_id)
        student = repo.get("students", body.student_id, lock=True)
        if student.lock_version != body.student_lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "学生或资格已变化，请刷新后重试")
        if body.enabled and self._dto(student)["status"] != "ACTIVE":
            raise ConflictError(message="仅当前在读学生可以启用资格")
        row = self.db.scalar(
            select(VolunteerQualification)
            .where(
                VolunteerQualification.student_id == student.id,
                VolunteerQualification.semester_id == body.semester_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is not None and row.college_id != self.college_id:
            raise ConflictError(message="原资格归属不同或尚未核实，请先完成学籍与资格交接")
        before = self._dto(row) if row else None
        if row is None:
            row = VolunteerQualification(
                student_id=student.id,
                semester_id=body.semester_id,
                college_id=self.college_id,
                created_by=self.actor.id,
                enabled=body.enabled,
            )
            self.db.add(row)
        row.enabled = body.enabled
        student.lock_version += 1
        if body.enabled:
            AcademicService(self.db)._grant_volunteer_role(student.id)
        self.db.flush()
        return self._audit(
            "academic.volunteer_qualification.upsert",
            row,
            before,
            body.reason,
            after_extra={"student_lock_version": student.lock_version},
        )

    def _action(self, kind):
        if kind not in MODELS:
            raise NotFoundError("不支持的写入资源")
        return "student.manage" if kind == "students" else "academic.manage"

    def _semester(self, sid):
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == sid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if semester is None:
            raise NotFoundError("学期不存在")
        if semester.status != "ACTIVE":
            raise ConflictError(message="学期已归档")
        return semester

    def _owned(self, kind, rid, repo):
        row = repo.get(kind, rid, lock=True)
        if kind == "courses" and row.college_id != self.college_id:
            raise NotFoundError("工作区不能修改学校共享课程")
        return row

    def _weeks(self, semester, values):
        if not values or any(
            type(w) is not int or not 1 <= w <= semester.total_weeks for w in values
        ):
            raise AppError(ErrorCode.VALIDATION_ERROR, "必须填写有效学期周次", 422)
        return sorted(set(values))

    def _schedule_time(self, row, semester, weeks, *, resolver=None):
        if row.start_period > row.end_period:
            raise AppError(ErrorCode.VALIDATION_ERROR, "结束节次小于开始节次", 422)
        if not get_settings().campus_scheduling_enabled:
            return
        if resolver is None:
            resolver = TimeResolver(self.db)
            resolver.prefetch(self.college_id, semester.id, lock=True)
        day = semester.start_date
        while day <= semester.end_date:
            actual = resolver.teaching_day(self.college_id, semester.id, day)
            if actual and actual[0] in weeks and actual[1] == row.weekday:
                resolver.interval(
                    self.college_id,
                    semester.id,
                    day,
                    row.start_period,
                    row.end_period,
                    teaching_class_id=row.teaching_class_id,
                )
            day += timedelta(days=1)

    @atomic_write
    def create(self, kind, data):
        if kind not in CREATE_SCHEMAS:
            raise NotFoundError("请使用专用创建入口")
        repo = self._repo(self._action(kind), write=True)
        body = validated(CREATE_SCHEMAS[kind], data)
        values = body.model_dump(exclude={"reason", "weeks", "enrolled_since"})
        semester, weeks = None, None
        if kind == "students":
            ac = repo.get("administrative_classes", body.administrative_class_id)
            if ac.status != "ACTIVE" or body.enrolled_since > business_today():
                raise ConflictError(message="行政班须启用，入籍日期不能在未来")
        elif kind == "teaching_classes":
            semester = self._semester(body.semester_id)
            repo.get("courses", body.course_id)
            if body.course_type_id is None:
                from app.modules.academic.default_types import regular_type
                values["course_type_id"] = regular_type(self.db, self.college_id).id
            if body.course_type_id is not None:
                type_row = self.db.scalar(
                    select(CourseType)
                    .where(
                        CourseType.id == body.course_type_id,
                        CourseType.college_id == self.college_id,
                        CourseType.status == "ACTIVE",
                    )
                    .with_for_update()
                )
                if type_row is None:
                    raise NotFoundError("课程类型不属于本院或已停用")
        elif kind == "schedules":
            teaching = repo.get("teaching_classes", body.teaching_class_id)
            semester = self._semester(teaching.semester_id)
            if teaching.status != "ACTIVE":
                raise ConflictError(message="教学班已停用")
            values["semester_id"] = teaching.semester_id
            weeks = self._weeks(semester, body.weeks)
        if kind != "students":
            values["college_id"] = self.college_id
        row = MODELS[kind](**values)
        if weeks is not None:
            self._schedule_time(row, semester, weeks)
        self.db.add(row)
        self.db.flush()
        if kind == "students":
            self.db.add(
                StudentEnrollment(
                    student_id=row.id,
                    administrative_class_id=ac.id,
                    college_id=self.college_id,
                    effective_from=body.enrolled_since,
                    status="ENROLLED",
                    revision=1,
                    historical_confirmed=True,
                    snapshot=class_snapshot(ac),
                )
            )
        if weeks is not None:
            self.db.add_all(CourseScheduleWeek(schedule_id=row.id, week_no=w) for w in weeks)
        self.db.flush()
        return self._audit(f"academic.{kind}.create", row, None, body.reason)

    @atomic_write
    def update(self, kind, rid, data):
        if kind not in UPDATE_SCHEMAS:
            raise NotFoundError("请使用专用更新入口")
        repo = self._repo(self._action(kind), write=True)
        body = validated(UPDATE_SCHEMAS[kind], data)
        row = self._owned(kind, rid, repo)
        version_key = "lock_version" if kind == "students" else "ownership_version"
        if getattr(row, version_key) != getattr(body, version_key):
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "资料已变化，请刷新")
        before = self._dto(row)
        values = body.model_dump(exclude_unset=True, exclude={"reason", version_key, "weeks"})
        allowed_statuses = (
            {"ACTIVE", "SUSPENDED", "GRADUATED"} if kind == "students" else {"ACTIVE", "DISABLED"}
        )
        if "status" in values and values["status"] not in allowed_statuses:
            raise AppError(ErrorCode.VALIDATION_ERROR, "状态无效", 422)
        if any(
            value is None
            for key, value in values.items()
            if key in {"name", "class_name", "course_name", "weekday", "start_period", "end_period"}
        ):
            raise AppError(ErrorCode.VALIDATION_ERROR, "必要字段不能清空", 422)
        if kind == "students":
            if "administrative_class_id" in values and (
                str(values["administrative_class_id"])
                if values["administrative_class_id"]
                else None
            ) != before.get("administrative_class_id"):
                raise ConflictError(message="转班或清除归属须使用带日期的学籍异动")
            if "status" in values and values["status"] != before.get("status"):
                raise ConflictError(message="学籍停用或恢复须使用带日期的学籍异动")
            # The dated lifecycle owns these projections, even when its future
            # effective transition has not yet been applied to the legacy row.
            values.pop("administrative_class_id", None)
            values.pop("status", None)
        semester = (
            self._semester(row.semester_id) if kind in {"schedules", "teaching_classes"} else None
        )
        for key, value in values.items():
            setattr(row, key, value)
        if kind == "schedules":
            weeks = self._weeks(
                semester,
                body.weeks
                if "weeks" in body.model_fields_set
                else list(
                    self.db.scalars(
                        select(CourseScheduleWeek.week_no).where(
                            CourseScheduleWeek.schedule_id == row.id
                        )
                    )
                ),
            )
            self._schedule_time(row, semester, weeks)
            if "weeks" in body.model_fields_set:
                self.db.execute(
                    delete(CourseScheduleWeek).where(CourseScheduleWeek.schedule_id == row.id)
                )
                self.db.add_all(CourseScheduleWeek(schedule_id=row.id, week_no=w) for w in weeks)
        setattr(row, version_key, getattr(row, version_key) + 1)
        self.db.flush()
        return self._audit(f"academic.{kind}.update", row, before, body.reason)

    @atomic_write
    def delete_many(self, kind, ids, versions, reason=None):
        repo = self._repo(self._action(kind), write=True)
        ids = sorted(set(ids))
        if not ids or len(ids) > 500 or set(versions) != set(ids):
            raise AppError(ErrorCode.VALIDATION_ERROR, "删除集合及版本必须完整一致", 422)
        rows = [self._owned(kind, rid, repo) for rid in ids]
        version_key = "lock_version" if kind == "students" else "ownership_version"
        for row in rows:
            if getattr(row, version_key) != versions[row.id]:
                raise ConflictError(ErrorCode.VERSION_CONFLICT, "资料已变化，整批未删除")
            if kind in {"schedules", "teaching_classes"}:
                self._semester(row.semester_id)
        target = MODELS[kind].__table__
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                if fk.column.table is target:
                    if kind == "schedules" and table.name == "course_schedule_week":
                        continue
                    if (
                        self.db.scalar(select(fk.parent).where(fk.parent.in_(ids)).limit(1))
                        is not None
                    ):
                        raise ConflictError(
                            message="资料存在业务或历史引用，整批未删除；请停用或先处理依赖"
                        )
        for row in rows:
            self.db.add(
                AuditLog(
                    actor_user_id=self.actor.id,
                    action=f"academic.{kind}.delete",
                    resource_type=target.name,
                    resource_id=str(row.id),
                    before_json=self._dto(row),
                    after_json={"_workspace_college_id": str(self.college_id)},
                    reason=reason,
                    request_id=self.request_id,
                )
            )
            self.db.delete(row)
        self.db.flush()
        self.db.commit()
        result = {"deleted_ids": [str(rid) for rid in ids], "deleted_count": len(ids)}
        if kind == "administrative_classes" and len(rows) == 1:
            result.update(
                class_id=str(rows[0].id), class_name=rows[0].class_name, deleted_students_count=0
            )
        return result
