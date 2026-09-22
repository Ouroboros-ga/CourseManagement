"""报表源修订递增助手（技术方案 9.4、17）——P6 挂账的统一偿还点。

凡「影响考勤事实」的写路径（审核通过生成考勤、应到人数调整、考勤更正、异议终审改判），
均在其既有事务内、提交前调用本模块对 (semester_id, week_no) 的源修订号原子 +1，使周报
得以判断"最新版本是否落后于源数据"。

事务约定（技术方案 5.1，与全仓一致）：本模块 **flush-only、绝不 commit**——它只在调用方
已开启的事务里追加一条 UPSERT，提交仍由各业务 Service 末尾单次 commit 统一完成，从而与
考勤/审计写入保持原子性（同生同灭）。

并发正确性：以 MySQL 方言 ``INSERT ... ON DUPLICATE KEY UPDATE revision = revision + 1``
实现。对联合主键行的自增由服务端在该行排他锁下求值，天然串行化，杜绝"读-改-写"竞态导致
的丢失更新（并发多路径同时 bump 时 revision 单调、无跳号丢失）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules.inspection.models import InspectionTask
from app.modules.report.models import ReportSourceRevision


class SourceRevisionService:
    """(学期, 周次) 源修订号的集中递增入口。全部为无状态静态方法，仅依附传入 Session 的事务。"""

    @staticmethod
    def bump(session: Session, semester_id: int, week_no: int) -> None:
        """对 (semester_id, week_no) 修订号原子 +1（首建为 1）。flush-only，不提交。"""
        now = utcnow()
        stmt = mysql_insert(ReportSourceRevision).values(
            semester_id=semester_id,
            week_no=week_no,
            revision=1,
            updated_at=now,
        )
        stmt = stmt.on_duplicate_key_update(
            revision=ReportSourceRevision.revision + 1,
            updated_at=now,
        )
        session.execute(stmt)

    @staticmethod
    def bump_for_task(session: Session, task: InspectionTask) -> None:
        """已持有任务实体时直接按其学期/周次递增，省一次查询。"""
        SourceRevisionService.bump(session, task.semester_id, task.week_no)

    @staticmethod
    def bump_for_task_id(session: Session, task_id: int) -> None:
        """仅有 task_id（如考勤/异议更正路径）时，读取所属任务的学期/周次再递增。"""
        row = session.execute(
            select(InspectionTask.semester_id, InspectionTask.week_no).where(
                InspectionTask.id == task_id
            )
        ).one()
        SourceRevisionService.bump(session, int(row[0]), int(row[1]))


__all__ = ["SourceRevisionService"]
