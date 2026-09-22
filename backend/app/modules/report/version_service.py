"""版本化周报服务（W7c，技术方案 18）。

三阶段有界同步生成（不建 worker/队列）：

① 短写事务·锁分配：get-or-create 并锁 report 行（SELECT ... FOR UPDATE 串行化同
   (学期,周,范围) 的版本号分配），若上一版本仍 GENERATING 且未超接管预算 → 拒绝并发重复生成；
   若已超预算 → 以条件 UPDATE 原子换 attempt_token 接管复用同一版本号；否则分配
   version_no = latest+1 登记一条 GENERATING 行并落库提交（中断可观测、可被后续接管）。
② 一致性只读快照：在提交①之后的新事务里，按 REPEATABLE READ 同一快照读源修订号 +
   命中任务 + 名单 + 当前考勤 + 班级分布 + 个人明细，**先范围过滤再聚合**、口径与 W7a 统计
   共用 aggregation 纯函数。规模超限在此步写入产物前拒绝（把 GENERATING 版本置 FAILED）。
③ 事务外生成产物：渲染明细 JSON 快照与 Excel（openpyxl 每次新建工作簿、写死数值），
   经存储后端落私有目录（与业务事务解耦，崩溃留孤儿对象由清理侧忽略）。
④ 独立短事务·发布：以 (id, status=GENERATING, attempt_token=?) 条件更新锁定发布权——
   只有令牌匹配者能发布，迟到者发现状态/令牌不符即放弃并清理孤儿对象，杜绝重复版本；
   同事务登记两个 REPORT_FILE 文件行、回填版本行 source_revision/rule/template/文件id/
   generated_at 并置 PUBLISHED、更新 report.latest_updated_at。

落后判定（技术方案 18）：latest.version.source_revision < 当前 report_source_revision.revision
→ behind_source=true，前端提示"源数据已更新，请生成新版本"；rule/template 版本比较提示
公式/模板已更新。权限：生成需 report.generate、查看/下载需 report.read，二者独立
（statistics.read 不隐式授予，周报含个人明细）。

事务纪律：Repository flush-only，本服务在各阶段边界单 commit；append-only 审计同事务。
"""

from __future__ import annotations

import contextlib
import hashlib
import secrets
from datetime import timedelta
from typing import Any

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
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.storage import StorageBackend, build_default_storage
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.report import aggregation as agg
from app.modules.report import artifacts
from app.modules.report import permissions as perms
from app.modules.report.models import ReportVersion, ReportVersionStatus
from app.modules.report.repository import ReportRepository, ReportVersionRepository
from app.modules.report.schemas import (
    GenerateReportResponse,
    ReportVersionsResponse,
    ReportVersionSummary,
)


