"""异议仓储：仅取数 / 加锁读 / 增删改并 flush，绝不自行 commit。

约定与 attendance / inspection 仓储一致（技术方案 5.1、15、PERMISSIONS.md 13.2）：
- 提交由 Service 统一在事务末尾单次完成；
- 全局锁层级"考勤 → 异议"（技术方案 15）：创建 / 终审都**先锁考勤记录行**，再在其保护下
  检查 / 锁定异议行，保证并发下"同一考勤只有一个进行中异议"与"终审不覆盖他人新认定"；
- 列表返回 (items, total)，本人范围谓词由 Service 依数据范围传入（管理全量 / 本人 student_id）。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.common.pagination import PageParams
from app.core.exceptions import PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.resource_scope import ResourceScope
from app.modules.identity.staff_scope import responsible_class_condition
from app.modules.inspection.dimensions import TaskDimensions
from app.modules.inspection.models import InspectionTask, TaskRosterMember
from app.modules.objection.models import Objection, ObjectionFile, ObjectionFinalStatus


def _paged(session: Session, stmt: Select, params: PageParams) -> tuple[list, int]:
    count_sub = stmt.order_by(None).subquery()
    total = session.execute(select(func.count()).select_from(count_sub)).scalar_one()
    items = list(
        session.execute(stmt.limit(params.limit).offset(params.offset)).scalars().unique().all()
    )
    return items, int(total)


def _for_update(stmt: Select):  # noqa: ANN202 - 返回 Executable 由调用方 execute
    return stmt.with_for_update().execution_options(populate_existing=True)


class ObjectionRepository:
    def __init__(self, session: Session, scope: ResourceScope | None = None) -> None:
        if scope is not None and scope.action not in {"objection.read", "objection.final_review"}:
            raise PermissionDeniedError("动作不匹配异议范围")
        self._session = session
        self.scope = scope

    def _attendance(self):
        stmt = select(AttendanceRecord)
        if self.scope is not None:
            stmt = stmt.where(
                AttendanceRecord.task_id.in_(
                    select(InspectionTask.id).where(
                        self.scope.task_condition()
                    )
                )
            )
        return stmt.execution_options(populate_existing=True)

    def _objections(self):
        stmt = select(Objection)
        if self.scope is not None:
            stmt = stmt.where(
                self._attendance()
                .where(
                    AttendanceRecord.id == Objection.attendance_record_id,
                    AttendanceRecord.student_id == Objection.student_id,
                )
                .exists()
            )
        return stmt.execution_options(populate_existing=True)

    def add(self, obj: object) -> None:
        self._session.add(obj)

    def flush(self) -> None:
        self._session.flush()

    # ---- 考勤锁定读（全局锁层级最外层，先于异议）----
    def get_attendance_for_update(self, record_id: int) -> AttendanceRecord | None:
        stmt = _for_update(self._attendance().where(AttendanceRecord.id == record_id))
        return self._session.execute(stmt).scalar_one_or_none()

    def get_attendance(self, record_id: int) -> AttendanceRecord | None:
        return self._session.scalar(self._attendance().where(AttendanceRecord.id == record_id))

    # ---- 异议单条读 / 锁定读 ----
    def get_objection(self, objection_id: int) -> Objection | None:
        return self._session.scalar(self._objections().where(Objection.id == objection_id))

    def get_objection_for_update(self, objection_id: int) -> Objection | None:
        stmt = _for_update(self._objections().where(Objection.id == objection_id))
        return self._session.execute(stmt).scalar_one_or_none()

    # ---- 未完成异议查重（须已在 Service 中锁定同一考勤行，串行化并发创建）----
    def has_open_objection(self, attendance_record_id: int) -> bool:
        stmt = (
            select(Objection.id)
            .where(
                Objection.attendance_record_id == attendance_record_id,
                Objection.final_status == ObjectionFinalStatus.PENDING.value,
            )
            .limit(1)
        )
        return self._session.execute(stmt).first() is not None

    # ---- 列表（管理全量 / 本人 student_id；可按考勤、终审状态、初核状态过滤）----
    def list_objections(
        self,
        params: PageParams,
        *,
        student_id: int | None,
        attendance_record_id: int | None = None,
        final_status: str | None = None,
        initial_status: str | None = None,
        semester_id: int | None = None,
        dimensions: TaskDimensions | None = None,
    ) -> tuple[list[Objection], int]:
        """按数据范围取异议。

        student_id 非空即本人范围（OWN_OBJECTION）强约束；为空表示管理范围不加学生谓词
        （PERMISSIONS.md 7.6 / 8）。
        """
        stmt = self._objections()
        if semester_id is not None:
            stmt = stmt.where(Objection.attendance_record_id.in_(
                select(AttendanceRecord.id).join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                .where(InspectionTask.semester_id == semester_id)
            ))
        if dimensions is not None:
            stmt = stmt.where(Objection.attendance_record_id.in_(select(AttendanceRecord.id).where(AttendanceRecord.task_id.in_(select(InspectionTask.id).where(*dimensions.conditions())))))
        if student_id is not None:
            stmt = stmt.where(Objection.student_id == student_id)
        if attendance_record_id is not None:
            stmt = stmt.where(Objection.attendance_record_id == attendance_record_id)
        if final_status is not None:
            stmt = stmt.where(Objection.final_status == final_status)
        if initial_status is not None:
            stmt = stmt.where(Objection.initial_status == initial_status)
        stmt = stmt.order_by(Objection.id.desc())
        return _paged(self._session, stmt, params)

    # ---- 教工责任区（T05）：按任务名单快照行政班 + 当前责任关系收窄 ----
    def _responsible_exists(self, user_id: int, as_of, *, review_college: bool = False):
        """本人当前责任关系覆盖“该异议学生在此任务快照中的行政班”。

        `review_college=True` 追加任务真实负责学院与档案学院的交集，仅用于判定能否改判；
        省略时只表达读取范围（架构合同 §2：不能把 None 当作允许审核外院记录）。
        """
        att = aliased(AttendanceRecord)
        task = aliased(InspectionTask)
        member = aliased(TaskRosterMember)
        return (
            select(member.id)
            .select_from(member, att, task)
            .where(
                att.id == Objection.attendance_record_id,
                att.student_id == Objection.student_id,
                task.id == att.task_id,
                member.task_id == task.id,
                member.roster_version == task.roster_version,
                member.student_id == att.student_id,
                member.administrative_class_id_snapshot.is_not(None),
                responsible_class_condition(
                    user_id,
                    administrative_class_id=member.administrative_class_id_snapshot,
                    as_of=as_of,
                    review_college_id=task.college_id if review_college else None,
                ),
            )
            .correlate(Objection)
            .exists()
        )

    def list_responsible(
        self,
        user_id: int,
        as_of,
        params: PageParams,
        *,
        final_status: str | None = None,
        initial_status: str | None = None,
        semester_id: int | None = None,
        administrative_class_id: int | None = None,
    ) -> tuple[list[Objection], int]:
        """责任区异议列表：SQL 先授权再分页，绝不在 Python 侧过滤。"""
        stmt = self._objections().where(self._responsible_exists(user_id, as_of))
        if final_status is not None:
            stmt = stmt.where(Objection.final_status == final_status)
        if initial_status is not None:
            stmt = stmt.where(Objection.initial_status == initial_status)
        if semester_id is not None or administrative_class_id is not None:
            att = aliased(AttendanceRecord)
            task = aliased(InspectionTask)
            member = aliased(TaskRosterMember)
            narrowing = (
                select(member.id)
                .select_from(member, att, task)
                .where(
                    att.id == Objection.attendance_record_id,
                    task.id == att.task_id,
                    member.task_id == task.id,
                    member.roster_version == task.roster_version,
                    member.student_id == att.student_id,
                )
            )
            if semester_id is not None:
                narrowing = narrowing.where(task.semester_id == semester_id)
            if administrative_class_id is not None:
                narrowing = narrowing.where(
                    member.administrative_class_id_snapshot == administrative_class_id
                )
            stmt = stmt.where(narrowing.correlate(Objection).exists())
        stmt = stmt.order_by(Objection.id.desc())
        return _paged(self._session, stmt, params)

    def get_responsible(
        self, user_id: int, as_of, objection_id: int
    ) -> tuple[Objection, int, int] | None:
        """责任区内单条异议，连同任务与负责学院；不在范围即 None（防枚举）。"""
        row = self._session.execute(
            select(Objection, InspectionTask.id, InspectionTask.college_id)
            .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
            .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
            .where(
                Objection.id == objection_id,
                self._responsible_exists(user_id, as_of),
            )
        ).first()
        if row is None:
            return None
        return row[0], int(row[1]), int(row[2])

    def responsible_context(
        self, objection_ids: Sequence[int]
    ) -> dict[int, tuple[int, int]]:
        """异议 → (任务 id, 任务负责学院)；单次批量取，禁 N+1。"""
        ids = list(objection_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(Objection.id, InspectionTask.id, InspectionTask.college_id)
            .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
            .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
            .where(Objection.id.in_(ids))
        ).all()
        return {int(r[0]): (int(r[1]), int(r[2])) for r in rows if r[2] is not None}

    def reviewable_responsible_ids(
        self, user_id: int, as_of, objection_ids: Sequence[int]
    ) -> set[int]:
        """给定异议中，本人既有责任关系又属本院负责任务的那些 id（审核动作口径）。"""
        ids = list(objection_ids)
        if not ids:
            return set()
        rows = self._session.execute(
            select(Objection.id).where(
                Objection.id.in_(ids),
                self._responsible_exists(user_id, as_of, review_college=True),
            )
        ).all()
        return {int(r[0]) for r in rows}

    # ---- 证明材料关联（禁 N+1）----
    def map_file_ids_by_objection(self, objection_ids: Sequence[int]) -> dict[int, list[int]]:
        ids = list(objection_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(ObjectionFile.objection_id, ObjectionFile.file_id).where(
                ObjectionFile.objection_id.in_(ids)
            )
        ).all()
        out: dict[int, list[int]] = {int(oid): [] for oid in ids}
        for oid, fid in rows:
            out[int(oid)].append(int(fid))
        return out


__all__ = ["ObjectionRepository"]
