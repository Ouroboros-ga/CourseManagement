"""考勤域仓储：仅取数 / 加锁读 / 增删改并 flush，绝不自行 commit。

约定与 inspection / academic 仓储一致（技术方案 5.1、15、PERMISSIONS.md 13.2）：
- 提交由 Service 统一在事务末尾单次完成；
- 更正走行级串行写用 `get_record_for_update`（SELECT ... FOR UPDATE + populate_existing）；
- 列表返回 (items, total)，可见性谓词由 Service 依数据范围传入（管理全量 / 本人 student_id）。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordVersion,
)
from app.modules.inspection.models import InspectionTask, TaskRosterMember


def _paged(session: Session, stmt: Select, params: PageParams) -> tuple[list, int]:
    count_sub = stmt.order_by(None).subquery()
    total = session.execute(select(func.count()).select_from(count_sub)).scalar_one()
    items = list(
        session.execute(stmt.limit(params.limit).offset(params.offset)).scalars().unique().all()
    )
    return items, int(total)


def _for_update(stmt: Select):  # noqa: ANN202 - 返回 Executable 由调用方 execute
    return stmt.with_for_update().execution_options(populate_existing=True)


class AttendanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, obj: object) -> None:
        self._session.add(obj)

    def flush(self) -> None:
        self._session.flush()

    # ---- 单条读 / 锁定读 ----
    def get_record(self, record_id: int) -> AttendanceRecord | None:
        return self._session.get(AttendanceRecord, record_id)

    def get_record_for_update(self, record_id: int) -> AttendanceRecord | None:
        stmt = _for_update(
            select(AttendanceRecord).where(AttendanceRecord.id == record_id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    # ---- 列表（管理全量 / 本人 student_id；可按任务、学期、认定类型过滤）----
    def list_records(
        self,
        params: PageParams,
        *,
        student_id: int | None,
        task_id: int | None = None,
        semester_id: int | None = None,
        effective_type: str | None = None,
    ) -> tuple[list[AttendanceRecord], int]:
        """按数据范围取当前考勤。

        student_id 非空即本人范围（SELF_STUDENT）强约束；为空表示管理范围不加学生谓词。
        任务/学期过滤经关联 inspection_task（考勤本身不存学期，随任务归属，技术方案 9.2）。
        """
        stmt = select(AttendanceRecord)
        if student_id is not None:
            stmt = stmt.where(AttendanceRecord.student_id == student_id)
        if effective_type is not None:
            stmt = stmt.where(AttendanceRecord.effective_type == effective_type)
        if task_id is not None:
            stmt = stmt.where(AttendanceRecord.task_id == task_id)
        if semester_id is not None:
            task_subq = select(InspectionTask.id).where(
                InspectionTask.semester_id == semester_id
            )
            stmt = stmt.where(AttendanceRecord.task_id.in_(task_subq))
        stmt = stmt.order_by(AttendanceRecord.id.desc())
        return _paged(self._session, stmt, params)

    # ---- 历史版本（随记录可见性由 Service 先鉴范围，再取版本）----
    def list_versions(self, record_id: int) -> list[AttendanceRecordVersion]:
        return list(
            self._session.execute(
                select(AttendanceRecordVersion)
                .where(AttendanceRecordVersion.attendance_record_id == record_id)
                .order_by(AttendanceRecordVersion.version_no)
            )
            .scalars()
            .all()
        )

    # ---- 批量装配辅助（禁 N+1，技术方案 12）----
    def map_tasks_by_ids(self, task_ids: Sequence[int]) -> dict[int, InspectionTask]:
        ids = list(task_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(InspectionTask).where(InspectionTask.id.in_(ids))
        ).scalars().all()
        return {t.id: t for t in rows}

    def map_roster_display(
        self, pairs: Sequence[tuple[int, int]], version_by_task: dict[int, int]
    ) -> dict[tuple[int, int], tuple[str | None, str | None]]:
        """为 (task_id, student_id) 对取当前名单版本快照学号/姓名。

        按各任务当前 roster_version 过滤，保证展示与"据以生成考勤"的名单一致（技术方案 10/12）。
        """
        if not pairs:
            return {}
        task_ids = list({tid for tid, _ in pairs})
        student_ids = list({sid for _, sid in pairs})
        rows = self._session.execute(
            select(
                TaskRosterMember.task_id,
                TaskRosterMember.student_id,
                TaskRosterMember.roster_version,
                TaskRosterMember.student_no,
                TaskRosterMember.name,
            ).where(
                TaskRosterMember.task_id.in_(task_ids),
                TaskRosterMember.student_id.in_(student_ids),
            )
        ).all()
        out: dict[tuple[int, int], tuple[str | None, str | None]] = {}
        for tid, sid, rver, sno, name in rows:
            if rver == version_by_task.get(tid):
                out[(int(tid), int(sid))] = (sno, name)
        return out


__all__ = ["AttendanceRepository"]