class ReportService:
    def __init__(self, session: Session, storage: StorageBackend | None = None) -> None:
        self._session = session
        self._stat_repo = ReportRepository(session)
        self._repo = ReportVersionRepository(session)
        self._identity = IdentityRepository(session)
        self._settings: Settings = get_settings()
        self._storage = storage or build_default_storage(self._settings)

    # ------------------------------------------------------------------ #
    # 守卫：功能权限纵深复核（事务内重读有效权限）+ 管理范围准入
    # ------------------------------------------------------------------ #
    def _guard(self, actor: CurrentUser, code: str) -> None:
        actor_row = self._identity.get_user_by_id_for_update(actor.id)
        if actor_row is None:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor.id)):
            raise PermissionDeniedError()
        if not perms.is_manage_scope(perms.resolve_read_scope(actor.roles)):
            raise PermissionDeniedError("周报为聚合读数，仅管理范围可见")

    # ================================================================== #
    # 生成新版本
    # ================================================================== #
    def generate_version(
        self,
        actor: CurrentUser,
        *,
        semester_id: int,
        week_no: int,
        scope: str = "COLLEGE",
        reason: str | None,
        request_id: str | None,
    ) -> GenerateReportResponse:
        self._guard(actor, perms.REPORT_GENERATE_PERMISSION)

        # ---- 阶段①：锁分配版本号 + 登记 GENERATING（独立提交，令并发者可见/可接管）----
        token = secrets.token_hex(16)
        report = self._repo.get_or_create_report_for_update(
            semester_id=semester_id, week_no=week_no, scope=scope
        )
        latest = self._repo.latest_version(report.id)
        takeover = False
        if latest is not None and latest.status == ReportVersionStatus.GENERATING.value:
            stale_before = utcnow() - timedelta(
                seconds=self._settings.report_generate_takeover_stale_seconds
            )
            if latest.created_at < stale_before:
                # 中断超预算 → 条件换令牌接管，复用同一版本号。
                rc = self._repo.take_over_stale_generating(
                    version_id=latest.id,
                    old_token=latest.attempt_token or "",
                    new_token=token,
                    stale_before=stale_before,
                )
                if rc == 0:
                    self._session.commit()
                    raise ConflictError(
                        ErrorCode.STATE_CONFLICT, "该版本已被他人接管生成，请稍后重试"
                    )
                version = latest
                version.generated_by = actor.id
                version.reason = reason
                takeover = True
            else:
                self._session.commit()  # 释放行锁
                raise ConflictError(ErrorCode.STATE_CONFLICT, "上一版本仍在生成中，请稍后重试")
        else:
            version_no = report.latest_version_no + 1
            version = ReportVersion(
                report_id=report.id,
                version_no=version_no,
                status=ReportVersionStatus.GENERATING.value,
                attempt_token=token,
                generated_by=actor.id,
                reason=reason,
            )
            self._repo.add_version(version)
            report.latest_version_no = version_no
        # 固化本次生成所依据的统计公式版本与 Excel 模板版本（来自 Settings，可配不硬编码），
        # 供发布后按"当前值 vs 版本内值"提示口径/模板已更新。接管分支同样刷新为当前口径。
        version.rule_version = self._current_rule_version()
        version.template_version = self._current_template_version()
        self._audit(
            actor_user_id=actor.id,
            action="report.version.start",
            resource_id=str(version.id),
            after={
                "semester_id": semester_id,
                "week_no": week_no,
                "scope": scope,
                "version_no": version.version_no,
                "takeover": takeover,
            },
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()  # 阶段①落库：GENERATING 行持久化，崩溃可被接管

        # ---- 阶段②：一致性只读快照，先范围过滤再聚合；规模超限写产物前拒绝 ----
        try:
            payload, source_revision = self._build_payload(
                semester_id=semester_id, week_no=week_no, version=version
            )
        except AppError:
            self._mark_failed(version_id=version.id, token=token, reason="超出生成规模上限")
            raise
        self._session.commit()  # 结束只读快照事务，释放一致性读

        # ---- 阶段③：事务外渲染产物并落存储（不占业务事务）----
        json_bytes = artifacts.build_snapshot_json(payload)
        excel_bytes = artifacts.build_excel(payload)
        json_key = self._build_object_key("json")
        excel_key = self._build_object_key("xlsx")
        self._storage.save(json_key, json_bytes, artifacts.JSON_CONTENT_TYPE)
        self._storage.save(excel_key, excel_bytes, artifacts.XLSX_CONTENT_TYPE)

        # ---- 阶段④：条件更新锁定发布权（迟到者令牌不符即放弃）----
        published = self._publish(
            actor=actor,
            version_id=version.id,
            token=token,
            source_revision=source_revision,
            json_artifact=(json_key, json_bytes),
            excel_artifact=(excel_key, excel_bytes),
            reason=reason,
            request_id=request_id,
        )
        if published is None:
            # 发布权已被他人（接管者）取得：清理本次孤儿对象，绝不重复发布。
            self._safe_delete(json_key)
            self._safe_delete(excel_key)
            raise ConflictError(ErrorCode.STATE_CONFLICT, "生成已被接管，本次结果放弃发布")

        current_rev = self._repo.current_source_revision(semester_id, week_no)
        summary = self._version_summary(
            published, current_rev, self._current_rule_version(), self._current_template_version()
        )
        return GenerateReportResponse(
            report_id=published.report_id,
            semester_id=semester_id,
            week_no=week_no,
            scope=scope,
            version=summary,
            current_source_revision=current_rev,
            message="周报新版本已发布"
            if not summary.behind_source
            else "已发布，但源数据在生成期间又有更新",
        )

    def _build_payload(
        self, *, semester_id: int, week_no: int, version: ReportVersion
    ) -> tuple[dict[str, Any], int]:
        """在阶段②只读快照内取数并聚合（口径与统计共用 agg）。返回 (payload, source_revision)。"""
        ids = self._stat_repo.eligible_task_ids(
            semester_id=semester_id, week_no=week_no, date_from=None, date_to=None
        )
        # 有界生成：命中任务规模超上限时，在写产物前拒绝（异常上抛由调用方置 FAILED）。
        if len(ids) > self._settings.report_generate_max_tasks:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"命中任务数 {len(ids)} 超单次生成上限 "
                f"{self._settings.report_generate_max_tasks}，请缩小范围",
                http_status=422,
                field_errors={"week_no": "生成规模超限"},
            )
        expected = self._stat_repo.task_expected_counts(ids)
        att_by_task = self._stat_repo.attendance_type_counts(ids)
        roster_by_tc = self._stat_repo.roster_counts_by_task_class(ids)
        att_by_tc = self._stat_repo.attendance_counts_by_task_class(ids)
        meta = self._stat_repo.task_meta(ids)
        details = self._stat_repo.abnormal_details(ids)
        source_revision = self._repo.current_source_revision(semester_id, week_no)

        exp_total = sum(cur for cur, _snap in expected.values())
        type_totals = agg.sum_type_totals(att_by_task)
        abnormal_total = type_totals["LEAVE"] + type_totals["LATE"] + type_totals["ABSENT"]
        overall = agg.build_overall(exp_total, type_totals, abnormal_total)
        classes = agg.build_classes(expected, roster_by_tc, att_by_tc)
        tasks = agg.build_tasks(ids, expected, att_by_task, meta)

        payload: dict[str, Any] = {
            "meta": {
                "semester_id": semester_id,
                "week_no": week_no,
                "scope": "COLLEGE",
                "eligible_task_count": len(ids),
                "source_revision": source_revision,
                "rule_version": version.rule_version,
                "template_version": version.template_version,
            },
            "overall": overall.model_dump(),
            "classes": [c.model_dump() for c in classes],
            "tasks": [t.model_dump() for t in tasks],
            "details": details,
        }
        return payload, source_revision

    def _publish(
        self,
        *,
        actor: CurrentUser,
        version_id: int,
        token: str,
        source_revision: int,
        json_artifact: tuple[str, bytes],
        excel_artifact: tuple[str, bytes],
        reason: str | None,
        request_id: str | None,
    ) -> ReportVersion | None:
        """阶段④：锁版本行、校验令牌仍匹配且为 GENERATING，登记文件行并置 PUBLISHED。

        返回发布后的版本行；若令牌/状态不符（已被接管发布）返回 None（调用方放弃 + 清孤儿）。
        """
        version = self._repo.get_version_for_update(version_id)
        if (
            version is None
            or version.status != ReportVersionStatus.GENERATING.value
            or version.attempt_token != token
        ):
            self._session.rollback()
            return None
        snap_file = self._create_file_row(json_artifact, "report_snapshot.json")
        excel_file = self._create_file_row(excel_artifact, "report_weekly.xlsx")
        self._session.flush()  # 取回文件行主键供版本行外键回填
        version.snapshot_file_id = snap_file.id
        version.excel_file_id = excel_file.id
        version.source_revision = source_revision
        version.status = ReportVersionStatus.PUBLISHED.value
        version.generated_at = utcnow()
        report = self._repo.get_report(version.report_id)
        if report is not None:
            report.latest_updated_at = version.generated_at
        self._audit(
            actor_user_id=actor.id,
            action="report.version.publish",
            resource_id=str(version.id),
            before={"status": ReportVersionStatus.GENERATING.value},
            after={
                "status": ReportVersionStatus.PUBLISHED.value,
                "version_no": version.version_no,
                "source_revision": source_revision,
                "snapshot_file_id": str(snap_file.id),
                "excel_file_id": str(excel_file.id),
            },
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(version)
        return version

    def _mark_failed(self, *, version_id: int, token: str, reason: str) -> None:
        """规模超限时把当前 GENERATING 版本置 FAILED（令牌匹配才改），保留审计与版本号占位。"""
        version = self._repo.get_version_for_update(version_id)
        if (
            version is not None
            and version.status == ReportVersionStatus.GENERATING.value
            and version.attempt_token == token
        ):
            version.status = ReportVersionStatus.FAILED.value
            version.reason = reason
        self._session.commit()

    # ================================================================== #
    # 版本列表 + 落后判定
    # ================================================================== #
    def list_versions(self, actor: CurrentUser, report_id: int) -> ReportVersionsResponse:
        self._guard(actor, perms.REPORT_READ_PERMISSION)
        report = self._repo.get_report(report_id)
        if report is None:
            raise NotFoundError()
        versions = self._repo.list_versions(report_id)
        current_rev = self._repo.current_source_revision(report.semester_id, report.week_no)
        cur_rule = self._current_rule_version()
        cur_tmpl = self._current_template_version()
        items = [self._version_summary(v, current_rev, cur_rule, cur_tmpl) for v in versions]
        latest = next(
            (v for v in versions if v.status == ReportVersionStatus.PUBLISHED.value), None
        )
        latest_behind = bool(latest is not None and latest.source_revision < current_rev)
        return ReportVersionsResponse(
            report_id=report.id,
            semester_id=report.semester_id,
            week_no=report.week_no,
            scope=report.scope,
            current_source_revision=current_rev,
            current_rule_version=cur_rule,
            current_template_version=cur_tmpl,
            latest_version_no=report.latest_version_no,
            latest_updated_at=(
                report.latest_updated_at.isoformat() if report.latest_updated_at else None
            ),
            latest_behind_source=latest_behind,
            items=items,
        )

    def _version_summary(
        self, v: ReportVersion, current_rev: int, cur_rule: int, cur_tmpl: int
    ) -> ReportVersionSummary:
        published = v.status == ReportVersionStatus.PUBLISHED.value
        return ReportVersionSummary(
            id=v.id,
            version_no=v.version_no,
            status=v.status,
            source_revision=v.source_revision,
            rule_version=v.rule_version,
            template_version=v.template_version,
            generated_at=v.generated_at.isoformat() if v.generated_at else None,
            created_at=v.created_at.isoformat(),
            generated_by=v.generated_by,
            reason=v.reason,
            snapshot_available=published and v.snapshot_file_id is not None,
            excel_available=published and v.excel_file_id is not None,
            behind_source=v.source_revision < current_rev,
            rule_outdated=v.rule_version < cur_rule,
            template_outdated=v.template_version < cur_tmpl,
        )

    # ================================================================== #
    # 下载（含个人明细，鉴权 report.read）
    # ================================================================== #
    def download(self, actor: CurrentUser, version_id: int, *, kind: str) -> tuple[bytes, str, str]:
        self._guard(actor, perms.REPORT_READ_PERMISSION)
        version = self._repo.get_version(version_id)
        if version is None:
            raise NotFoundError()
        if version.status != ReportVersionStatus.PUBLISHED.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "版本未发布，不可下载")
        file_id = version.excel_file_id if kind == "EXCEL" else version.snapshot_file_id
        if file_id is None:
            raise NotFoundError()
        file = self._session.get(FileObject, file_id)
        if file is None:
            raise NotFoundError()
        if file.status in (FileStatus.PURGED.value, FileStatus.PURGE_PENDING.value):
            raise FileExpiredError()
        if file.expires_at is not None and file.expires_at <= utcnow():
            raise FileExpiredError()
        data = self._storage.read(file.object_key)
        filename = "report_weekly.xlsx" if kind == "EXCEL" else "report_snapshot.json"
        return data, file.content_type, filename

    # ------------------------------------------------------------------ #
    # 内部：文件行 / 对象键 / 版本口径 / 审计
    # ------------------------------------------------------------------ #
    def _current_rule_version(self) -> int:
        return self._settings.report_rule_version

    def _current_template_version(self) -> int:
        return self._settings.report_template_version

    def _build_object_key(self, ext: str) -> str:
        now = utcnow()
        return f"{now:%Y/%m}/report/{secrets.token_hex(16)}.{ext}"

    def _create_file_row(self, artifact: tuple[str, bytes], original_name: str) -> FileObject:
        object_key, content = artifact
        content_type = (
            artifacts.XLSX_CONTENT_TYPE
            if original_name.endswith(".xlsx")
            else artifacts.JSON_CONTENT_TYPE
        )
        file = FileObject(
            object_key=object_key,
            category=FileCategory.REPORT_FILE.value,
            original_name=original_name,
            content_type=content_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            uploader_user_id=None,  # 服务端生成件，无上传者（SET NULL 语义天然适配）
            status=FileStatus.READY.value,
            retention_policy_version=self._settings.file_retention_policy_version,
            expires_at=self._retention_deadline(),
        )
        self._session.add(file)
        return file

    def _retention_deadline(self):  # -> datetime
        days = self._settings.file_retention_days_by_category().get(
            FileCategory.REPORT_FILE.value, 365
        )
        return utcnow() + timedelta(days=days)

    def _safe_delete(self, object_key: str) -> None:
        # 孤儿对象删除失败仅忽略，清理侧兜底。
        with contextlib.suppress(Exception):
            self._storage.delete(object_key)

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_id: str,
        after: dict[str, Any],
        reason: str | None,
        request_id: str | None,
        before: dict[str, Any] | None = None,
    ) -> None:
        self._session.flush()
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type="report_version",
                resource_id=resource_id,
                before_json=before,
                after_json=after,
                reason=reason,
                request_id=request_id,
            )
        )


__all__ = ["ReportService"]
