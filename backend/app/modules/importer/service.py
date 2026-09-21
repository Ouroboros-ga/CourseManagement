"""导入服务：预览解析（不写业务表）+ 确认整批原子落库（技术方案 19，PERMISSIONS.md 12.5）。

两步语义：
- `create_preview` 只解析并暂存规范行到 ImportBatch，绝不改动业务数据；返回概要 +
  结构化错误/告警，`can_confirm` 标记是否可确认（无 error 级问题）。
- `confirm` 加批次行锁，校验状态/有效期/父作用域（学期 ACTIVE、教学班存在），**先**
  重新核验所有外部引用（学号 / 学生），任一缺失即在写任何数据前抛错回滚；核验通过后再
  于同一事务内整批写入并**单次提交**（任一行失败全回滚，保证原子）。

权限：执行导入 = `import.execute` 且目标资源 `manage`（roster→student、timetable→
academic、volunteer→volunteer），二者事务内重读有效权限纵深校验。

志愿者资格"先导入后绑定"：确认时若学生已绑定账号则即时自动授予 VOLUNTEER；未绑定
者仅落资格行，待其绑定由身份模块反向补授（见 identity.bind_student）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.parsing.time_slots import parse_weekday, parse_weeks
from app.common.parsing.xlsx_tabular import pick, read_tabular_rows
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
from app.core.permissions import PermissionCode, RoleCode
from app.modules.academic.models import (
    Course,
    CourseSchedule,
    Semester,
    Student,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.academic.repository import AcademicRepository
from app.modules.audit.models import AuditLog
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.importer import permissions as iperm
from app.modules.importer.models import ImportBatch, ImportBatchStatus, ImportTarget
from app.modules.importer.repository import ImporterRepository
from app.modules.importer.schemas import (
    ImportConfirmResponse,
    ImportPreviewResponse,
    ImportTemplateResponse,
)

_TRUE_TOKENS = {"是", "1", "true", "yes", "y", "启用", "有效"}
_FALSE_TOKENS = {"否", "0", "false", "no", "n", "停用", "禁用", "无效"}


def _issue(
    code: str, message: str, *, field: str | None = None, row: int | None = None,
    severity: str = "error",
) -> dict[str, object]:
    return {"code": code, "message": message, "field": field, "row": row, "severity": severity}


def _parse_bool(text: str, default: bool = True) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return default
    if t in _TRUE_TOKENS:
        return True
    if t in _FALSE_TOKENS:
        return False
    return default


class ImporterService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ImporterRepository(session)
        self._academic = AcademicRepository(session)
        self._identity = IdentityRepository(session)

    # ================================================================== #
    # 守卫与审计（与 identity/academic 服务一致）
    # ================================================================== #
    def _require(self, actor_user_id: int, code: str) -> None:
        actor = self._identity.get_user_by_id_for_update(actor_user_id)
        if actor is None:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor_user_id)):
            raise PermissionDeniedError()

    def _require_composite(self, actor_user_id: int, target: str) -> None:
        """组合权限：import.execute + 目标资源 manage。任一缺失即 403。"""
        if target not in iperm.TARGET_MANAGE_PERMISSION:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "未知导入目标", http_status=422,
                field_errors={"target": target},
            )
        self._require(actor_user_id, PermissionCode.IMPORT_EXECUTE.value)
        self._require(actor_user_id, iperm.TARGET_MANAGE_PERMISSION[target])

    def _require_target_manage(self, actor_user_id: int, target: str) -> None:
        """仅要求目标资源 manage（用于下载/查看模板，PERMISSIONS.md 12.5）。"""
        if target not in iperm.TARGET_MANAGE_PERMISSION:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "未知导入目标", http_status=422,
                field_errors={"target": target},
            )
        self._require(actor_user_id, iperm.TARGET_MANAGE_PERMISSION[target])

    def _audit(
        self, *, actor_user_id: int, action: str, resource_id: str,
        before: Mapping[str, object] | None, after: Mapping[str, object] | None,
        reason: str | None, request_id: str | None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type="import_batch",
                resource_id=resource_id,
                before_json=dict(before) if before is not None else None,
                after_json=dict(after) if after is not None else None,
                reason=reason,
                request_id=request_id,
            )
        )
        self._session.flush()

    # ================================================================== #
    # 模板
    # ================================================================== #
    def get_template(self, actor: CurrentUser, target: str) -> ImportTemplateResponse:
        self._require_target_manage(actor.id, target)
        spec = iperm.template_spec(target)
        return ImportTemplateResponse(**spec)

    # ================================================================== #
    # 预览（解析并暂存，不写业务表）
    # ================================================================== #
    def create_preview(
        self,
        actor: CurrentUser,
        *,
        target: str,
        content: bytes,
        semester_id: int | None,
        teaching_class_id: int | None,
        filename: str | None,
        replace: bool,
        request_id: str | None,
    ) -> ImportPreviewResponse:
        self._require_composite(actor.id, target)
        self._validate_scope(target, semester_id=semester_id, teaching_class_id=teaching_class_id)

        try:
            rows = read_tabular_rows(
                content, required_headers=iperm.required_headers(target)
            )
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, f"文件解析失败：{exc}", http_status=422
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 非法/损坏 xlsx 统一归为 422
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "文件不是有效的 .xlsx，无法解析", http_status=422
            ) from exc

        settings = get_settings()
        if len(rows) > settings.import_max_rows:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"行数超过上限 {settings.import_max_rows}",
                http_status=422,
            )

        if target == ImportTarget.ROSTER.value:
            payload, issues, summary = self._parse_roster(rows, teaching_class_id)
        elif target == ImportTarget.VOLUNTEER.value:
            payload, issues, summary = self._parse_volunteer(rows, semester_id)
        else:
            payload, issues, summary = self._parse_timetable(rows, semester_id)

        error_count = sum(1 for i in issues if i["severity"] == "error")
        summary = {**summary, "error_count": error_count}

        batch = ImportBatch(
            target=target,
            status=ImportBatchStatus.PREVIEW.value,
            semester_id=semester_id,
            teaching_class_id=teaching_class_id,
            created_by=actor.id,
            filename=filename,
            payload_json=payload,
            summary_json=summary,
            error_json=issues,
            expires_at=utcnow() + timedelta(minutes=settings.import_preview_ttl_minutes),
        )
        self._repo.add(batch)
        self._audit(
            actor_user_id=actor.id,
            action="import.batch.preview",
            resource_id=str(batch.id),
            before=None,
            after={"target": target, "summary": summary},
            reason=None,
            request_id=request_id,
        )
        self._session.commit()
        return self._to_preview(batch)

    def _validate_scope(
        self, target: str, *, semester_id: int | None, teaching_class_id: int | None
    ) -> None:
        need = iperm.TARGET_SCOPE_FIELDS[target]
        if "semester_id" in need:
            if semester_id is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, "该导入目标必须提供 semester_id",
                    http_status=422, field_errors={"semester_id": "required"},
                )
            if self._academic.get_semester(semester_id) is None:
                raise NotFoundError("学期不存在")
        if "teaching_class_id" in need:
            if teaching_class_id is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, "该导入目标必须提供 teaching_class_id",
                    http_status=422, field_errors={"teaching_class_id": "required"},
                )
            if self._academic.get_teaching_class(teaching_class_id) is None:
                raise NotFoundError("教学班不存在")

    # ---- 解析器：产出 (payload, issues, summary) ----
    def _parse_roster(
        self, rows: list[dict[str, str]], teaching_class_id: int | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        seen: dict[str, int] = {}
        student_nos: list[str] = []
        for idx, raw in enumerate(rows, start=2):
            no = pick(raw, "学号", "student_no", "studentno", "no")
            if not no:
                issues.append(_issue("missing_student_no", "学号为空", field="学号", row=idx))
                continue
            if no in seen:
                issues.append(
                    _issue("duplicate_student", f"学号 {no} 重复", field="学号", row=idx,
                           severity="warning")
                )
                continue
            seen[no] = idx
            if self._academic.get_student_by_no(no) is None:
                issues.append(
                    _issue("unknown_student", f"学号 {no} 不存在于学生名单", field="学号", row=idx)
                )
                continue
            student_nos.append(no)
        payload = {"student_nos": student_nos, "replace": bool(teaching_class_id)}
        summary = {"row_total": len(rows), "student_total": len(student_nos)}
        return payload, issues, summary

    def _parse_volunteer(
        self, rows: list[dict[str, str]], semester_id: int | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        by_no: dict[str, dict] = {}
        for idx, raw in enumerate(rows, start=2):
            no = pick(raw, "学号", "student_no", "studentno", "no")
            if not no:
                issues.append(_issue("missing_student_no", "学号为空", field="学号", row=idx))
                continue
            enabled = _parse_bool(pick(raw, "是否启用", "启用", "enabled", "enable"))
            if no in by_no:
                issues.append(
                    _issue("duplicate_student", f"学号 {no} 重复，取末次", field="学号", row=idx,
                           severity="warning")
                )
            if self._academic.get_student_by_no(no) is None:
                issues.append(
                    _issue("unknown_student", f"学号 {no} 不存在于学生名单", field="学号", row=idx)
                )
                continue
            by_no[no] = {"student_no": no, "enabled": enabled}
        entries = list(by_no.values())
        payload = {"semester_id": semester_id, "rows": entries}
        summary = {
            "row_total": len(rows),
            "student_total": len(entries),
            "enabled_count": sum(1 for e in entries if e["enabled"]),
        }
        return payload, issues, summary

    def _parse_timetable(
        self, rows: list[dict[str, str]], semester_id: int | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        sem = self._academic.get_semester(semester_id) if semester_id else None
        total_weeks = sem.total_weeks if sem is not None else 0
        seen: set[tuple] = set()
        entries: list[dict] = []
        for idx, raw in enumerate(rows, start=2):
            class_code = pick(raw, "教学班码", "教学班", "class_code")
            course_code = pick(raw, "课程代码", "课程编码", "course_code")
            course_name = pick(raw, "课程名称", "课程", "course_name")
            weekday_raw = pick(raw, "星期", "weekday", "周")
            start_raw = pick(raw, "开始大节", "start_period", "起节")
            end_raw = pick(raw, "结束大节", "end_period", "止节")
            weeks_raw = pick(raw, "周次", "weeks", "上课周")
            classroom = pick(raw, "上课地点", "地点", "classroom")
            row_issue = self._validate_timetable_row(
                idx, class_code, course_code, weekday_raw, start_raw, end_raw, weeks_raw,
                total_weeks, issues,
            )
            if row_issue is None:
                continue
            weekday, start, end, weeks = row_issue
            key = (class_code, course_code, weekday, start, end, tuple(weeks), classroom)
            if key in seen:
                issues.append(
                    _issue("duplicate_entry", "重复课表行，已合并", field=None, row=idx,
                           severity="warning")
                )
                continue
            seen.add(key)
            entries.append(
                {
                    "class_code": class_code,
                    "course_code": course_code,
                    "course_name": course_name or course_code,
                    "weekday": weekday,
                    "start_period": start,
                    "end_period": end,
                    "weeks": list(weeks),
                    "classroom": classroom,
                }
            )
        payload = {"semester_id": semester_id, "rows": entries}
        summary = {
            "row_total": len(rows),
            "schedule_count": len(entries),
            "teaching_class_count": len({e["class_code"] for e in entries}),
            "course_count": len({e["course_code"] for e in entries}),
        }
        return payload, issues, summary

    def _validate_timetable_row(
        self, idx: int, class_code: str, course_code: str, weekday_raw: str,
        start_raw: str, end_raw: str, weeks_raw: str, total_weeks: int,
        issues: list[dict],
    ) -> tuple[int, int, int, Sequence[int]] | None:
        if not class_code:
            issues.append(_issue("missing_class_code", "教学班码为空", field="教学班码", row=idx))
            return None
        if not course_code:
            issues.append(_issue("missing_course_code", "课程代码为空", field="课程代码", row=idx))
            return None
        try:
            weekday = parse_weekday(weekday_raw)
            start = int(start_raw)
            end = int(end_raw)
            weeks = parse_weeks(weeks_raw, total_weeks)
        except (ValueError, TypeError) as exc:
            issues.append(_issue("bad_time_field", f"时间字段解析失败：{exc}", row=idx))
            return None
        if not 1 <= start <= 20 or not 1 <= end <= 20:
            issues.append(_issue("period_out_of_range", "大节须为 1..20", row=idx))
            return None
        if end < start:
            issues.append(_issue("period_inverted", "结束大节不得早于开始大节", row=idx))
            return None
        return weekday, start, end, weeks

    # ================================================================== #
    # 读取批次
    # ================================================================== #
    def get_batch(self, actor: CurrentUser, batch_id: int) -> ImportPreviewResponse:
        batch = self._repo.get(batch_id)
        if batch is None:
            raise NotFoundError("导入批次不存在")
        self._require_composite(actor.id, batch.target)
        return self._to_preview(batch)

    def get_errors(self, actor: CurrentUser, batch_id: int) -> dict[str, list[dict]]:
        batch = self._repo.get(batch_id)
        if batch is None:
            raise NotFoundError("导入批次不存在")
        self._require_composite(actor.id, batch.target)
        issues = batch.error_json or []
        return {
            "errors": [i for i in issues if i.get("severity") == "error"],
            "warnings": [i for i in issues if i.get("severity") != "error"],
        }

    def _to_preview(self, batch: ImportBatch) -> ImportPreviewResponse:
        issues = batch.error_json or []
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") != "error"]
        can_confirm = (
            batch.status == ImportBatchStatus.PREVIEW.value
            and not errors
            and batch.expires_at > utcnow()
        )
        return ImportPreviewResponse(
            id=batch.id,
            target=batch.target,
            status=batch.status,
            semester_id=batch.semester_id,
            teaching_class_id=batch.teaching_class_id,
            summary=batch.summary_json or {},
            errors=errors,
            warnings=warnings,
            expires_at=batch.expires_at,
            can_confirm=can_confirm,
        )

    # ================================================================== #
    # 确认（整批原子落库）
    # ================================================================== #
    def confirm(
        self, actor: CurrentUser, batch_id: int, request_id: str | None
    ) -> ImportConfirmResponse:
        batch = self._repo.get_for_update(batch_id)
        if batch is None:
            raise NotFoundError("导入批次不存在")
        self._require_composite(actor.id, batch.target)

        if batch.status == ImportBatchStatus.CONFIRMED.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该批次已确认，不可重复导入")
        if batch.status != ImportBatchStatus.PREVIEW.value:
            raise ConflictError(
                ErrorCode.STATE_CONFLICT, f"批次状态 {batch.status} 不可确认"
            )
        if batch.expires_at <= utcnow():
            batch.status = ImportBatchStatus.EXPIRED.value
            self._session.commit()
            raise ConflictError(ErrorCode.STATE_CONFLICT, "预览已过期，请重新上传")

        issues = batch.error_json or []
        if any(i.get("severity") == "error" for i in issues):
            raise AppError(ErrorCode.VALIDATION_ERROR, "存在错误项，无法确认导入", http_status=422)

        payload = batch.payload_json or {}
        if batch.target == ImportTarget.ROSTER.value:
            created = self._apply_roster(actor, batch, payload, request_id)
        elif batch.target == ImportTarget.VOLUNTEER.value:
            created = self._apply_volunteer(actor, batch, payload, request_id)
        else:
            created = self._apply_timetable(actor, batch, payload, request_id)

        batch.status = ImportBatchStatus.CONFIRMED.value
        batch.summary_json = {**(batch.summary_json or {}), **created}
        self._audit(
            actor_user_id=actor.id,
            action="import.batch.confirm",
            resource_id=str(batch.id),
            before={"status": ImportBatchStatus.PREVIEW.value},
            after={"status": ImportBatchStatus.CONFIRMED.value, **created},
            reason=None,
            request_id=request_id,
        )
        # 单一提交点：以上所有业务写入 + 状态变更 + 审计同事务原子生效。
        self._session.commit()
        return ImportConfirmResponse(
            id=batch.id,
            target=batch.target,
            status=batch.status,
            summary=batch.summary_json or {},
        )

    def _require_active_semester_for_confirm(self, semester_id: int | None) -> Semester:
        if semester_id is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "批次缺少学期", http_status=422)
        sem = self._academic.get_semester_for_update(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if sem.status != "ACTIVE":
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学期已归档，禁止写入")
        return sem

    def _apply_roster(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        tc_id = batch.teaching_class_id
        tc = self._academic.get_teaching_class_for_update(tc_id) if tc_id else None
        if tc is None:
            raise NotFoundError("教学班不存在")
        self._require_active_semester_for_confirm(tc.semester_id)
        nos: list[str] = list(payload.get("student_nos") or [])
        # 先全部重解析并核验存在（任一缺失写前即抛，保证原子无副作用）。
        ids: list[int] = []
        missing: list[str] = []
        for no in nos:
            stu = self._academic.get_student_by_no(no)
            if stu is None:
                missing.append(no)
            else:
                ids.append(stu.id)
        if missing:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, f"以下学号已不存在：{missing}", http_status=422
            )
        before_count = len(self._academic.get_roster_students(tc.id))
        self._academic.set_roster(tc.id, ids)
        return {
            "roster_before": before_count,
            "roster_after": len(set(ids)),
            "resource_type": "teaching_class",
            "resource_id": str(tc.id),
        }

    def _apply_volunteer(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        sem = self._require_active_semester_for_confirm(batch.semester_id)
        entries: list[dict] = list(payload.get("rows") or [])
        resolved: list[tuple[Student, bool]] = []
        missing: list[str] = []
        for e in entries:
            stu = self._academic.get_student_by_no(e["student_no"])
            if stu is None:
                missing.append(e["student_no"])
            else:
                resolved.append((stu, bool(e["enabled"])))
        if missing:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, f"以下学号已不存在：{missing}", http_status=422
            )
        created_rows = 0
        updated_rows = 0
        granted_roles = 0
        for stu, enabled in resolved:
            vq = self._academic.get_volunteer_qualification_by_sem_student(sem.id, stu.id)
            if vq is None:
                vq = VolunteerQualification(
                    semester_id=sem.id, student_id=stu.id, enabled=enabled, created_by=actor.id
                )
                self._academic.add(vq)
                self._academic.flush()
                created_rows += 1
            else:
                if vq.enabled != enabled:
                    updated_rows += 1
                vq.enabled = enabled
                self._academic.flush()
            if enabled:
                granted_roles += int(self._grant_volunteer_if_bound(stu.id))
        return {
            "qualification_created": created_rows,
            "qualification_updated": updated_rows,
            "volunteer_role_granted": granted_roles,
            "resource_type": "volunteer_qualification",
            "resource_id": str(sem.id),
        }

    def _grant_volunteer_if_bound(self, student_id: int) -> bool:
        acct = self._session.execute(
            select(UserAccount).where(UserAccount.student_id == student_id)
        ).scalar_one_or_none()
        if acct is None:
            return False
        if RoleCode.VOLUNTEER.value in self._identity.list_role_codes(acct.id):
            return False
        role = self._identity.get_or_create_role(
            RoleCode.VOLUNTEER.value, RoleCode.VOLUNTEER.value
        )
        self._identity.grant_role(acct.id, role.id)
        acct.lock_version += 1
        return True

    def _apply_timetable(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        sem = self._require_active_semester_for_confirm(batch.semester_id)
        entries: list[dict] = list(payload.get("rows") or [])
        # 写前整体核验周次/大节仍落在学期范围（学期总周数可能被改）。
        for e in entries:
            bad = [w for w in e["weeks"] if w < 1 or w > sem.total_weeks]
            if bad:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"周次超出学期范围(1..{sem.total_weeks})：{bad}",
                    http_status=422,
                )
        courses_created = 0
        tcs_created = 0
        schedules_created = 0
        for e in entries:
            course = self._academic.get_course_by_code(e["course_code"])
            if course is None:
                course = Course(
                    course_code=e["course_code"],
                    course_name=e["course_name"],
                    status="ACTIVE",
                )
                self._academic.add(course)
                self._academic.flush()
                courses_created += 1
            tc = self._academic.get_teaching_class_by_key(
                sem.id, course.id, e["class_code"]
            )
            if tc is None:
                tc = TeachingClass(
                    semester_id=sem.id,
                    course_id=course.id,
                    class_code=e["class_code"],
                    class_name=e["course_name"],
                    status="ACTIVE",
                )
                self._academic.add(tc)
                self._academic.flush()
                tcs_created += 1
            schedule = CourseSchedule(
                semester_id=sem.id,
                teaching_class_id=tc.id,
                weekday=e["weekday"],
                start_period=e["start_period"],
                end_period=e["end_period"],
                classroom=e["classroom"] or None,
                status="ACTIVE",
            )
            self._academic.add(schedule)
            self._academic.flush()
            self._academic.set_schedule_weeks(schedule, e["weeks"])
            schedules_created += 1
        return {
            "course_created": courses_created,
            "teaching_class_created": tcs_created,
            "schedule_created": schedules_created,
            "resource_type": "semester",
            "resource_id": str(sem.id),
        }
