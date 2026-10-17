"""任课教师对本人授课查课记录的直接更正（教职工协作，T04）。

授权与事务边界：
- 授权在写入事务内完成：锁操作者账号（复用 identity 仓储）与教职工档案，再锁考勤
  行与任务行，随后按 `staff_scope.teaching_class_condition` 逐条复核本人对任务
  （主教学班或全部来源课表教学班）在课次日的有效授课关系；LOCAL 不扩散共享视图，
  SHARED 仅匹配已确认映射。
- 教师更正不向普通教工拼接全局 `attendance.correct`，也不走管理员路径：
  版本写入复用 `AttendanceService.apply_correction` 的同一版本/审计/源修订事务，
  归档学期不因本人入口解锁；待处理异议保持原状态且必须在后续审核中重新核对版本。
- `current_version` 过期统一 409 VERSION_CONFLICT；记录不存在或不在本人授课范围内
  统一 404 防枚举。
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
from app.modules.academic.models import Semester, TeachingClass
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
from app.modules.identity.staff_scope import teaching_class_condition
from app.modules.inspection.models import InspectionTask, TaskScheduleSource


class StaffTeachingAttendanceService:
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

        self._assert_teaching_coverage(actor.id, task)
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

    def teaching_versions(
        self, actor: CurrentUser, staff_ref: CurrentStaff, record_id: int
    ) -> list[AttendanceVersionResponse]:
        """本人授课记录的认定历史：卡片允许 `view_history` 必须有对应入口，
        不能只过滤列表却把历史留给需要全院 `attendance.read` 的旧接口。"""
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
        self._assert_teaching_coverage(actor.id, task)
        return self._attendance.assemble_versions(record_id)

    def _assert_teaching_coverage(self, user_id: int, task: InspectionTask) -> None:
        """锁内复核本人当前有效授课关系同时覆盖记录任务与课次日期。"""
        class_ids: set[int] = set()
        if task.teaching_class_id:
            class_ids.add(task.teaching_class_id)
        class_ids.update(
            self._db.scalars(
                select(TaskScheduleSource.teaching_class_id).where(
                    TaskScheduleSource.task_id == task.id
                )
            )
        )
        class_ids.discard(None)
        covered = self._db.scalar(
            select(TeachingClass.id).where(
                TeachingClass.id.in_(class_ids),
                teaching_class_condition(
                    user_id, occurrence_on=task.inspection_date, as_of=business_today()
                ),
            )
        )
        if covered is None:
            raise NotFoundError("考勤记录不存在或无权访问")


__all__ = ["StaffTeachingAttendanceService"]
