"""教职工本人的考勤更正与认定历史（教职工协作 T04/T07，审查 F1/F6）。

授权与事务边界：
- 授权在写入事务内完成：锁操作者账号（复用 identity 仓储）与教职工档案，再锁考勤
  行与任务行，随后**逐学生**复核本人对该生在本任务里的授课归属
  （`inspection/staff_record_query.teaching_membership_for_record`）。合班任务不再因为
  任务里有一个自己的班就放行整条名单；LOCAL 不扩散共享视图，SHARED 仅匹配已确认映射；
  归属取自名单快照冻结的来源教学班，不回头用当前选课名单猜历史。
- 完全不属于本人的学生统一 404 防枚举；归属待核对（历史名单版本没有来源记录，或该生
  同时属于其他教学班）可读、可看历史，但写入口 403 并说明原因，由既有获授权管理路径核实。
- 教师更正不向普通教工拼接全局 `attendance.correct`，也不走管理员路径：
  版本写入复用 `AttendanceService.apply_correction` 的同一版本/审计/源修订事务，
  归档学期不因本人入口解锁；待处理异议保持原状态且必须在后续审核中重新核对版本。
- `current_version` 过期统一 409 VERSION_CONFLICT。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.modules.academic.models import Semester
from app.modules.academic.staff_models import FacultyStaff
from app.modules.attendance.repository import AttendanceRepository
from app.modules.attendance.schemas import (
    AttendanceCorrectionRequest,
    AttendanceVersionResponse,
    ManagementAttendanceResponse,
)
from app.modules.attendance.service import AttendanceService
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.role_scope import business_today
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_deps import CurrentStaff
from app.modules.identity.staff_scope import responsible_class_condition
from app.modules.inspection.models import InspectionTask, TaskRosterMember


class StaffAttendanceSelfService:
    """教职工本人授课视角的考勤更正服务；只服务本人资源，不产生管理范围。"""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._identity = IdentityRepository(db)
        self._repo = AttendanceRepository(db)
        self._attendance = AttendanceService(db)

    def _guard(self, actor: CurrentUser, staff_ref: CurrentStaff, *, lock: bool):
        """账号与档案当前都有效；写入口加锁重读，历史读取不持行锁。"""
        if lock:
            account = self._identity.get_user_by_id_for_update(actor.id)
        else:
            account = self._db.scalar(
                select(UserAccount)
                .where(UserAccount.id == actor.id)
                .execution_options(populate_existing=True)
            )
        if account is None or account.status != "ACTIVE":
            raise UnauthenticatedError("操作者账号不可用")
        stmt = select(FacultyStaff).where(
            FacultyStaff.id == staff_ref.staff_id,
            FacultyStaff.user_id == actor.id,
        )
        if lock:
            stmt = stmt.with_for_update()
        profile = self._db.execute(
            stmt.execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if profile is None:
            raise NotFoundError("教职工档案不存在")
        if profile.status != "ACTIVE":
            raise PermissionDeniedError("教职工档案已停用")
        return account, profile

    def correct_teaching(
        self,
        actor: CurrentUser,
        staff_ref: CurrentStaff,
        record_id: int,
        body: AttendanceCorrectionRequest,
        request_id: str | None = None,
    ) -> ManagementAttendanceResponse:
        """更正本人授课覆盖的教学班考勤；授权失效/非本人课程一律拒绝。"""
        self._guard(actor, staff_ref, lock=True)

        record = self._repo.get_record_for_update(record_id)
        if record is None:
            raise NotFoundError("考勤记录不存在或无权访问")
        task = self._db.execute(
            select(InspectionTask)
            .where(InspectionTask.id == record.task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        semester_status = self._db.scalar(
            select(Semester.status)
            .where(Semester.id == task.semester_id)
            .with_for_update(read=True)
        )
        if semester_status == "ARCHIVED":
            # 归档学期只走既有获授权归档更正入口，不因本人授课入口自动解锁。
            raise ConflictError(message="该学期已归档，请使用获授权的归档更正入口")

        self._assert_correctable(actor.id, task, record.student_id)
        try:
            self._attendance.apply_correction(
                record,
                body,
                actor_user_id=actor.id,
                request_id=request_id,
                archived=False,
            )
        except Exception:
            self._db.rollback()
            raise
        self._db.commit()
        return self._attendance._assemble([record])[0]

    def record_versions(
        self,
        actor: CurrentUser,
        staff_ref: CurrentStaff,
        record_id: int,
        view: str,
    ) -> list[AttendanceVersionResponse]:
        """本人可见考勤记录的认定历史：卡片声明哪个动作就必须有对应入口。

        明细在两种视图都会给出 ``view_history``，因此历史也必须两种视图都可用——纯辅导员
        没有授课关系，若历史只按授课谓词放行，按钮会稳定失败。按 ``view`` 使用与列表
        相同的范围谓词：授课视图核对本人当前授课关系，责任视图核对该生在任务名单快照中的
        行政班是否由本人负责。读入口不持 ``FOR UPDATE`` 行锁，越界与不存在统一 404。
        """
        if view not in ("teaching", "responsible"):
            raise NotFoundError("考勤记录不存在或无权访问")
        self._guard(actor, staff_ref, lock=False)
        record = self._repo.get_record(record_id)
        if record is None:
            raise NotFoundError("考勤记录不存在或无权访问")
        task = self._db.scalar(
            select(InspectionTask)
            .where(InspectionTask.id == record.task_id)
            .execution_options(populate_existing=True)
        )
        if task is None:
            raise NotFoundError("考勤记录不存在或无权访问")
        if view == "teaching":
            self._assert_record_visible(actor.id, task, record.student_id)
        else:
            self._assert_responsible_coverage(actor.id, task, record.student_id)
        return self._attendance.assemble_versions(record_id)

    def _membership(self, task: InspectionTask, user_id: int, student_id: int):
        from app.modules.inspection.staff_record_query import teaching_membership_for_record

        return teaching_membership_for_record(
            self._db, task, user_id, business_today(), student_id
        )

    def _assert_record_visible(self, user_id: int, task: InspectionTask, student_id: int) -> None:
        """读取（含认定历史）：合班任务里非本人授课的学生不返回，归属不清的仍可读但不可改。"""
        visible, _correctable, _reason = self._membership(task, user_id, student_id)
        if not visible:
            raise NotFoundError("考勤记录不存在或无权访问")

    def _assert_correctable(self, user_id: int, task: InspectionTask, student_id: int) -> None:
        """写入：逐学生核对冻结的教学班归属，不因为同任务里有自己的班就放行整条名单。"""
        visible, correctable, reason = self._membership(task, user_id, student_id)
        if not visible:
            raise NotFoundError("考勤记录不存在或无权访问")
        if not correctable:
            raise PermissionDeniedError(reason or "该生的授课归属待核对，暂不能由本人更正")

    def _assert_responsible_coverage(
        self, user_id: int, task: InspectionTask, student_id: int
    ) -> None:
        """责任视图：该生在本次名单快照中的行政班由本人当前责任关系覆盖。

        与 ``StaffRecordQueryService`` 的读取谓词同一口径（名单快照行政班，不用当前学籍，
        也不要求任务由本院负责——只读命中不授予改判或材料权限）。
        """
        hit = self._db.scalar(
            select(TaskRosterMember.id).where(
                TaskRosterMember.task_id == task.id,
                TaskRosterMember.student_id == student_id,
                TaskRosterMember.roster_version == task.roster_version,
                responsible_class_condition(
                    user_id,
                    administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                    as_of=business_today(),
                ),
            )
        )
        if hit is None:
            raise NotFoundError("考勤记录不存在或无权访问")


__all__ = ["StaffAttendanceSelfService"]
