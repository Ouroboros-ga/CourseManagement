"""教职工绑定签发与核销：工号加一次性凭证，不按姓名/手机号认领。

与学生 `bind_student` 同构：清理快照事务后以 READ COMMITTED 顺序锁定账号、档案、
凭证，持锁后复查绑定状态，保证同一码不可双花、同一档案仅一次成功关联。已有管理员
身份只被明确关联，不派生新角色，也不合并同名账号。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.core.security import generate_friendly_binding_code, hash_token
from app.modules.academic.staff_models import FacultyStaff
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.authorization import STAFF_MANAGE_ACTION
from app.modules.identity.models import BindingTokenStatus, WechatIdentity
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_binding_models import StaffBindingToken
from app.modules.organization.models import College


class StaffBindingService:
    def __init__(self, session: Session, *, college_id: int | None = None) -> None:
        self._session = session
        self._repo = IdentityRepository(session)
        self._college_id = college_id
        self._settings = get_settings()

    # ------------------------------------------------------------------ #
    # 管理端：签发与作废（显式学院工作区）
    # ------------------------------------------------------------------ #
    def _require_workspace(self, actor: CurrentUser, *, write: bool = True) -> None:
        if self._college_id is None:
            raise PermissionDeniedError("教职工绑定码管理需要明确学院工作区")
        resolve_scope(self._session, actor, self._college_id, STAFF_MANAGE_ACTION, write=write)

    def _profile(self, staff_id: int, *, lock: bool = True) -> FacultyStaff:
        stmt = select(FacultyStaff).where(
            FacultyStaff.id == staff_id, FacultyStaff.college_id == self._college_id
        )
        if lock:
            stmt = stmt.with_for_update()
        row = self._session.execute(
            stmt.execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("教职工档案不在本院工作区")
        return row

    def issue_token(
        self,
        *,
        actor: CurrentUser,
        staff_id: int,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> tuple[int, str, datetime]:
        """签发并提交一次性绑定码；明文只返回一次。"""
        result = self.issue_token_in_transaction(
            actor=actor, staff_id=staff_id, reason=reason, request_id=request_id)
        self._session.commit()
        return result

    def issue_token_in_transaction(
        self,
        *,
        actor: CurrentUser,
        staff_id: int,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> tuple[int, str, datetime]:
        """签发 6 位绑定码，由调用方统一提交；导出落盘失败时凭证一起回滚。"""
        self._require_workspace(actor)
        row = self._profile(staff_id)
        if row.status != "ACTIVE":
            raise ConflictError(message="档案已停用，不能签发绑定码")
        # 档案行锁使同档案签发串行。不同档案可用相同短码，但同档案的历史码不复用，
        # 避免旧短信/截图重新变成有效凭证；不作废其他仍有效的已签发码。
        for _ in range(8):
            code = generate_friendly_binding_code(6)
            duplicate = self._session.scalar(
                select(StaffBindingToken.id).where(
                    StaffBindingToken.staff_id == row.id,
                    StaffBindingToken.token_hash == hash_token(code),
                ).limit(1)
            )
            if duplicate is None:
                break
        else:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "绑定码生成冲突，请重试签发")
        expires_at = utcnow() + timedelta(minutes=self._settings.binding_token_valid_minutes)
        token = StaffBindingToken(
            staff_id=row.id,
            token_hash=hash_token(code),
            status=BindingTokenStatus.UNUSED.value,
            expires_at=expires_at,
        )
        self._session.add(token)
        self._session.flush()
        self._audit(
            actor_id=actor.id,
            action="staff_binding_token.issue",
            resource_type="staff_binding_token",
            resource_id=str(token.id),
            before=None,
            after={"staff_id": row.id, "expires_at": expires_at.isoformat()},
            reason=reason,
            request_id=request_id,
        )
        return token.id, code, expires_at

    def revoke_token(
        self,
        *,
        actor: CurrentUser,
        token_id: int,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> int:
        """作废未使用的绑定码；已核销 409，已作废幂等。"""
        self._require_workspace(actor)
        staff_id = self._session.scalar(
            select(StaffBindingToken.staff_id)
            .join(FacultyStaff, FacultyStaff.id == StaffBindingToken.staff_id)
            .where(StaffBindingToken.id == token_id, FacultyStaff.college_id == self._college_id)
        )
        if staff_id is None:
            raise NotFoundError("绑定码不存在或不在本院工作区")
        self._profile(staff_id)
        token = self._session.execute(
            select(StaffBindingToken)
            .where(StaffBindingToken.id == token_id, StaffBindingToken.staff_id == staff_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if token is None:
            raise NotFoundError("绑定码不存在或不在本院工作区")
        if token.status == BindingTokenStatus.USED.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "绑定码已核销，无法作废")
        if token.status == BindingTokenStatus.EXPIRED.value:
            return token.id
        before: dict[str, object] = {"status": token.status}
        token.status = BindingTokenStatus.EXPIRED.value
        self._audit(
            actor_id=actor.id,
            action="staff_binding_token.revoke",
            resource_type="staff_binding_token",
            resource_id=str(token.id),
            before=before,
            after={"status": BindingTokenStatus.EXPIRED.value},
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()
        return token.id

    # ------------------------------------------------------------------ #
    # 本人：核销绑定码并关联档案
    # ------------------------------------------------------------------ #
    def redeem(
        self,
        *,
        user_id: int,
        staff_no: str,
        binding_code: str,
        request_id: str | None = None,
    ) -> dict[str, str]:
        self._session.rollback()
        # MySQL 用 READ COMMITTED 让持锁读看到最新已提交值；SQLite 方言不支持该级别。
        if self._session.get_bind().dialect.name == "mysql":
            self._session.connection(execution_options={"isolation_level": "READ COMMITTED"})

        user = self._repo.get_user_by_id_for_update(user_id)
        if user is None:
            raise NotFoundError("账号不存在")
        if not user.is_active:
            raise UnauthenticatedError("账号已停用")

        # 账号→档案→凭证的固定锁序；已关联的账号只能由管理端换绑。
        bound = self._session.execute(
            select(FacultyStaff)
            .where(FacultyStaff.user_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if bound is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该账号已关联教职工档案，请走管理端换绑")

        # 首次读取仅定位候选，不持凭证锁；随后固定按账号→档案→凭证锁定并重新核验。
        # 历史重复凭证必须排除已失效项；剩余仍有歧义时拒绝，不任取一条关联。
        digest = hash_token(binding_code)
        now = utcnow()
        candidates = self._session.execute(
            select(
                StaffBindingToken.id, StaffBindingToken.staff_id, FacultyStaff.staff_no,
                FacultyStaff.temporary_staff_no,
                StaffBindingToken.status, StaffBindingToken.expires_at, StaffBindingToken.used_at,
            )
            .join(FacultyStaff, FacultyStaff.id == StaffBindingToken.staff_id)
            .where(StaffBindingToken.token_hash == digest)
        ).all()
        matching = [row for row in candidates
                    if staff_no in (row.staff_no, row.temporary_staff_no)]
        live = [row for row in matching if (
            row.status == BindingTokenStatus.UNUSED.value
            and row.used_at is None and row.expires_at > now
        )]
        choices = live or matching or candidates
        if len(choices) != 1:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "绑定码无效或无法唯一确认档案", http_status=422
            )
        candidate = choices[0]
        profile = self._session.execute(
            select(FacultyStaff)
            .where(FacultyStaff.id == candidate.staff_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if profile is None:
            raise NotFoundError("教职工档案不存在")
        token = self._session.execute(
            select(StaffBindingToken)
            .where(
                StaffBindingToken.id == candidate.id,
                StaffBindingToken.staff_id == profile.id,
                StaffBindingToken.token_hash == digest,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if token is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "绑定码无效", http_status=422)

        now = utcnow()
        if token.status != BindingTokenStatus.UNUSED.value or token.used_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "绑定码已被使用")
        if token.expires_at <= now:
            token.status = BindingTokenStatus.EXPIRED.value
            self._session.commit()
            raise ConflictError(ErrorCode.STATE_CONFLICT, "绑定码已过期")

        if staff_no not in (profile.staff_no, profile.temporary_staff_no):
            # 不匹配按无效处理并计数，不泄露该码对应哪位教职工。
            token.failed_attempts += 1
            self._session.commit()
            raise AppError(ErrorCode.VALIDATION_ERROR, "绑定码与工号不匹配", http_status=422)

        # 持锁后复查：并发抢绑同一档案时，后到者读到已提交的关联账号并被拒绝。
        if profile.user_id is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该档案已关联其他账号，请联系管理员处理")
        if profile.status != "ACTIVE":
            raise ConflictError(ErrorCode.STATE_CONFLICT, "教职工档案已停用，无法绑定")
        college = self._session.get(College, profile.college_id, populate_existing=True)
        if college is None or college.status != "ACTIVE":
            raise ConflictError(ErrorCode.STATE_CONFLICT, "教职工所属学院已停用")

        profile.user_id = user.id
        profile.lock_version += 1
        token.status = BindingTokenStatus.USED.value
        token.used_at = now
        self._audit(
            actor_id=user.id,
            action="staff.bind",
            resource_type="faculty_staff",
            resource_id=str(profile.id),
            before={"user_id": None},
            after={
                "user_id": user.id,
                "staff_no": profile.staff_no,
                "college_id": profile.college_id,
                "lock_version": profile.lock_version,
                "has_wechat": self._has_wechat(user.id),
            },
            reason=None,
            request_id=request_id,
        )
        self._session.commit()
        return {
            "staff_id": str(profile.id),
            "staff_no": profile.staff_no,
            "name": profile.name,
            "college_id": str(profile.college_id),
            "user_id": str(user.id),
        }

    def _has_wechat(self, user_id: int) -> bool:
        return (
            self._session.execute(
                select(WechatIdentity.id).where(WechatIdentity.user_id == user_id).limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def _audit(
        self,
        *,
        actor_id: int,
        action: str,
        resource_type: str,
        resource_id: str,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
        reason: str | None,
        request_id: str | None,
    ) -> None:
        """追加审计事实（同事务，仅 flush；提交由公共方法统一负责）。"""
        if self._college_id is not None:
            after = scoped_snapshot(after, self._college_id)
        self._session.add(
            AuditLog(
                actor_user_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_json=before,
                after_json=after,
                reason=reason,
                request_id=request_id,
            )
        )
        self._session.flush()
