"""文件仓储：仅数据访问，flush 不 commit（事务由 Service 顶层统一掌控）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.modules.file.models import FileObject, FileStatus


class FileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, obj: FileObject) -> None:
        self._session.add(obj)

    def get(self, file_id: int) -> FileObject | None:
        return self._session.get(FileObject, file_id)

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
        """
        stmt = (
            select(FileObject)
            .where(
                FileObject.status.in_(
                    (FileStatus.READY.value, FileStatus.PURGE_PENDING.value)
                ),
                FileObject.expires_at.is_not(None),
                FileObject.expires_at <= cutoff,
            )
            .order_by(FileObject.id)
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().all())

    def is_linked_to_submittable_for(
        self, *, file_id: int, actor_user_id: int, may_review: bool, may_read_own: bool
    ) -> bool:
        """文件是否挂在"该操作者可读/可审"的提交上（技术方案 16.2 业务资源归属）。

        可审者（submission.review）经任意提交链接即得访问；仅可读本人生成（submission.read）
        者，须链接到本人作为受派志愿者的提交。延迟导入提交模型，避免 file 模块导入期耦合。
        """
        if not (may_review or may_read_own):
            return False

        from app.modules.inspection.models import (
            InspectionSubmission,
            SubmissionFile,
        )

        conds = [SubmissionFile.file_id == file_id]
        if not may_review:
            conds.append(InspectionSubmission.volunteer_user_id == actor_user_id)

        stmt = select(
            exists(
                select(1)
                .select_from(SubmissionFile)
                .join(
                    InspectionSubmission,
                    InspectionSubmission.id == SubmissionFile.submission_id,
                )
                .where(*conds)
            )
        )
        return bool(self._session.execute(stmt).scalar_one())


__all__ = ["FileRepository"]
