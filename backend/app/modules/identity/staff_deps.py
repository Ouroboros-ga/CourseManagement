"""教工本人依赖与 /me 摘要：每次请求回查档案、账号与学院。

独立于学生 `BindingCompleteDep`：pre_binding 的既有学生语义不变，本依赖只认服务端
会话账号对应的有效档案。档案停用、账号停用或解绑都会让下一次请求被拒绝，不等待
旧访问令牌过期，也不依赖前端隐藏入口。摘要只提供入口信息，不授予任何权限。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.academic.staff_repository import StaffRepository
from app.modules.identity.deps import CurrentUserDep
from app.modules.identity.models import UserAccount
from app.modules.identity.role_scope import business_today
from app.modules.identity.service import CurrentUser
from app.modules.organization.models import College

# 管理入口由固定角色派生，与本人教职工能力分开列出，不互相推导。
MANAGER_ROLES = frozenset({"SUPER_ADMIN", "TEACHER_ADMIN", "STUDENT_AFFAIRS_MANAGER"})


@dataclass(frozen=True)
class CurrentStaff:
    user: CurrentUser
    staff_id: int
    staff_no: str
    name: str
    school_id: int
    college_id: int
    lock_version: int


def active_profile(db: Session, user_id: int) -> FacultyStaff | None:
    """账号、档案与学院三者当前都有效才视为可用本人教工身份。

    学院还须与档案同校：跨校的错配数据不能被当作本人范围。
    """
    return db.scalar(
        select(FacultyStaff)
        .join(UserAccount, UserAccount.id == FacultyStaff.user_id)
        .join(College, College.id == FacultyStaff.college_id)
        .where(
            FacultyStaff.user_id == user_id,
            FacultyStaff.status == "ACTIVE",
            UserAccount.status == "ACTIVE",
            College.status == "ACTIVE",
            College.school_id == FacultyStaff.school_id,
        )
    )


def require_current_staff(
    user: CurrentUserDep, db: Annotated[Session, Depends(get_db)]
) -> CurrentStaff:
    row = active_profile(db, user.id)
    if row is None:
        raise PermissionDeniedError("教职工档案无效或尚未绑定")
    return CurrentStaff(
        user=user,
        staff_id=row.id,
        staff_no=row.staff_no,
        name=row.name,
        school_id=row.school_id,
        college_id=row.college_id,
        lock_version=row.lock_version,
    )


CurrentStaffDep = Annotated[CurrentStaff, Depends(require_current_staff)]


def _has_active_relation(db: Session, model, staff_id: int, day: date) -> bool:
    """本人视图存在性摘要；区间口径由 StaffRepository 统一提供。"""
    repo = StaffRepository(db)
    if model is TeachingStaffAssignment:
        return repo.has_active_teaching(staff_id, day)
    return repo.has_active_responsibility(staff_id, day)


def resolve_app_context(db: Session, user: CurrentUser) -> dict[str, Any]:
    """呈现模式与本人工作视图摘要；真实资源授权仍逐请求重新计算。"""
    account = db.scalar(
        select(UserAccount).where(UserAccount.id == user.id).execution_options(
            populate_existing=True
        )
    )
    profile = active_profile(db, user.id) if account is not None else None
    modes: list[str] = []
    if account is not None and (account.student_id is not None or "STUDENT" in user.roles):
        modes.append("student")
    if profile is not None:
        modes.append("staff")
    day = business_today()
    staff_summary = None
    if profile is not None:
        staff_summary = {
            "staff_id": str(profile.id),
            "staff_no": profile.staff_no,
            "name": profile.name,
            "college_id": str(profile.college_id),
            "views": {
                "teaching": _has_active_relation(db, TeachingStaffAssignment, profile.id, day),
                "responsible": _has_active_relation(db, ClassStaffResponsibility, profile.id, day),
            },
        }
    # 单一模式直接进入；并存时由客户端记住本人选择，服务端给确定的默认入口。
    default_mode: str | None = None
    if len(modes) == 1:
        default_mode = modes[0]
    elif "student" in modes:
        default_mode = "student"
    return {
        "modes": modes,
        "default_mode": default_mode,
        "administrator": bool(set(user.roles) & MANAGER_ROLES),
        "staff": staff_summary,
    }
