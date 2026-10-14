"""请求范围覆盖旧查询的纵深守卫；资源入口仍负责动作和事务规则。

范围只由当前数据库身份产生；本人入口沿用原有所有权守卫。
SQL 谓词使用 Core 表列构建，避免 ORM 条件在子查询里递归或由当前学生归属搬动历史。
"""

from contextlib import contextmanager
from datetime import date
from typing import Any

from sqlalchemy import and_, event, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.exceptions import PermissionDeniedError


def business_today() -> date:
    from app.modules.identity.authorization import business_today as current_date

    return current_date()


def management_college(db: Session, actor_id: int, *, actor_locked: bool = False) -> int | None:
    from app.modules.academic.enrollment_models import (
        StudentManagerAppointment,
        TeacherCollegeBinding,
    )
    from app.modules.academic.enrollment_service import EnrollmentService
    from app.modules.identity.models import UserAccount
    from app.modules.identity.repository import IdentityRepository

    roles = set(IdentityRepository(db).list_effective_role_codes(actor_id))
    if "SUPER_ADMIN" in roles:
        return None
    if "TEACHER_ADMIN" in roles:
        row = db.get(
            TeacherCollegeBinding,
            actor_id,
            populate_existing=True,
            with_for_update={"read": True} if actor_locked else None,
        )
        if row is None:
            raise PermissionDeniedError("教师尚未配置学院，请管理员设置归属")
        return row.college_id
    if "STUDENT_AFFAIRS_MANAGER" in roles:
        user = db.get(UserAccount, actor_id)
        enrollment = (
            EnrollmentService(db).at(user.student_id, business_today())
            if user and user.student_id
            else None
        )
        appointment = db.scalar(
            select(StudentManagerAppointment)
            .where(
                StudentManagerAppointment.user_id == actor_id,
                StudentManagerAppointment.effective_from <= business_today(),
                or_(
                    StudentManagerAppointment.effective_to.is_(None),
                    StudentManagerAppointment.effective_to > business_today(),
                ),
            )
            .order_by(StudentManagerAppointment.id.desc())
            .limit(1)
        )
        if (
            enrollment
            and enrollment.status == "ENROLLED"
            and appointment
            and appointment.college_id == enrollment.college_id
        ):
            return appointment.college_id
    return None  # 学生/志愿者的可见性仍由各域本人关系决定。


def activate_query_scope(
    db: Session, actor_id: int, *, personal: bool = False, actor_locked: bool = False
) -> None:
    db.info["query_scope_actor_id"] = actor_id
    db.info["query_scope_personal"] = personal
    db.info["query_scope_actor_locked"] = actor_locked
    db.info.pop("college_query_scope", None)
    if personal:
        return
    college_id = management_college(db, actor_id, actor_locked=actor_locked)
    if college_id is not None:
        db.info["college_query_scope"] = {
            "actor_id": actor_id,
            "college_id": college_id,
            "on_date": business_today(),
        }


def recheck_query_scope(db: Session, actor_id: int) -> None:
    """服务取得账号锁后重验归属；不能沿用事务回滚前的范围。"""
    current = db.info.get("query_scope_actor_id")
    if current is None or isinstance(current, int):
        activate_query_scope(
            db,
            actor_id,
            personal=db.info.get("query_scope_personal", False) if current == actor_id else False,
            actor_locked=True,
        )


@contextmanager
def query_date(db: Session, on_date: date):
    """已授权课程的按日名单读取，不提前迁移学生当前工作区。"""
    previous = db.info.get("college_query_scope")
    if previous:
        db.info["college_query_scope"] = {**previous, "on_date": on_date}
    try:
        yield
    finally:
        if previous:
            db.info["college_query_scope"] = previous


@contextmanager
def personal_lookup(db: Session):
    """仅用于带本人 FK 谓词的存在性查询；禁止在该上下文写入。"""
    previous = db.info.pop("college_query_scope", None)
    personal = db.info.get("query_scope_personal", False)
    needs_refresh = db.info.get("query_scope_needs_refresh", False)
    db.info["query_scope_personal"] = True
    try:
        with db.no_autoflush:
            yield
    finally:
        db.info["query_scope_personal"] = personal
        if previous:
            db.info["college_query_scope"] = previous
        if needs_refresh:
            db.info["query_scope_needs_refresh"] = True


