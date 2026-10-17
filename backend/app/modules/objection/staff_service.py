"""班主任/辅导员责任班级的异议聚合与一次审核（教职工协作，T05）。

固定口径（docs/development/STAFF_ARCHITECTURE_CONTRACT_20261017.md §2、§3）：
- 读取范围由**任务名单快照行政班**与本人当前责任关系共同决定，同学院不等于全部班级；
- 审核另外要求任务真实负责学院与档案学院一致（交集），外院任务只展示、不改判；
- 审核复用 `ObjectionService.apply_final_review` 的**唯一状态机**，与管理员终审同人同规则，
  不新建审批流，也不向普通教工拼接全局 `objection.final_review` / `attendance.correct`；
- 并发锚点是同一考勤行：按“账号→档案→考勤→异议”加锁后重读状态，教师更正推进版本时
  审核者必须先按当前版本重新核对，过期请求 409，异议不被静默关闭；
- 状态、考勤版本、报表源修订与审计单次提交，失败整体回滚。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.modules.academic.schemas import IdStr
from app.modules.academic.staff_models import FacultyStaff
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.role_scope import business_today
from app.modules.identity.staff_deps import CurrentStaff
from app.modules.objection.models import Objection
from app.modules.objection.schemas import ObjectionFinalReviewRequest, ObjectionResponse
from app.modules.objection.service import ObjectionService, assert_pending_review
from app.modules.organization.models import College

READ_BLOCK_REASONS = {
    "foreign_college": "该查课任务由其他学院负责，请由该学院审核；你仍可核对自己班级的记录",
}


class StaffResponsibleObjectionItem(BaseModel):
    """责任区异议行：完整异议上下文 + 负责学院 + 当前是否可改判。"""

    objection: ObjectionResponse
    task_id: IdStr | None = None
    responsible_college_id: IdStr | None = None
    responsible_college_name: str | None = None
    can_review: bool
    review_block_reason: str | None = None


class StaffResponsibleObjectionService(ObjectionService):
    """只服务本人责任班级；任何全局管理员入口在本对象上都不可达。"""

    def __init__(self, session: Session, staff: CurrentStaff) -> None:
        super().__init__(session)
        self._staff = staff
        self.actor = staff.user

    # -- 守卫：全局权限路径一律封死 -------------------------------------------- #
    def _require(self, actor_user_id: int, code: str) -> set[str]:
        raise PermissionDeniedError("责任区审核不使用全局异议权限")

    def _lock_actor(self, actor_user_id: int) -> set[str]:
        raise PermissionDeniedError("责任区审核不使用全局异议权限")

    def _legacy_manage_gate(self):
        raise PermissionDeniedError("责任区审核不使用学院管理入口")

    def _guard(self, *, lock: bool) -> UserAccount:
        """账号与档案当前都有效；写路径加锁重读，读路径不持行锁。"""
        if lock:
            account = IdentityRepository(self._session).get_user_by_id_for_update(self.actor.id)
        else:
            account = self._session.scalar(
                select(UserAccount)
                .where(UserAccount.id == self.actor.id)
                .execution_options(populate_existing=True)
            )
        if account is None or account.status != "ACTIVE":
            raise UnauthenticatedError("操作者账号不可用")
        stmt = select(FacultyStaff).where(
            FacultyStaff.id == self._staff.staff_id,
            FacultyStaff.user_id == self.actor.id,
        )
        if lock:
            stmt = stmt.with_for_update()
        profile = self._session.execute(
            stmt.execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if profile is None or profile.status != "ACTIVE":
            raise PermissionDeniedError("教职工档案已停用或未绑定")
        if profile.college_id != self._staff.college_id:
            raise PermissionDeniedError("教职工档案归属已变化，请重新登录")
        return account

    # -- 读取 ------------------------------------------------------------------ #
    def list_responsible(
        self,
        params: PageParams,
        *,
        final_status: str | None = None,
        initial_status: str | None = None,
        semester_id: int | None = None,
        administrative_class_id: int | None = None,
    ) -> dict[str, Any]:
        self._guard(lock=False)
        as_of = business_today()
        rows, total = self._repo.list_responsible(
            self.actor.id,
            as_of,
            params,
            final_status=final_status,
            initial_status=initial_status,
            semester_id=semester_id,
            administrative_class_id=administrative_class_id,
        )
        return {
            "items": self._items(rows, as_of),
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_responsible(self, objection_id: int) -> StaffResponsibleObjectionItem:
        self._guard(lock=False)
        as_of = business_today()
        found = self._repo.get_responsible(self.actor.id, as_of, objection_id)
        if found is None:
            raise NotFoundError("异议不存在或不在本人责任班级")
        obj = found[0]
        return self._items([obj], as_of)[0]

    def _items(self, objs: list[Objection], as_of) -> list[StaffResponsibleObjectionItem]:
        if not objs:
            return []
        ids = [o.id for o in objs]
        context = self._repo.responsible_context(ids)
        reviewable = self._repo.reviewable_responsible_ids(self.actor.id, as_of, ids)
        colleges = self._college_names({task[1] for task in context.values()})
        responses = self._assemble(objs)
        items: list[StaffResponsibleObjectionItem] = []
        for obj, response in zip(objs, responses, strict=True):
            pair = context.get(obj.id)
            task_id, college_id = pair if pair else (None, None)
            can_review = obj.id in reviewable
            items.append(
                StaffResponsibleObjectionItem(
                    objection=response,
                    task_id=str(task_id) if task_id is not None else None,
                    responsible_college_id=str(college_id) if college_id is not None else None,
                    responsible_college_name=(
                        colleges.get(college_id) if college_id is not None else None
                    ),
                    can_review=can_review,
                    review_block_reason=None
                    if can_review
                    else READ_BLOCK_REASONS["foreign_college"],
                )
            )
        return items

    def _college_names(self, college_ids: set[int]) -> dict[int, str]:
        ids = {cid for cid in college_ids if cid is not None}
        if not ids:
            return {}
        return {
            c.id: c.name
            for c in self._session.scalars(select(College).where(College.id.in_(ids)))
        }

    # -- 写：一次审核 ---------------------------------------------------------- #
    def review(
        self,
        objection_id: int,
        body: ObjectionFinalReviewRequest,
        request_id: str | None = None,
    ) -> ObjectionResponse:
        """责任区一次审核；授权、归档、版本与状态机都在同一事务内复核。"""
        self._guard(lock=True)
        # 学院锚点：责任关系/交接的写入同样先锁本院行，避免并发换届后仍按旧快照改判。
        self._session.scalar(
            select(College.id)
            .where(College.id == self._staff.college_id)
            .with_for_update()
        )
        anchor = self._repo.get_objection(objection_id)
        if anchor is None:
            raise NotFoundError("异议不存在或不在本人责任班级")

        # 全局锁层级：考勤 → 异议（技术方案 15），与教师更正共用同一行作为并发锚点。
        record = self._repo.get_attendance_for_update(anchor.attendance_record_id)
        obj = self._repo.get_objection_for_update(objection_id)
        if record is None or obj is None:
            raise NotFoundError("异议不存在或不在本人责任班级")

        self._assert_reviewable(obj.id)
        from app.modules.academic.archive import require_open_task

        require_open_task(self._session, record.task_id)
        assert_pending_review(obj)
        try:
            self.apply_final_review(
                obj, record, body, actor_user_id=self.actor.id, request_id=request_id
            )
        except Exception:
            self._session.rollback()
            raise
        self._session.commit()
        self._session.refresh(obj)
        return self._assemble([obj])[0]

    def _assert_reviewable(self, objection_id: int) -> None:
        """锁内复核：本人当前责任关系覆盖该生在任务快照中的班级，且任务由本院负责。"""
        context = self._repo.responsible_context([objection_id])
        if objection_id not in context:
            raise NotFoundError("异议不存在或不在本人责任班级")
        college_id = context[objection_id][1]
        if objection_id in self._repo.reviewable_responsible_ids(
            self.actor.id, business_today(), [objection_id]
        ):
            return
        if college_id != self._staff.college_id:
            raise PermissionDeniedError(READ_BLOCK_REASONS["foreign_college"])
        raise NotFoundError("异议不存在或不在本人责任班级")


__all__ = [
    "StaffResponsibleObjectionItem",
    "StaffResponsibleObjectionService",
]
