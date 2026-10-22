"""文件服务：受限上传、状态流转、短时签名访问与下载校验（技术方案 16）。

事务约定与 identity/academic/importer/inspection 一致：Repository 只 flush 不 commit，
Service 顶层在成功前单次 commit。上传先经校验与存储落盘再建 READY 行 + 审计并同事务提交；
对象存储写非事务，若随后提交失败会留下随机键孤儿对象（不可枚举、无引用），由清理侧忽略，
重试上传生成新键，不影响正确性。

访问授权（技术方案 16.2）：文件无独立功能权限，按"业务资源归属"放行——上传者本人恒可
访问自己上传的 READY 材料；已关联到某提交的材料，具备 submission.review 的审核者可访问、
具备 submission.read 的志愿者仅能经本人提交访问；异议证明仅在关联异议后，按本人
objection.read 或管理初核/终审权限访问。不可见资源统一以 404 处理，避免枚举探测。
下载路由不再鉴权，只校验 HMAC 签名与过期（技术方案 16.2 明确不即时撤销已发出链接）。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    FileExpiredError,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.modules.audit.models import AuditLog
from app.modules.file import permissions as fperm
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import FileAccessResponse, FileUploadResponse
from app.modules.file.storage import StorageBackend, build_default_storage
from app.modules.file.validation import FileValidationError, validate_upload
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser


class FileService:
    def __init__(self, session: Session, storage: StorageBackend | None = None) -> None:
        self._session = session
        self._repo = FileRepository(session)
        self._identity = IdentityRepository(session)
        self._settings: Settings = get_settings()
        self._storage = storage or build_default_storage(self._settings)

    # ------------------------------------------------------------------ #
    # 守卫
    # ------------------------------------------------------------------ #
    def _require_permission(self, actor_user_id: int, code: str) -> None:
        """事务内重读有效权限的纵深守卫（与其余模块一致）。"""
        actor = self._identity.get_user_by_id_for_update(actor_user_id)
        if actor is None:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor_user_id)):
            raise PermissionDeniedError()

    def _retention_deadline(self, category: str) -> datetime:
        days = self._settings.file_retention_days_by_category().get(category, 30)
        return utcnow() + timedelta(days=days)

    # ------------------------------------------------------------------ #
    # 上传
    # ------------------------------------------------------------------ #
    def upload(
        self,
        actor: CurrentUser,
        *,
        category: str,
        content: bytes,
        filename: str | None,
        declared_content_type: str | None,
        request_id: str | None,
    ) -> FileUploadResponse:
        if actor.pre_binding:
            # 受限会话不得上传业务材料（绑定完成守卫在路由再兜一道纵深）。
            raise PermissionDeniedError("请先完成身份绑定")

        if not fperm.is_uploadable_category(category):
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "不支持的材料类别",
                http_status=422,
                field_errors={"category": category},
            )
        extra = fperm.required_upload_permission(category)
        if extra is not None:
            self._require_permission(actor.id, extra)

        try:
            validated = validate_upload(
                data=content,
                declared_content_type=declared_content_type,
                original_name=filename,
                allowed_extensions=self._settings.allowed_extension_set,
                max_bytes=self._settings.file_max_bytes,
                max_pixels=self._settings.file_max_image_pixels,
            )
        except FileValidationError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                exc.message,
                http_status=422,
                field_errors={"file": exc.message},
            ) from exc

        object_key = self._build_object_key(validated.ext)
        self._storage.save(object_key, content, validated.content_type)

        file = FileObject(
            object_key=object_key,
            category=category,
            original_name=filename,
            content_type=validated.content_type,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
            uploader_user_id=actor.id,
            status=FileStatus.READY.value,
            retention_policy_version=self._settings.file_retention_policy_version,
            expires_at=self._retention_deadline(category),
        )
        self._repo.add(file)
        self._session.flush()  # 取得自增主键供审计 resource_id 与响应回显
        self._audit(
            actor_user_id=actor.id,
            action="file.upload",
            resource_id=str(file.id),
            after={
                "category": category,
                "content_type": validated.content_type,
                "size_bytes": validated.size_bytes,
                "width": validated.width,
                "height": validated.height,
                "status": FileStatus.READY.value,
            },
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(file)
        return self._to_upload_response(file, validated.width, validated.height)

    def _build_object_key(self, ext: str) -> str:
        now = utcnow()
        return f"{now:%Y/%m}/{secrets.token_hex(16)}.{ext}"

    # ------------------------------------------------------------------ #
    # 访问授权 + 短时链接
    # ------------------------------------------------------------------ #
    def can_access(self, actor: CurrentUser, file: FileObject) -> bool:
        # 教工本人材料访问独立于学生绑定：已关联有效档案的受限会话仍按逐文件事实判定，
        # 由 can_staff_access_file 自己核对账号/档案/学院；学生与管理员路径守卫保持不变。
        from app.modules.file.staff_access import can_staff_access_file

        if can_staff_access_file(self._session, actor.id, file):
            return True
        if actor.pre_binding:
            return False
        if self._settings.campus_business_scoped_enabled:
            return self._can_access_scoped(actor, file)
        from app.modules.identity.repository import IdentityRepository

        repo = IdentityRepository(self._session)
        user = repo.get_user_by_id(actor.id)
        if user is None or not user.is_active or actor.pre_binding:
            return False
        permissions = set(repo.list_effective_permissions(actor.id))
        if (file.uploader_user_id == actor.id
            and permissions & {"submission.create", "objection.create", "import.execute", "report.generate"}
            and not self._repo.has_business_link(file.id)):
            return True
        from app.modules.academic.history_policy import self_history_available
        from app.modules.identity.query_scope import personal_lookup

        with personal_lookup(self._session):
            within_history = self_history_available(self._session, actor.id)
            if (
                within_history
                and not actor.pre_binding
                and file.category == FileCategory.SUBMISSION_PHOTO.value
            ):
                if "attendance.read" in permissions and self._repo.is_linked_to_own_attendance(
                    file_id=file.id, actor_user_id=actor.id
                ):
                    return True
                if "submission.read" in permissions and self._repo.is_linked_to_submittable_for(
                    file_id=file.id, actor_user_id=actor.id, may_review=False, may_read_own=True
                ):
                    return True
            if (
                within_history
                and not actor.pre_binding
                and file.category == FileCategory.OBJECTION_PROOF.value
                and "objection.read" in permissions
                and self._repo.is_linked_to_readable_objection_for(
                    file_id=file.id, actor_user_id=actor.id, may_manage=False, may_read_own=True
                )
            ):
                return True
        if file.category == FileCategory.REPORT_FILE.value:
            return "report.read" in permissions and self._repo.is_linked_to_report(file.id)
        if (
            not actor.pre_binding
            and file.category == FileCategory.SUBMISSION_PHOTO.value
            and "attendance.read" in permissions
            and within_history
            and self._repo.is_linked_to_own_attendance(file_id=file.id, actor_user_id=actor.id)
        ):
            return True
        if file.category == FileCategory.OBJECTION_PROOF.value:
            from app.modules.objection.permissions import (
                MANAGE_READ_PERMISSIONS,
                OBJECTION_READ_PERMISSION,
            )

            if self._repo.is_linked_to_readable_objection_for(
                file_id=file.id,
                actor_user_id=actor.id,
                may_manage=bool(permissions & MANAGE_READ_PERMISSIONS),
                may_read_own=OBJECTION_READ_PERMISSION in permissions,
            ):
                return True
            from app.modules.file.staff_access import can_staff_access_file

            return can_staff_access_file(self._session, actor.id, file)
        may_review = "submission.review" in permissions
        may_read_own = "submission.read" in permissions
        if (may_review or may_read_own) and self._repo.is_linked_to_submittable_for(
            file_id=file.id,
            actor_user_id=actor.id,
            may_review=may_review,
            may_read_own=may_read_own,
        ):
            return True
        from app.modules.file.staff_access import can_staff_access_file

        return can_staff_access_file(self._session, actor.id, file)

    def _can_access_scoped(self, actor: CurrentUser, file: FileObject) -> bool:
        from sqlalchemy import select

        from app.modules.identity.management_scope import management_college_ids
        from app.modules.identity.models import UserAccount

        user = self._session.scalar(select(UserAccount).where(
            UserAccount.id == actor.id
        ).execution_options(populate_existing=True))
        if actor.pre_binding or user is None or not user.is_active:
            return False
        if file.uploader_user_id == user.id:
            return True
        permissions = set(self._identity.list_effective_permissions(user.id))
        if file.category == FileCategory.SUBMISSION_PHOTO.value:
            if "attendance.read" in permissions and self._repo.is_linked_to_own_attendance(
                file_id=file.id, actor_user_id=user.id
            ):
                return True
            from app.modules.identity.management_scope import management_task_access
            may_review, predicate = management_task_access(self._session, actor, "submission.review")
            colleges = management_college_ids(self._session, actor, "submission.review")
            return self._repo.is_linked_to_submittable_for(
                file_id=file.id, actor_user_id=user.id,
                may_review=may_review, review_task_condition=predicate,
                review_college_ids=colleges, may_read_own="submission.read" in permissions,
            )
        if file.category == FileCategory.OBJECTION_PROOF.value:
            from app.modules.identity.management_scope import management_task_access
            may_manage, predicate = management_task_access(self._session, actor, "objection.read")
            colleges = management_college_ids(self._session, actor, "objection.read")
            return self._repo.is_linked_to_readable_objection_for(
                file_id=file.id, actor_user_id=user.id,
                may_manage=may_manage, management_task_condition=predicate,
                management_college_ids=colleges, may_read_own="objection.read" in permissions,
            )
        if file.category == FileCategory.REPORT_FILE.value:
            colleges = management_college_ids(self._session, actor, "report.read")
            return self._repo.is_linked_to_scoped_report(file.id, colleges)
        # 导入与临时文件不凭照片审核权限派生访问。
        return False

    def get_access(
        self, actor: CurrentUser, file_id: int, *, delivery: str = "proxy"
    ) -> FileAccessResponse:
        file = self._repo.get(file_id)
        # 不可见或不存在统一 404，避免枚举探测（技术方案 16.2 资源归属）。
        if file is None or not self.can_access(actor, file):
            raise NotFoundError()
        self._assert_accessible(file)

        ttl = self._settings.file_signed_url_ttl_seconds
        # 待处理异议的证明沿用既有延长访问规则，其余文件不能签发超出保留期的链接。
        if file.expires_at is not None and file.expires_at > utcnow():
            ttl = min(ttl, int((file.expires_at - utcnow()).total_seconds()))
            if ttl < 1:
                raise FileExpiredError()
        if (
            delivery == "direct" and self._settings.oss_web_direct_enabled
            and self._settings.file_storage_backend == "object"
            and file.content_type.startswith("image/")
            # SDK 签名会扣除准备耗时再取整；1 秒可能变成非法的 0 秒，沿用代理更稳妥。
            and ttl >= 2
        ):
            signer = getattr(self._storage, "presign_direct_get", None)
            if callable(signer):
                link = signer(file.object_key, ttl)
                return FileAccessResponse(
                    url=link.url, method="GET",
                    expires_in=max(0, int((link.expires_at - datetime.now(UTC)).total_seconds())),
                    expires_at=link.expires_at,
                )
        url = self._storage.presign_get(file.id, file.object_key, ttl)
        return FileAccessResponse(
            url=url,
            method="GET",
            expires_in=ttl,
            expires_at=utcnow() + timedelta(seconds=ttl),
        )

    def _assert_accessible(self, file: FileObject) -> None:
        if file.status == FileStatus.PURGED.value or file.status == FileStatus.PURGE_PENDING.value:
            raise FileExpiredError()
        if file.status in (FileStatus.UPLOADING.value, FileStatus.FAILED.value):
            raise ConflictError(ErrorCode.STATE_CONFLICT, "文件尚未就绪，暂不可访问")
        if self._retention_expired(file):
            raise FileExpiredError()

    def _retention_expired(self, file: FileObject) -> bool:
        if file.expires_at is None or file.expires_at > utcnow():
            return False
        from app.modules.identity.query_scope import personal_lookup

        with personal_lookup(self._session):
            return not (
                file.category == FileCategory.OBJECTION_PROOF.value
                and self._repo.is_linked_to_pending_objection(file.id)
            )

    def download(self, file_id: int, expires: int, sig: str) -> tuple[bytes, str, str | None]:
        """下载路由取内容：不再鉴权，仅校验对象存在、未清理、签名与有效期（技术方案 16.2）。"""
        file = self._repo.get(file_id)
        if file is None:
            raise NotFoundError()
        if file.status in (FileStatus.PURGED.value, FileStatus.PURGE_PENDING.value) or (
            self._retention_expired(file)
        ):
            raise FileExpiredError()
        verifier = getattr(self._storage, "verify_download", None)
        if not callable(verifier) or not verifier(file.object_key, expires, sig):
            raise PermissionDeniedError("签名链接无效或已过期")
        data = self._storage.read(file.object_key)
        return data, file.content_type, file.original_name

    # ------------------------------------------------------------------ #
    # 到期清理（部署定时脚本复用本服务，技术方案 16.1 / 16.3）
    # ------------------------------------------------------------------ #
    def purge_expired_files(
        self, *, batch_size: int = 200, cutoff: datetime | None = None
    ) -> dict[str, int]:
        """按到期日清理底层对象，可重跑、逐文件独立事务提交。

        状态机：READY → 先落库 PURGE_PENDING（持久化清理意图，崩溃可恢复），删底层对象
        成功后置 PURGED 记 purged_at；底层删除失败则保留 PURGE_PENDING 待下次运行，绝不把
        删除失败的文件标记为已清理。底层对象已不存在视作清理完成（幂等续跑）。与请求级
        "单事务单次提交"不同，此维护作业逐文件提交以隔离失败并保证可续跑（技术方案 66）。
        """
        now = cutoff or utcnow()
        candidates = self._repo.list_purge_candidates(cutoff=now, limit=batch_size)
        stats = {"scanned": len(candidates), "marked": 0, "purged": 0, "failed": 0}
        for cand in candidates:
            file_id = int(cand.id)
            row = self._repo.get_for_update(file_id)
            if row is None or row.status not in (
                FileStatus.READY.value,
                FileStatus.PURGE_PENDING.value,
            ):
                self._session.rollback()
                continue
            object_key = row.object_key
            if row.status == FileStatus.READY.value:
                row.status = FileStatus.PURGE_PENDING.value
                self._session.commit()  # 事务1：持久化清理意图
                stats["marked"] += 1
            else:
                self._session.rollback()  # 释放行锁，删除在锁外进行

            try:
                self._storage.delete(object_key)  # 返回 False（对象缺失）亦视作已清理
            except Exception:  # noqa: BLE001 - 底层删除失败，留待下次运行
                stats["failed"] += 1
                continue

            row2 = self._repo.get_for_update(file_id)  # 事务2：置 PURGED + 审计
            if row2 is None or row2.status != FileStatus.PURGE_PENDING.value:
                self._session.rollback()
                continue
            row2.status = FileStatus.PURGED.value
            row2.purged_at = utcnow()
            self._system_audit(
                action="file.purge",
                resource_id=str(file_id),
                before={"status": FileStatus.PURGE_PENDING.value},
                after={"status": FileStatus.PURGED.value, "object_removed": True},
                reason="retention_expired",
            )
            self._session.commit()
            stats["purged"] += 1
        return stats

    # ------------------------------------------------------------------ #
    # 响应装配 / 审计
    # ------------------------------------------------------------------ #
    def _to_upload_response(self, file: FileObject, width: int, height: int) -> FileUploadResponse:
        return FileUploadResponse(
            id=str(file.id),
            category=file.category,
            status=file.status,
            original_name=file.original_name,
            content_type=file.content_type,
            size_bytes=file.size_bytes,
            width=width,
            height=height,
            sha256=file.sha256,
            expires_at=file.expires_at,
        )

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_id: str,
        after: dict[str, object],
        request_id: str | None,
    ) -> None:
        # resource_id 需要真实主键，先 flush 取得自增 id。
        self._session.flush()
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type="file_object",
                resource_id=resource_id,
                before_json=None,
                after_json=dict(after),
                reason=None,
                request_id=request_id,
            )
        )

    def _system_audit(
        self,
        *,
        action: str,
        resource_id: str,
        before: dict[str, object],
        after: dict[str, object],
        reason: str,
    ) -> None:
        """系统触发的审计（无操作者）：如定时清理。actor_user_id 置空，保留变更前后事实。"""
        self._session.flush()
        self._session.add(
            AuditLog(
                actor_user_id=None,
                action=action,
                resource_type="file_object",
                resource_id=resource_id,
                before_json=dict(before),
                after_json=dict(after),
                reason=reason,
                request_id=None,
            )
        )


__all__ = ["FileService"]