def predicates(college_id: int, today: date, actor_id: int | None = None) -> dict[type, Any]:
    from app.models import Base
    from app.modules.academic.enrollment_models import (
        CourseParticipation,
        EnrollmentChange,
        StudentDataPlan,
        StudentEnrollment,
        StudentManagerAppointment,
        TeacherCollegeBinding,
        TeachingClassAudience,
    )
    from app.modules.academic.models import (
        AdministrativeClass,
        Course,
        CourseSchedule,
        CourseScheduleWeek,
        Student,
        TeachingClass,
        TeachingClassStudent,
        VolunteerQualification,
    )
    from app.modules.attendance.models import AttendanceRecord, AttendanceRecordVersion
    from app.modules.identity.models import UserAccount
    from app.modules.importer.models import ImportBatch
    from app.modules.inspection.models import (
        InspectionAssignment,
        InspectionSubmission,
        InspectionTask,
        TaskDeadlineAssessment,
        TaskRosterMember,
        TaskRosterVersion,
        TaskScheduleSource,
    )
    from app.modules.objection.models import Objection, ObjectionFile
    from app.modules.report.models import Report, ReportVersion

    tables = Base.metadata.tables
    classes, students, enrollment = (
        tables["administrative_class"],
        tables["student"],
        tables["student_enrollment"],
    )
    task_ids = select(tables["inspection_task"].c.id).where(
        tables["inspection_task"].c.college_id == college_id
    )
    teaching_ids = select(tables["teaching_class"].c.id).where(
        tables["teaching_class"].c.college_id == college_id
    )
    class_ids = select(classes.c.id).where(classes.c.college_id == college_id)
    current_students = select(enrollment.c.student_id).where(
        enrollment.c.college_id == college_id,
        enrollment.c.superseded.is_(False),
        enrollment.c.effective_from <= today,
        or_(enrollment.c.effective_to.is_(None), enrollment.c.effective_to > today),
    )
    known = select(enrollment.c.student_id)
    student_predicate = or_(
        students.c.id.in_(current_students),
        students.c.id.not_in(known) & students.c.administrative_class_id.in_(class_ids),
    )
    student_ids = select(students.c.id).where(student_predicate)
    record_ids = select(tables["attendance_record"].c.id).where(
        tables["attendance_record"].c.task_id.in_(task_ids)
    )
    objection_ids = select(tables["objection"].c.id).where(
        tables["objection"].c.attendance_record_id.in_(record_ids)
    )
    report_ids = select(tables["report"].c.id).where(tables["report"].c.college_id == college_id)
    return {
        AdministrativeClass: AdministrativeClass.college_id == college_id,
        TeachingClass: TeachingClass.college_id == college_id,
        CourseSchedule: and_(
            CourseSchedule.college_id == college_id,
            CourseSchedule.teaching_class_id.in_(teaching_ids),
        ),
        Student: student_predicate,
        UserAccount: or_(
            UserAccount.id == actor_id,
            UserAccount.student_id.in_(student_ids),
            UserAccount.id.in_(
                select(TeacherCollegeBinding.__table__.c.user_id).where(
                    TeacherCollegeBinding.__table__.c.college_id == college_id
                )
            ),
        ),
        StudentEnrollment: StudentEnrollment.college_id == college_id,
        StudentManagerAppointment: StudentManagerAppointment.college_id == college_id,
        TeacherCollegeBinding: TeacherCollegeBinding.college_id == college_id,
        StudentDataPlan: StudentDataPlan.college_id == college_id,
        EnrollmentChange: EnrollmentChange.target_enrollment_id.in_(
            select(enrollment.c.id).where(enrollment.c.college_id == college_id)
        ),
        VolunteerQualification: VolunteerQualification.student_id.in_(student_ids),
        TeachingClassStudent: and_(
            TeachingClassStudent.teaching_class_id.in_(teaching_ids),
            TeachingClassStudent.student_id.in_(student_ids),
        ),
        CourseParticipation: and_(
            CourseParticipation.teaching_class_id.in_(teaching_ids),
            CourseParticipation.student_id.in_(student_ids),
        ),
        TeachingClassAudience: and_(
            TeachingClassAudience.teaching_class_id.in_(teaching_ids),
            TeachingClassAudience.administrative_class_id.in_(class_ids),
        ),
        Course: or_(Course.college_id.is_(None), Course.college_id == college_id),
        CourseScheduleWeek: CourseScheduleWeek.schedule_id.in_(
            select(tables["course_schedule"].c.id).where(
                tables["course_schedule"].c.college_id == college_id
            )
        ),
        InspectionTask: InspectionTask.college_id == college_id,
        InspectionAssignment: InspectionAssignment.task_id.in_(task_ids),
        InspectionSubmission: InspectionSubmission.task_id.in_(task_ids),
        TaskRosterMember: TaskRosterMember.task_id.in_(task_ids),
        TaskRosterVersion: TaskRosterVersion.task_id.in_(task_ids),
        TaskScheduleSource: TaskScheduleSource.task_id.in_(task_ids),
        TaskDeadlineAssessment: TaskDeadlineAssessment.task_id.in_(task_ids),
        AttendanceRecord: AttendanceRecord.task_id.in_(task_ids),
        AttendanceRecordVersion: AttendanceRecordVersion.attendance_record_id.in_(record_ids),
        Objection: Objection.attendance_record_id.in_(record_ids),
        ObjectionFile: ObjectionFile.objection_id.in_(objection_ids),
        ImportBatch: ImportBatch.college_id == college_id,
        Report: Report.college_id == college_id,
        ReportVersion: ReportVersion.report_id.in_(report_ids),
    }


