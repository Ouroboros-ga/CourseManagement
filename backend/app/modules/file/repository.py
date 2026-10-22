"""文件仓储：仅数据访问，flush 不 commit（事务由 Service 顶层统一掌控）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, or_, select, true
from sqlalchemy.orm import Session

from app.modules.file.models import FileObject, FileStatus


class FileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, obj: FileObject) -> None:
        self._session.add(obj)

    def is_linked_to_scoped_report(self, file_id: int, college_ids: frozenset[int] | None) -> bool:
        from app.modules.report.models import Report, ReportVersion

        stmt = select(ReportVersion.id).join(Report, Report.id == ReportVersion.report_id).where(
            ReportVersion.status == "PUBLISHED",
            or_(ReportVersion.excel_file_id == file_id, ReportVersion.snapshot_file_id == file_id,
                ReportVersion.word_file_id == file_id),
        )
        if college_ids is not None:
            stmt = stmt.where(Report.college_id.in_(college_ids),
                ReportVersion.college_id_snapshot == Report.college_id)
        return self._session.scalar(stmt.limit(1)) is not None

    def get(self, file_id: int) -> FileObject | None:
        return self._session.get(FileObject, file_id)

    def has_business_link(self, file_id: int) -> bool:
        """只查关联存在性；上传人不能绕过已关联业务资源的范围和身份。"""
        from app.modules.inspection.models import SubmissionFile
        from app.modules.objection.models import ObjectionFile
        from app.modules.report.models import ReportVersion

        for model, columns in [
            (SubmissionFile, ["file_id"]),
            (ObjectionFile, ["file_id"]),
            (ReportVersion, ["snapshot_file_id", "excel_file_id", "word_file_id"]),
        ]:
            table = model.__table__
            condition = None
            for column in columns:
                clause = table.c[column] == file_id
                condition = clause if condition is None else condition | clause
            if (
                condition is not None
                and self._session.scalar(
                    select(table.c.id if "id" in table.c else table.c.file_id)
                    .where(condition)
                    .limit(1)
                )
                is not None
            ):
                return True
        return False

    def is_linked_to_report(self, file_id: int) -> bool:
        from app.modules.report.models import ReportVersion

        return (
            self._session.scalar(
                select(ReportVersion.id)
                .where(
                    (ReportVersion.snapshot_file_id == file_id)
                    | (ReportVersion.excel_file_id == file_id)
                    | (ReportVersion.word_file_id == file_id)
                )
                .limit(1)
            )
            is not None
        )

    def get_for_update(self, file_id: int) -> FileObject | None:
        stmt = (
            select(FileObject)
            .where(FileObject.id == file_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_purge_candidates(self, *, cutoff: datetime, limit: int) -> list[FileObject]:
        """到期需清理的文件：READY（尚未标记）或 PURGE_PENDING（上次标记但底层删除失败待重试）。

        仅取 expires_at 已固化且已到期（<= cutoff）者；按 id 升序，供定时脚本可续跑分批处理。
        被**未完成异议**（objection.final_status=PENDING）引用的材料**暂停清理**——异议关闭后
        其自然重新纳入候选（技术方案 16.3、538/713；与新建异议关联材料按同一文件行锁串行化）。
        """
        stmt = (
            select(FileObject)
            .where(
                FileObject.status.in_((FileStatus.READY.value, FileStatus.PURGE_PENDING.value)),
                FileObject.expires_at.is_not(None),
                FileObject.expires_at <= cutoff,
            )
            .order_by(FileObject.id)
            .limit(limit)
        )

        # 延迟导入异议模型，避免 file 模块导入期耦合异议域；排除被未完成异议引用的文件。
        from app.modules.objection.models import Objection, ObjectionFile, ObjectionFinalStatus

        open_objection_files = (
            select(ObjectionFile.file_id)
            .join(Objection, Objection.id == ObjectionFile.objection_id)
            .where(Objection.final_status == ObjectionFinalStatus.PENDING.value)
        )
        stmt = stmt.where(FileObject.id.not_in(open_objection_files))
        return list(self._session.execute(stmt).scalars().all())

    def is_linked_to_submittable_for(
        self, *, file_id: int, actor_user_id: int, may_review: bool, may_read_own: bool,
        review_college_ids: frozenset[int] | None = None,
        review_task_condition=None,
    ) -> bool:
        """文件是否挂在"该操作者可读/可审"的提交上（技术方案 16.2 业务资源归属）。

        可审者（submission.review）经任意提交链接即得访问；仅可读本人生成（submission.read）
        者，须链接到本人作为受派志愿者的提交。延迟导入提交模型，避免 file 模块导入期耦合。
        """
        if not (may_review or may_read_own):
            return False

        from app.modules.inspection.models import (
            InspectionSubmission,
            InspectionTask,
            SubmissionFile,
        )

        conds = [SubmissionFile.file_id == file_id]
        from sqlalchemy import false, or_

        managed = (InspectionTask.college_id.in_(review_college_ids)
                   if review_college_ids is not None else true()) if may_review else false()
        if may_review and review_task_condition is not None:
            managed = review_task_condition
        own = InspectionSubmission.volunteer_user_id == actor_user_id if may_read_own else false()
        conds.append(or_(managed, own))

        stmt = select(
            exists(
                select(1)
                .select_from(SubmissionFile)
                .join(
                    InspectionSubmission,
                    InspectionSubmission.id == SubmissionFile.submission_id,
                )
                .join(InspectionTask, InspectionTask.id == InspectionSubmission.task_id)
                .where(*conds)
            )
        )
        return bool(self._session.execute(stmt).scalar_one())

    def is_linked_to_own_attendance(self, *, file_id: int, actor_user_id: int) -> bool:
        from app.modules.attendance.effect_scope import see_withdrawn
        from app.modules.attendance.evidence import attendance_photo_query
        from app.modules.attendance.models import AttendanceRecord
        from app.modules.identity.models import UserAccount
        from app.modules.inspection.models import SubmissionFile

        linked = (
            attendance_photo_query()
            .join(UserAccount, UserAccount.student_id == AttendanceRecord.student_id)
            .where(
                UserAccount.id == actor_user_id,
                UserAccount.status == "ACTIVE",
                SubmissionFile.file_id == file_id,
            )
        )
        # 证据可达性看的是"曾据以生成"，不是"结论是否仍有效"：撤回后本人仍能读自己的照片。
        return bool(
            self._session.execute(see_withdrawn(select(exists(linked)))).scalar_one()
        )

    def is_linked_to_readable_objection_for(
        self, *, file_id: int, actor_user_id: int, may_manage: bool, may_read_own: bool,
        management_college_ids: frozenset[int] | None = None,
        management_task_condition=None,
    ) -> bool:
        """仅异议已关联材料可按管理权限或有效学生绑定签发访问链接。"""
        if not (may_manage or may_read_own):
            return False

        from sqlalchemy import false, or_

        from app.modules.attendance.effect_scope import see_withdrawn
        from app.modules.attendance.models import AttendanceRecord
        from app.modules.identity.models import UserAccount
        from app.modules.inspection.models import InspectionTask
        from app.modules.objection.models import Objection, ObjectionFile

        linked = (
            select(1)
            .select_from(ObjectionFile)
            .join(Objection, Objection.id == ObjectionFile.objection_id)
            .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
            .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
            .where(ObjectionFile.file_id == file_id)
        )
        managed = (InspectionTask.college_id.in_(management_college_ids)
                   if management_college_ids is not None else true()) if may_manage else false()
        if may_manage and management_task_condition is not None:
            managed = management_task_condition
        own = exists(select(UserAccount.id).where(
            UserAccount.id == actor_user_id, UserAccount.status == "ACTIVE",
            UserAccount.student_id == Objection.student_id,
        )) if may_read_own else false()
        linked = linked.where(
            Objection.student_id == AttendanceRecord.student_id, or_(managed, own)
        )
        return bool(
            self._session.execute(see_withdrawn(select(exists(linked)))).scalar_one()
        )

    def is_linked_to_pending_objection(self, file_id: int) -> bool:
        """保留期已过时，未结案异议关联的证明材料仍可读取。"""
        from app.modules.objection.models import Objection, ObjectionFile, ObjectionFinalStatus

        linked = (
            select(1)
            .select_from(ObjectionFile)
            .join(Objection, Objection.id == ObjectionFile.objection_id)
            .where(
                ObjectionFile.file_id == file_id,
                Objection.final_status == ObjectionFinalStatus.PENDING.value,
            )
        )
        return bool(self._session.execute(select(exists(linked))).scalar_one())


__all__ = ["FileRepository"]
