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
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.modules.attendance.models import AttendanceRecord
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
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, obj: object) -> None:
        self._session.add(obj)

    def flush(self) -> None:
        self._session.flush()

    # ---- 考勤锁定读（全局锁层级最外层，先于异议）----
    def get_attendance_for_update(self, record_id: int) -> AttendanceRecord | None:
        stmt = _for_update(select(AttendanceRecord).where(AttendanceRecord.id == record_id))
        return self._session.execute(stmt).scalar_one_or_none()

    def get_attendance(self, record_id: int) -> AttendanceRecord | None:
        return self._session.get(AttendanceRecord, record_id)

    # ---- 异议单条读 / 锁定读 ----
    def get_objection(self, objection_id: int) -> Objection | None:
        return self._session.get(Objection, objection_id)

    def get_objection_for_update(self, objection_id: int) -> Objection | None:
        stmt = _for_update(select(Objection).where(Objection.id == objection_id))
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
    ) -> tuple[list[Objection], int]:
        """按数据范围取异议。

        student_id 非空即本人范围（OWN_OBJECTION）强约束；为空表示管理范围不加学生谓词
        （PERMISSIONS.md 7.6 / 8）。
        """
        stmt = select(Objection)
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