def get_scoped(db: Session, entity, ident, **kwargs):
    info = db.info.get("college_query_scope")
    conditions = predicates(info["college_id"], info["on_date"], info["actor_id"]) if info else {}
    if entity in conditions:
        primary = entity.__mapper__.primary_key
        values = ident if isinstance(ident, tuple) else (ident,)
        if len(values) != len(primary):
            raise ValueError("主键数量无效")
        stmt = select(entity).where(
            *(column == value for column, value in zip(primary, values, strict=True)),
            conditions[entity],
        )
        if kwargs.get("with_for_update"):
            option = kwargs["with_for_update"]
            stmt = stmt.with_for_update(**(option if isinstance(option, dict) else {}))
        return db.scalar(stmt.execution_options(populate_existing=True))
    return Session.get(db, entity, ident, **kwargs)


class ScopedSession(Session):
    def get(self, entity, ident, **kwargs):
        return get_scoped(self, entity, ident, **kwargs)


@event.listens_for(Session, "do_orm_execute")
def filter_queries(state) -> None:
    db = state.session
    if db.info.pop("query_scope_needs_refresh", False) and not db.info.get(
        "query_scope_refreshing"
    ):
        db.info["query_scope_refreshing"] = True
        try:
            actor_id = db.info.get("query_scope_actor_id")
            if actor_id is not None:
                activate_query_scope(
                    db, actor_id, personal=db.info.get("query_scope_personal", False)
                )
        finally:
            db.info.pop("query_scope_refreshing", None)
    info = state.session.info.get("college_query_scope")
    if not info:
        return
    from sqlalchemy.sql.elements import TextClause

    if isinstance(state.statement, TextClause):
        raise PermissionDeniedError("学院工作区不能执行未限定资源范围的原生查询")
    conditions = predicates(info["college_id"], info["on_date"], info["actor_id"])
    if state.is_select:
        for model, condition in conditions.items():
            state.statement = state.statement.options(
                with_loader_criteria(model, condition, include_aliases=True)
            )
    elif state.is_update or state.is_delete:
        table = state.statement.table
        if table.name == "course":
            state.statement = state.statement.where(table.c.college_id == info["college_id"])
            return
        if table.name in {
            "semester",
            "calendar_override",
            "period_definition",
            "submission_deadline_day",
            "submission_deadline_version",
            "permission",
            "role_permission",
        }:
            raise PermissionDeniedError("学校共享数据只能由管理员修改")
        for model, condition in conditions.items():
            if table.name == getattr(model, "__tablename__", None):
                state.statement = state.statement.where(condition)
                break


@event.listens_for(Session, "after_transaction_end")
def invalidate_scope(db: ScopedSession, transaction) -> None:
    if transaction.parent is None and "query_scope_actor_id" in db.info:
        db.info["query_scope_needs_refresh"] = True
        db.info["query_scope_actor_locked"] = False


