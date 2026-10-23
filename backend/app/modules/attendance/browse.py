"""共享的管理端考勤检索与 SQL 分组；只收窄已授权记录，不授予权限。"""

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import case, func, or_, select

from app.core.exceptions import AppError, ErrorCode
from app.modules.attendance.models import AttendanceRecord
from app.modules.inspection.models import InspectionSubmission, InspectionTask, TaskRosterMember


@dataclass(frozen=True)
class AttendanceFilters:
    start_date: date | None = None
    end_date: date | None = None
    keyword: str = ""
    administrative_class_id: int | None = None
    unknown_class: bool = False
    abnormal_only: bool = False


def attendance_filters(
    start_date: date | None = None,
    end_date: date | None = None,
    keyword: Annotated[str, Query(max_length=128)] = "",
    administrative_class_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    unknown_class: bool = False,
    abnormal_only: bool = False,
):
    if start_date and end_date and start_date > end_date:
        raise AppError(ErrorCode.VALIDATION_ERROR, "开始日期不能晚于结束日期", 422)
    return AttendanceFilters(start_date, end_date, keyword.strip(), administrative_class_id,
                             unknown_class, abnormal_only)


FiltersDep = Annotated[AttendanceFilters, Depends(attendance_filters)]


def roster_version():
    # 正式通过提交冻结名单版本；没有提交的旧资料才退回任务版本，绝不套用当前学籍。
    approved = (
        select(InspectionSubmission.roster_version)
        .where(InspectionSubmission.task_id == InspectionTask.id,
               InspectionSubmission.review_status == "APPROVED")
        .order_by(InspectionSubmission.attempt_no.desc()).limit(1)
        .correlate(InspectionTask).scalar_subquery()
    )
    return func.coalesce(approved, InspectionTask.roster_version)


def facts(authorized_ids, filters: AttendanceFilters, *, semester_id=None,
          task_id=None, effective_type=None, dimensions=None):
    """最多一名成员快照匹配一条考勤；所有分页与聚合共享同一过滤集合。"""
    r, t, m = AttendanceRecord, InspectionTask, TaskRosterMember
    statement = (
        select(r.id.label("record_id"), r.task_id, r.student_id, r.effective_type,
               t.inspection_date, t.start_period, t.end_period,
               t.course_name_snapshot.label("course_name"),
               t.class_name_snapshot.label("teaching_class_name"),
               t.classroom_snapshot.label("classroom"),
               m.administrative_class_id_snapshot.label("administrative_class_id"),
               m.class_name_snapshot.label("class_name"), m.student_no, m.name)
        .join(t, t.id == r.task_id)
        .outerjoin(m, (m.task_id == t.id) & (m.student_id == r.student_id)
                   & (m.roster_version == roster_version()))
        .where(r.id.in_(authorized_ids))
    )
    conditions = []
    if semester_id is not None:
        conditions.append(t.semester_id == semester_id)
    if task_id is not None:
        conditions.append(t.id == task_id)
    if effective_type is not None:
        conditions.append(r.effective_type == effective_type)
    if dimensions is not None:
        conditions.extend(dimensions.conditions())
    if filters.start_date:
        conditions.append(t.inspection_date >= filters.start_date)
    if filters.end_date:
        conditions.append(t.inspection_date <= filters.end_date)
    if filters.administrative_class_id is not None:
        conditions.append(m.administrative_class_id_snapshot == filters.administrative_class_id)
    if filters.unknown_class:
        conditions.append(m.administrative_class_id_snapshot.is_(None))
    if filters.abnormal_only:
        conditions.append(r.effective_type != "NORMAL")
    if filters.keyword:
        conditions.append(or_(*[column.contains(filters.keyword, autoescape=True) for column in
            (m.student_no, m.name, m.class_name_snapshot, t.course_name_snapshot,
             t.class_name_snapshot, t.classroom_snapshot)]))
    return statement.where(*conditions)


def counts(source):
    return [
        func.count().label("record_count"),
        func.count(func.distinct(source.c.task_id)).label("task_count"),
        *[func.coalesce(func.sum(case((source.c.effective_type == code, 1), else_=0)), 0)
          .label(code.lower() + "_count") for code in ("NORMAL", "LATE", "ABSENT", "LEAVE")],
    ]


def grouped_page(db, statement, params, group_by):
    source = statement.subquery()
    summary = dict(db.execute(select(*counts(source))).mappings().one())
    if group_by == "task":
        columns = [source.c.task_id, source.c.course_name, source.c.teaching_class_name,
                   source.c.inspection_date, source.c.start_period, source.c.end_period,
                   source.c.classroom]
        grouped = select(*columns, *counts(source)).group_by(*columns)
        order = [source.c.inspection_date.desc(), source.c.start_period, source.c.task_id.desc()]
    else:
        grouped = select(source.c.administrative_class_id,
                         func.max(source.c.class_name).label("class_name"),
                         *counts(source)).group_by(source.c.administrative_class_id)
        order = [source.c.administrative_class_id.is_(None), source.c.administrative_class_id]
    total = db.scalar(select(func.count()).select_from(grouped.subquery()))
    items = [dict(row) for row in db.execute(
        grouped.order_by(*order).limit(params.limit).offset(params.offset)
    ).mappings()]
    for row in items:
        for key in ("task_id", "administrative_class_id"):
            if key in row and row[key] is not None:
                row[key] = str(row[key])
        if group_by == "administrative_class" and row["administrative_class_id"] is None:
            row["class_name"] = "历史班级待核对"
    if group_by == "task" and items:
        # 仅查询本页任务最后通过的提交者，避免受派改动让历史执行人漂移，也避免逐行取人。
        from app.modules.academic.models import Student
        from app.modules.identity.models import UserAccount

        s = InspectionSubmission
        latest = select(s.task_id, func.max(s.attempt_no).label("attempt_no")).where(
            s.task_id.in_([int(row["task_id"]) for row in items]), s.review_status == "APPROVED"
        ).group_by(s.task_id).subquery()
        names = dict(db.execute(select(s.task_id, func.coalesce(
            Student.name, UserAccount.display_name)).join(
            latest, (latest.c.task_id == s.task_id) & (latest.c.attempt_no == s.attempt_no)
        ).join(UserAccount, UserAccount.id == s.volunteer_user_id)
            .outerjoin(Student, Student.id == UserAccount.student_id)).all())
        for row in items:
            row["volunteer_name"] = names.get(int(row["task_id"]))
        timings = dict(db.execute(select(InspectionTask.id, InspectionTask.time_snapshot).where(
            InspectionTask.id.in_([int(row["task_id"]) for row in items]))).all())
        for row in items:
            snapshot = timings.get(int(row["task_id"])) or {}
            row["time_basis"] = snapshot.get("time_basis", "PERIODS")
            row["time_label"] = snapshot.get("time_label")
    return dict(items=items, total=total, page=params.page, page_size=params.page_size,
                group_by=group_by, summary=summary)