@event.listens_for(Session, "before_flush")
def protect_writes(db: ScopedSession, _context, _instances) -> None:
    info = db.info.get("college_query_scope")
    if not info:
        return
    from app.models import Base
    from app.modules.academic.models import (
        AdministrativeClass,
        CalendarOverride,
        PeriodDefinition,
        Semester,
        Student,
    )
    from app.modules.identity.models import UserAccount
    from app.modules.inspection.models import SubmissionDeadlineDay, SubmissionDeadlineVersion
    from app.modules.organization.models import College, School

    cid = info["college_id"]
    connection = db.connection()
    tables = Base.metadata.tables
    from sqlalchemy.exc import OperationalError

    from app.core.exceptions import ConflictError

    try:
        college = connection.execute(
            select(tables["college"].c.status)
            .where(tables["college"].c.id == cid)
            .with_for_update(nowait=True)
        ).scalar_one_or_none()
    except OperationalError as error:
        if error.orig is not None and error.orig.args and error.orig.args[0] in {3572, 1213, 1205}:
            raise ConflictError(message="学院配置正在变更，未写入，请稍后重新预览") from error
        raise
    actor = connection.execute(
        select(tables["user_account"].c.status).where(
            tables["user_account"].c.id == info["actor_id"]
        )
    ).scalar_one_or_none()
    if college != "ACTIVE" or actor != "ACTIVE":
        raise PermissionDeniedError("学院或操作者已停用")
    from app.modules.academic.enrollment_models import TeacherCollegeBinding

    binding = connection.execute(
        select(TeacherCollegeBinding.__table__.c.college_id)
        .where(TeacherCollegeBinding.__table__.c.user_id == info["actor_id"])
        .with_for_update(read=True)
    ).scalar_one_or_none()
    if binding is not None and binding != cid:
        raise PermissionDeniedError("教师归属已变化，请重新登录")
    conditions = predicates(cid, info["on_date"], info["actor_id"])
    for row in set(db.new) | set(db.dirty) | set(db.deleted):
        if row in db.dirty and not db.is_modified(row, include_collections=True):
            continue
        model = type(row)
        if model is College:
            from sqlalchemy import inspect

            changed = {a.key for a in inspect(row).attrs if a.history.has_changes()}
            if (
                row in db.new
                or row in db.deleted
                or row.id != cid
                or changed - {"configuration_revision", "authorization_revision", "updated_at"}
            ):
                raise PermissionDeniedError("学院基本设置仅由管理员维护")
            continue
        if model in {
            School,
            Semester,
            PeriodDefinition,
            CalendarOverride,
            SubmissionDeadlineDay,
            SubmissionDeadlineVersion,
        }:
            raise PermissionDeniedError("学校共享设置仅由管理员维护")
        if model is UserAccount and row.id != info["actor_id"]:
            if row.student_id is None:
                raise PermissionDeniedError("教师不能维护其他学院账号")
            target = connection.execute(
                select(tables["student"].c.id).where(
                    tables["student"].c.id == row.student_id, conditions[Student]
                )
            ).scalar_one_or_none()
            if target is None:
                raise PermissionDeniedError("账号不在本学院")
        if model not in conditions:
            continue
        if row not in db.new:
            primary = model.__mapper__.primary_key
            values = [getattr(row, c.key) for c in primary]
            if (
                connection.execute(
                    select(model.__table__).where(
                        *(c == value for c, value in zip(primary, values, strict=True)),
                        conditions[model],
                    )
                ).first()
                is None
            ):
                raise PermissionDeniedError("资源不在本学院，不能写入或删除")
        if hasattr(row, "college_id"):
            if row.college_id is None and row in db.new:
                row.college_id = cid
            if row.college_id != cid:
                raise PermissionDeniedError("不能写入其他学院")
        from sqlalchemy import inspect

        if (
            model is AdministrativeClass
            and inspect(row).attrs.college.history.has_changes()
            and row.college
            != connection.execute(
                select(tables["college"].c.name).where(tables["college"].c.id == cid)
            ).scalar_one()
        ):
            raise PermissionDeniedError("学院文本不能用于变更归属")
        parents = {
            "administrative_class_id": "administrative_class",
            "teaching_class_id": "teaching_class",
            "course_schedule_id": "course_schedule",
            "schedule_id": "course_schedule",
            "task_id": "inspection_task",
            "course_id": "course",
            "report_id": "report",
        }
        for attribute, table_name in parents.items():
            parent_id = getattr(row, attribute, None)
            if parent_id is None or attribute.endswith("_snapshot"):
                continue
            table = tables[table_name]
            owner = connection.execute(
                select(table.c.college_id).where(table.c.id == parent_id).with_for_update(read=True)
            ).first()
            if owner is None or (
                owner[0] != cid and not (table_name == "course" and owner[0] is None)
            ):
                raise PermissionDeniedError("父资源不在本学院")
