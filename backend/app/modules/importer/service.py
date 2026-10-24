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

import hashlib
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.common.parsing.grid import (
    SCHOOL_SLOT_MAPPING,
    load_grid,
    normalize_class_name,
)
from app.common.parsing.time_slots import parse_period, parse_weekday, parse_weeks
from app.common.parsing.xlsx_tabular import _clean, pick, read_any_matrix, read_tabular_rows
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
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClass,
    TeachingClassStudent,
    VolunteerQualification,
)
from app.modules.academic.repository import AcademicRepository
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.importer import permissions as iperm
from app.modules.importer import staff_adapter
from app.modules.importer.models import ImportBatch, ImportBatchStatus, ImportTarget
from app.modules.importer.repository import ImporterRepository
from app.modules.importer.schemas import (
    ImportBatchListItem,
    ImportConfirmResponse,
    ImportPreviewResponse,
    ImportTemplateResponse,
)

_TRUE_TOKENS = {"是", "1", "true", "yes", "y", "启用", "有效"}
_FALSE_TOKENS = {"否", "0", "false", "no", "n", "停用", "禁用", "无效"}


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
    row: int | None = None,
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
        from app.modules.identity.query_scope import recheck_query_scope

        recheck_query_scope(self._session, actor_user_id)
        if code not in set(self._identity.list_effective_permissions(actor_user_id)):
            raise PermissionDeniedError()

    def _require_composite(self, actor_user_id: int, target: str) -> None:
        """组合权限：import.execute + 目标资源 manage。任一缺失即 403。"""
        self._require(actor_user_id, PermissionCode.IMPORT_EXECUTE.value)
        self._require_target_manage(actor_user_id, target)

    def _manage_action_for(self, target: str) -> str:
        """目标所需的资源动作：教职工资料用院级 staff.manage，不借用旧目标权限。"""
        if staff_adapter.is_staff_target(target):
            return iperm.STAFF_IMPORT_ACTION
        db_target = target
        if db_target not in iperm.TARGET_MANAGE_PERMISSION:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "未知导入目标",
                http_status=422,
                field_errors={"target": target},
            )
        return iperm.TARGET_MANAGE_PERMISSION[db_target]

    def _require_target_manage(self, actor_user_id: int, target: str) -> None:
        """仅要求目标资源 manage（用于下载/查看模板，PERMISSIONS.md 12.5）。"""
        self._require(actor_user_id, self._manage_action_for(target))

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_id: str,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        reason: str | None,
        request_id: str | None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type="import_batch",
                resource_id=resource_id,
                before_json=dict(before) if before is not None else None,
                after_json=scoped_snapshot(
                    dict(after) if after is not None else None, getattr(self, "cid", None)
                ),
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
        if staff_adapter.is_staff_target(target):
            return staff_adapter.get_template(target)
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
        course_type_id: int | None = None,
        filename: str | None,
        replace: bool,
        request_id: str | None,
        commit: bool = True,
    ) -> ImportPreviewResponse:
        # 旧页面的责任表入口与行政班名单共用真实解析/落库目标，不能落入课表解析。
        if target == "class_duty":
            target = ImportTarget.ADMIN_ROSTER.value
        self._require_composite(actor.id, target)
        self._validate_scope(target, semester_id=semester_id, teaching_class_id=teaching_class_id)
        if course_type_id is not None:
            cid = getattr(self, "cid", None)
            if cid is None and hasattr(actor, "college_id"):
                cid = actor.college_id
            self._resolve_course_type(cid, course_type_id)

        settings = get_settings()
        if staff_adapter.is_staff_target(target):
            staff_norm = staff_adapter.normalize_staff_target(target)
            cid = getattr(self, "cid", None)
            if cid is None and hasattr(actor, "college_id"):
                cid = actor.college_id
            if cid is None:
                raise AppError(ErrorCode.VALIDATION_ERROR, "请从已授权学院工作区执行导入", 422)
            if staff_norm == "faculty_staff":
                payload, issues, summary = staff_adapter.parse_faculty_staff(
                    self._session, content, cid, filename
                )
            elif staff_norm == "class_responsibility":
                payload, issues, summary = staff_adapter.parse_class_responsibility(
                    self._session, content, cid, filename
                )
            else:
                assert semester_id is not None
                payload, issues, summary = staff_adapter.parse_teaching_assignment(
                    self._session, content, semester_id, cid, filename
                )
        elif target == ImportTarget.GRID_TIMETABLE.value:
            payload, issues, summary = self._parse_grid_timetable(content, semester_id, filename)
        elif target == ImportTarget.ADMIN_ROSTER.value:
            payload, issues, summary = self._parse_admin_roster(content, filename)
        else:
            try:
                rows = read_tabular_rows(
                    content,
                    required_headers=iperm.required_headers(target),
                    include_source=True,
                    max_rows=settings.import_max_rows,
                )
            except ValueError as exc:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, f"文件解析失败：{exc}", http_status=422
                ) from exc
            except Exception as exc:  # noqa: BLE001 - 非法/损坏 xlsx 统一归为 422
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "文件不是有效的 Excel 表格，无法解析",
                    http_status=422,
                ) from exc

            if len(rows) > settings.import_max_rows:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"行数超过上限 {settings.import_max_rows}",
                    http_status=422,
                )

            if target == ImportTarget.ROSTER.value:
                payload, issues, summary = self._parse_roster(rows, teaching_class_id, replace)
            elif target == ImportTarget.VOLUNTEER.value:
                payload, issues, summary = self._parse_volunteer(rows, semester_id)
            elif target == ImportTarget.ELECTIVE_COURSE.value:
                payload, issues, summary = self._parse_elective_course(rows, semester_id)
                payload["preserve_existing"] = True
            else:
                payload, issues, summary = self._parse_timetable(rows, semester_id)

        if target == ImportTarget.ADMIN_ROSTER.value:
            payload["student_baseline"] = {}
            existing_students = {
                student.student_no: student for student in self._academic.get_students_by_nos(
                    [item["student_no"] for item in payload.get("students", [])]
                )
            }
            for item in payload.get("students", []):
                student = existing_students.get(item["student_no"])
                payload["student_baseline"][item["student_no"]] = (
                    {"id": str(student.id), "version": student.lock_version} if student else None
                )
        error_count = sum(1 for i in issues if i["severity"] == "error")
        if target in {"timetable", "grid_timetable", "admin_roster"} and getattr(self, "cid", None):
            from app.modules.importer.person_links import plan_links
            from app.modules.importer.person_links import summary as link_summary

            links = plan_links(self, target, payload, semester_id)
            payload["person_links"] = links
            summary.update(link_summary(links))
            issues.extend(
                _issue(
                    "PERSON_LINK_PENDING",
                    f"{row.get('class_name') or row.get('class_code')} · "
                    f"{row.get('name') or row.get('staff_no') or '未填教师'}：{row['message']}",
                    severity="warning",
                )
                for row in links["pending"]
            )
        payload["source_file_sha256"] = hashlib.sha256(content).hexdigest()
        payload["course_type_id"] = course_type_id
        summary = {**summary, "error_count": error_count}

        # 教职工三类资料按规范种类落库（同义目标名归一），不再借用旧目标的别名。
        db_target = (
            staff_adapter.normalize_staff_target(target)
            if staff_adapter.is_staff_target(target)
            else target
        )
        batch = ImportBatch(
            target=db_target,
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
        if commit:
            self._session.commit()
        else:
            self._session.flush()
        return self._to_preview(batch)

    def _validate_scope(
        self, target: str, *, semester_id: int | None, teaching_class_id: int | None
    ) -> None:
        if staff_adapter.is_staff_target(target):
            staff_adapter.validate_scope(
                target,
                semester_id=semester_id,
                teaching_class_id=teaching_class_id,
                academic=self._academic,
            )
            return
        need = iperm.TARGET_SCOPE_FIELDS[target]
        if "semester_id" in need:
            if semester_id is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "该导入目标必须提供 semester_id",
                    http_status=422,
                    field_errors={"semester_id": "required"},
                )
            if self._academic.get_semester(semester_id) is None:
                raise NotFoundError("学期不存在")
        if "teaching_class_id" in need:
            if teaching_class_id is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "该导入目标必须提供 teaching_class_id",
                    http_status=422,
                    field_errors={"teaching_class_id": "required"},
                )
            if self._academic.get_teaching_class(teaching_class_id) is None:
                raise NotFoundError("教学班不存在")

    # ---- 解析器：产出 (payload, issues, summary) ----
    def _parse_roster(
        self,
        rows: list[dict[str, str]],
        teaching_class_id: int | None,
        replace: bool = False,
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        seen: dict[str, int] = {}
        student_nos: list[str] = []
        student_sources = {}
        for idx, raw in enumerate(rows, start=2):
            idx = int(raw.get("_source_row", idx))
            no = pick(raw, "学号", "student_no", "studentno", "no")
            if not no:
                issues.append(_issue("missing_student_no", "学号为空", field="学号", row=idx))
                continue
            if no in seen:
                issues.append(
                    _issue(
                        "duplicate_student",
                        f"学号 {no} 重复",
                        field="学号",
                        row=idx,
                        severity="warning",
                    )
                )
                continue
            seen[no] = idx
            if self._academic.get_student_by_no(no) is None:
                issues.append(
                    _issue("unknown_student", f"学号 {no} 不存在于学生名单", field="学号", row=idx)
                )
                continue
            student_nos.append(no)
            student_sources[no] = {"row": idx, "sheet": raw.get("_source_sheet")}
        payload = {
            "student_nos": student_nos,
            "student_sources": student_sources,
            # 名单导入只做补充/差异确认：未出现在文件中的现有成员一律保留。
            # 减少成员必须走显式差异确认或学籍异动流程，不能靠 replace 隐式整体覆盖。
            "preserve_existing": True,
            "replace": False,
        }
        if replace:
            issues.append(
                _issue(
                    "roster_additive_only",
                    "名单导入按补充语义执行，未出现在本文件中的现有成员不会被删除；"
                    "需要减少成员请改用学生数据差异预览与学籍异动流程。",
                    severity="warning",
                )
            )
        summary = {"row_total": len(rows), "student_total": len(student_nos)}
        return payload, issues, summary

    def _parse_volunteer(
        self, rows: list[dict[str, str]], semester_id: int | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        by_no: dict[str, dict] = {}
        for idx, raw in enumerate(rows, start=2):
            idx = int(raw.get("_source_row", idx))
            no = pick(raw, "学号", "student_no", "studentno", "no")
            if not no:
                issues.append(_issue("missing_student_no", "学号为空", field="学号", row=idx))
                continue
            enabled = _parse_bool(pick(raw, "是否启用", "启用", "enabled", "enable"))
            if no in by_no:
                issues.append(
                    _issue(
                        "duplicate_student",
                        f"学号 {no} 重复，取末次",
                        field="学号",
                        row=idx,
                        severity="warning",
                    )
                )
            if self._academic.get_student_by_no(no) is None:
                issues.append(
                    _issue("unknown_student", f"学号 {no} 不存在于学生名单", field="学号", row=idx)
                )
                continue
            by_no[no] = {"student_no": no, "enabled": enabled, "source_row": idx,
                         "source_sheet": raw.get("_source_sheet")}
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
            idx = int(raw.get("_source_row", idx))
            class_code = pick(raw, "教学班码", "教学班", "class_code")
            course_code = pick(raw, "课程代码", "课程编码", "course_code")
            course_name = pick(raw, "课程名称", "课程", "course_name")
            weekday_raw = pick(raw, "星期", "weekday", "周")
            start_raw = pick(raw, "开始大节", "start_period", "起节")
            end_raw = pick(raw, "结束大节", "end_period", "止节")
            weeks_raw = pick(raw, "周次", "weeks", "上课周")
            classroom = pick(raw, "上课地点", "地点", "classroom")
            teacher = pick(raw, "任课老师", "授课教师", "任课教师", "教师", "老师", "teacher")
            row_issue = self._validate_timetable_row(
                idx,
                class_code,
                course_code,
                weekday_raw,
                start_raw,
                end_raw,
                weeks_raw,
                total_weeks,
                issues,
            )
            if row_issue is None:
                continue
            weekday, start, end, weeks = row_issue
            key = (class_code, course_code, weekday, start, end, tuple(weeks), classroom, teacher)
            if key in seen:
                issues.append(
                    _issue(
                        "duplicate_entry",
                        "重复课表行，已合并",
                        field=None,
                        row=idx,
                        severity="warning",
                    )
                )
                continue
            seen.add(key)
            entries.append(
                {
                    "class_code": class_code,
                    "source_row": idx,
                    "source_sheet": raw.get("_source_sheet"),
                    "course_code": course_code,
                    "course_name": course_name or course_code,
                    "weekday": weekday,
                    "start_period": start,
                    "end_period": end,
                    "weeks": list(weeks),
                    "classroom": classroom,
                    "teacher": teacher or None,
                    "teacher_staff_no": pick(
                        raw, "教师工号", "任课教师工号", "教工号", "teacher_staff_no"
                    ) or None,
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
        self,
        idx: int,
        class_code: str,
        course_code: str,
        weekday_raw: str,
        start_raw: str,
        end_raw: str,
        weeks_raw: str,
        total_weeks: int,
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
        max_period = 60 if get_settings().campus_business_scoped_enabled else 20
        if not 1 <= start <= max_period or not 1 <= end <= max_period:
            issues.append(_issue("period_out_of_range", f"大节须为 1..{max_period}", row=idx))
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

    def list_recent(self, actor: CurrentUser, limit: int = 10) -> list[ImportBatchListItem]:
        """最近导入列表仅学院工作区提供；旧兼容入口不暴露暂存批次清单。"""
        raise AppError(ErrorCode.STATE_CONFLICT, "请从已授权学院工作区执行导入", 409)

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
            target=(batch.payload_json or {}).get("import_type") or batch.target,
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
        self, actor: CurrentUser, batch_id: int, request_id: str | None,
        *, commit: bool = True, prepared_payload: dict | None = None,
    ) -> ImportConfirmResponse:
        batch = self._repo.get_for_update(batch_id)
        if batch is None:
            raise NotFoundError("导入批次不存在")
        # 批次落库的 target 是教职工资料的兼容别名，确认时按真实资料种类授权。
        self._require_composite(
            actor.id, (batch.payload_json or {}).get("import_type") or batch.target
        )

        if batch.status == ImportBatchStatus.CONFIRMED.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该批次已确认，不可重复导入")
        if batch.status != ImportBatchStatus.PREVIEW.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, f"批次状态 {batch.status} 不可确认")
        if batch.expires_at <= utcnow():
            batch.status = ImportBatchStatus.EXPIRED.value
            if commit:
                self._session.commit()
            raise ConflictError(ErrorCode.STATE_CONFLICT, "预览已过期，请重新上传")

        issues = batch.error_json or []
        if any(i.get("severity") == "error" for i in issues):
            raise AppError(ErrorCode.VALIDATION_ERROR, "存在错误项，无法确认导入", http_status=422)

        payload = prepared_payload if prepared_payload is not None else (batch.payload_json or {})
        self._session.execute(select(Semester.id).order_by(Semester.id).with_for_update()).all()
        links = None
        if "person_links" in (batch.payload_json or {}) and not payload.get("skip_person_links"):
            from app.modules.importer.person_links import plan_links

            links = payload.get("person_links")
            if prepared_payload is None and plan_links(
                self, batch.target, batch.payload_json, batch.semester_id
            ) != links:
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT, "人员匹配或任职关系已变化，请重新读取资料核对"
                )
        if payload.get("confirmation_skip"):
            created = {"unchanged": True}
        elif payload.get("import_type") and staff_adapter.is_staff_target(payload["import_type"]):
            created = staff_adapter.apply_staff(self._session, actor, batch, payload, request_id)
        elif batch.target == ImportTarget.ROSTER.value:
            created = self._apply_roster(actor, batch, payload, request_id)
        elif batch.target == ImportTarget.VOLUNTEER.value:
            created = self._apply_volunteer(actor, batch, payload, request_id)
        elif batch.target == ImportTarget.ADMIN_ROSTER.value:
            created = self._apply_admin_roster(actor, batch, payload, request_id)
        elif batch.target == ImportTarget.GRID_TIMETABLE.value:
            created = self._apply_grid_timetable(actor, batch, payload, request_id)
        elif batch.target == ImportTarget.ELECTIVE_COURSE.value:
            created = self._apply_elective_course(actor, batch, payload, request_id)
        else:
            created = self._apply_timetable(actor, batch, payload, request_id)

        if links is not None and not payload.get("skip_person_links"):
            from app.modules.importer.person_links import apply_links

            created.update(apply_links(self, links, batch.semester_id, request_id))
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
        if commit:
            self._session.commit()
        return ImportConfirmResponse(
            id=batch.id,
            target=(batch.payload_json or {}).get("import_type") or batch.target,
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
        from app.modules.academic.enrollment_service import EnrollmentService
        from app.modules.academic.roster_lifecycle import record_roster_replacement

        lifecycle = EnrollmentService(self._session)
        lifecycle._lock_semesters()
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
        if payload.get("preserve_existing"):
            ids = sorted(
                set(ids) | {student.id for student in self._academic.get_roster_students(tc.id)}
            )
        record_roster_replacement(self._session, tc.id, ids, lifecycle.today)
        self._academic.set_roster(tc.id, ids)
        self._session.flush()
        lifecycle._refresh_tasks(0, lifecycle.today, actor.id, teaching_class_id=tc.id)
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
                from app.modules.identity.role_scope import current_student_college
                vq.college_id = current_student_college(self._session, stu)
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
        role = self._identity.get_or_create_role(RoleCode.VOLUNTEER.value, RoleCode.VOLUNTEER.value)
        self._identity.grant_role(acct.id, role.id)
        acct.lock_version += 1
        return True

    def _resolve_course_type(
        self, college_id: int | None, course_type_id: int | None
    ) -> int | None:
        from app.modules.academic.campus_models import CourseType

        if course_type_id is not None:
            stmt = select(CourseType).where(
                CourseType.id == course_type_id,
                CourseType.status == "ACTIVE",
            )
            if college_id is not None:
                stmt = stmt.where(CourseType.college_id == college_id)
            ctype = self._session.scalar(stmt)
            if ctype is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, "所选课程类型不存在、非本院或已停用", 422
                )
            return ctype.id
        if college_id is not None:
            ctype = self._session.scalar(
                select(CourseType).where(
                    CourseType.college_id == college_id,
                    CourseType.builtin_key == "regular",
                    CourseType.status == "ACTIVE",
                )
            )
            if ctype is not None:
                return ctype.id
        return None

    def _apply_timetable(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        sem = self._require_active_semester_for_confirm(batch.semester_id)
        resolved_type_id = self._resolve_course_type(
            batch.college_id, payload.get("course_type_id")
        )
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
            tc = self._academic.get_teaching_class_by_key(sem.id, course.id, e["class_code"])
            if tc is None:
                tc = TeachingClass(
                    semester_id=sem.id,
                    course_id=course.id,
                    college_id=batch.college_id,
                    course_type_id=resolved_type_id,
                    class_code=e["class_code"],
                    class_name=e["course_name"],
                    teacher_name=e.get("teacher"),
                    status="ACTIVE",
                )
                self._academic.add(tc)
                self._academic.flush()
                tcs_created += 1
            else:
                if e.get("teacher") and not tc.teacher_name:
                    tc.teacher_name = e.get("teacher")
                if resolved_type_id and not tc.course_type_id:
                    tc.course_type_id = resolved_type_id
            schedule = CourseSchedule(
                semester_id=sem.id,
                teaching_class_id=tc.id,
                weekday=e["weekday"],
                start_period=e["start_period"],
                end_period=e["end_period"],
                classroom=e["classroom"] or None,
                teacher=e.get("teacher"),
                status="ACTIVE",
            )
            self._check_schedule_overlap(schedule, e["weeks"])
            self._academic.add(schedule)
            self._academic.flush()
            self._academic.set_schedule_weeks(schedule, e["weeks"])
            schedules_created += 1
            # 若教学班码对应行政班，自动将行政班学生关联入教学班名单
            ac = self._academic.get_admin_class_by_code(e["class_code"])
            if ac is None:
                ac = self._session.execute(
                    select(AdministrativeClass).where(
                        AdministrativeClass.class_name == e["class_code"]
                    )
                ).scalar_one_or_none()
            if ac is not None:
                stus = list(
                    self._session.execute(
                        select(Student).where(
                            Student.administrative_class_id == ac.id,
                            Student.status == "ACTIVE",
                        )
                    )
                    .scalars()
                    .all()
                )
                if stus:
                    existing_sids = set(
                        self._session.execute(
                            select(TeachingClassStudent.student_id).where(
                                TeachingClassStudent.teaching_class_id == tc.id
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for st in stus:
                        if st.id not in existing_sids:
                            self._session.add(
                                TeachingClassStudent(teaching_class_id=tc.id, student_id=st.id)
                            )
                            existing_sids.add(st.id)
                    self._academic.flush()

        return {
            "course_created": courses_created,
            "teaching_class_created": tcs_created,
            "schedule_created": schedules_created,
            "resource_type": "semester",
            "resource_id": str(sem.id),
        }

    # ================================================================== #
    # 行政班花名册导入 (ADMIN_ROSTER)
    # ================================================================== #
    def _parse_admin_roster(
        self, content: bytes, filename: str | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        students: list[dict] = []
        seen_nos: dict[str, int] = {}

        default_class_name = ""
        default_college = ""
        default_grade = None

        if filename:
            clean_fn = re.sub(r"\.(xlsx|xls|csv)$", "", filename, flags=re.IGNORECASE).strip()
            default_class_name = re.sub(r"(考勤表|课表|名单|责任区).*$", "", clean_fn).strip()

        parsed_rows: list[dict[str, str]] = []
        class_duties: list[dict] = []

        try:
            from app.modules.importer.attendance_roster import inspect_attendance, read_sheets

            sheets = read_sheets(content)
            attendance = inspect_attendance(sheets)
            matrix = sheets[0][1] if sheets else read_any_matrix(content)
            if attendance:
                issues.extend(attendance["issues"])
        except Exception as exc:
            issues.append(_issue("parse_failed", f"文件解析失败：{exc}"))
            return (
                {"students": [], "class_duties": []},
                issues,
                {"row_total": 0, "student_count": 0},
            )

        # 扫描责任区名单或“学院 班名 班级年份”等首行标题。
        if matrix and len(matrix) > 0 and matrix[0]:
            r1_val = " ".join([_clean(c) for c in matrix[0]]).strip()
            m = re.search(r"([\u4e00-\u9fa5]+学院)\s+([\u4e00-\u9fa5\w]+)\s+班级(\d+)年", r1_val)
            if m:
                default_college = m.group(1).strip()
                default_class_name = m.group(2).strip()
                default_grade = int(m.group(3))
            else:
                m2 = re.search(r"([^\s]+学院)\s+([^\s]+)\s+.*?考勤表", r1_val)
                if m2:
                    default_college = m2.group(1).strip()
                    default_class_name = m2.group(2).strip()

        # 2. 扫描前 15 行寻找表头
        header_row_idx = -1
        sno_col, name_col, class_col, college_col, grade_col = -1, -1, -1, -1, -1
        head_teacher_col, counselor_col = -1, -1

        for r_idx, row in enumerate(matrix[:15]):
            cur_sno, cur_name, cur_class, cur_college, cur_grade = -1, -1, -1, -1, -1
            cur_ht, cur_co = -1, -1
            has_duty_number = False
            for c_idx, val in enumerate(row):
                cell = _clean(val)
                if cell in ("学号", "student_no", "studentno", "no"):
                    cur_sno = c_idx
                elif cell in ("姓名", "学生姓名", "name", "student_name"):
                    cur_name = c_idx
                elif cell in ("班级", "班级名称", "行政班", "行政班级", "class_name", "class"):
                    cur_class = c_idx
                elif cell in ("学院", "二级学院", "所属学院", "college", "department"):
                    cur_college = c_idx
                elif cell in ("年级", "grade_year", "grade"):
                    cur_grade = c_idx
                elif cell in ("班主任", "班主任姓名", "head_teacher", "headteacher"):
                    cur_ht = c_idx
                elif cell in ("辅导员", "辅导员姓名", "counselor"):
                    cur_co = c_idx
                elif cell in (
                    "班主任工号", "辅导员工号", "head_teacher_staff_no", "counselor_staff_no"
                ):
                    has_duty_number = True

            if cur_sno >= 0 or (cur_class >= 0 and (cur_ht >= 0 or cur_co >= 0 or has_duty_number)):
                header_row_idx = r_idx
                sno_col = cur_sno
                name_col = cur_name
                class_col = cur_class
                college_col = cur_college
                grade_col = cur_grade
                head_teacher_col = cur_ht
                counselor_col = cur_co
                break

        def derive_grade(cname: str, grade_raw: str | None = None) -> int | None:
            if grade_raw and str(grade_raw).isdigit():
                y = int(grade_raw)
                if y > 2000:
                    return y
                if 20 <= y <= 99:
                    return 2000 + y
            m_4d = re.search(r"20(\d{2})\d{2}$", cname)
            if m_4d:
                return 2000 + int(m_4d.group(1))
            m_2d = re.search(r"(\d{2})\d{2}$", cname)
            if m_2d:
                return 2000 + int(m_2d.group(1))
            return default_grade

        if header_row_idx >= 0 and sno_col >= 0:
            # 学生级花名册
            for r_idx in range(header_row_idx + 1, len(matrix)):
                row = matrix[r_idx]
                if not row or all(not str(c).strip() for c in row):
                    continue
                sno = _clean(row[sno_col]) if sno_col < len(row) else ""
                if sno.endswith(".0"):
                    sno = sno[:-2]
                name = _clean(row[name_col]) if name_col >= 0 and name_col < len(row) else ""
                cname = (
                    _clean(row[class_col])
                    if class_col >= 0 and class_col < len(row)
                    else default_class_name
                )
                college = (
                    _clean(row[college_col])
                    if college_col >= 0 and college_col < len(row)
                    else default_college
                )
                raw_grade = (
                    _clean(row[grade_col]) if grade_col >= 0 and grade_col < len(row) else None
                )
                grade_year = derive_grade(cname, raw_grade)
                ht = (
                    _clean(row[head_teacher_col])
                    if head_teacher_col >= 0 and head_teacher_col < len(row)
                    else None
                )
                co = (
                    _clean(row[counselor_col])
                    if counselor_col >= 0 and counselor_col < len(row)
                    else None
                )
                if sno and re.match(r"^\d{6,20}$", sno):
                    parsed_rows.append(
                        {
                            "student_no": sno,
                            "_source_row": str(r_idx + 1),
                            "name": name,
                            "class_name": cname or default_class_name,
                            "college": college,
                            "grade_year": str(grade_year or ""),
                            "head_teacher": ht or None,
                            "counselor": co or None,
                        }
                    )
        elif header_row_idx >= 0 and class_col >= 0:
            # 纯班级责任区表（如《二级学院学生责任区辅导员、班主任名单》）
            for r_idx in range(header_row_idx + 1, len(matrix)):
                row = matrix[r_idx]
                if not row or all(not str(c).strip() for c in row):
                    continue
                cname = _clean(row[class_col]) if class_col < len(row) else ""
                if not cname:
                    continue
                college = (
                    _clean(row[college_col])
                    if college_col >= 0 and college_col < len(row)
                    else default_college
                )
                raw_grade = (
                    _clean(row[grade_col]) if grade_col >= 0 and grade_col < len(row) else None
                )
                grade_year = derive_grade(cname, raw_grade)
                ht = (
                    _clean(row[head_teacher_col])
                    if head_teacher_col >= 0 and head_teacher_col < len(row)
                    else None
                )
                co = (
                    _clean(row[counselor_col])
                    if counselor_col >= 0 and counselor_col < len(row)
                    else None
                )
                class_duties.append(
                    {
                        "class_name": cname,
                        "source_row": r_idx + 1,
                        "college": college or None,
                        "grade_year": grade_year,
                        "head_teacher": ht or None,
                        "counselor": co or None,
                    }
                )
        else:
            # 尝试降级兼容键值对通用格式
            try:
                raw_rows = read_tabular_rows(content, include_source=True)
                for raw in raw_rows:
                    sno = pick(raw, "学号", "student_no", "studentno", "no")
                    name = pick(raw, "姓名", "name", "student_name")
                    cname = (
                        pick(raw, "班级", "班级名称", "行政班", "class_name", "class")
                        or default_class_name
                    )
                    college = pick(raw, "学院", "所属学院", "college") or default_college
                    grade = pick(raw, "年级", "grade_year", "grade") or (
                        str(default_grade) if default_grade else ""
                    )
                    ht = pick(raw, "班主任", "head_teacher", "班主任姓名")
                    co = pick(raw, "辅导员", "counselor", "辅导员姓名")
                    if sno:
                        parsed_rows.append(
                            {
                                "student_no": sno,
                                "_source_row": raw.get("_source_row"),
                                "name": name,
                                "class_name": cname,
                                "college": college,
                                "grade_year": grade,
                                "head_teacher": ht or None,
                                "counselor": co or None,
                            }
                        )
                    elif cname and (ht or co):
                        class_duties.append(
                            {
                                "class_name": cname,
                                "college": college or None,
                                "grade_year": derive_grade(cname, grade),
                                "head_teacher": ht or None,
                                "counselor": co or None,
                            }
                        )
            except Exception as exc:
                issues.append(_issue("parse_failed", f"花名册解析失败：{exc}"))
                return (
                    {"students": [], "class_duties": []},
                    issues,
                    {"row_total": 0, "student_count": 0},
                )

        class_names: set[str] = set()
        for idx, row in enumerate(parsed_rows, start=2):
            idx = int(row.get("_source_row") or idx)
            sno = row["student_no"]
            name = row["name"]
            cname = row["class_name"]
            if not sno:
                issues.append(_issue("missing_student_no", "学号为空", field="学号", row=idx))
                continue
            if not re.match(r"^\d{6,20}$", sno):
                issues.append(
                    _issue("invalid_student_no", f"学号格式不合规：{sno}", field="学号", row=idx)
                )
                continue
            if not name:
                issues.append(
                    _issue("missing_student_name", f"学生 {sno} 姓名为空", field="姓名", row=idx)
                )
                continue
            if not cname:
                issues.append(
                    _issue("missing_class_name", f"学生 {sno} 缺少班级名称", field="班级", row=idx)
                )
                continue
            if sno in seen_nos:
                issues.append(
                    _issue(
                        "duplicate_student",
                        f"学号 {sno} 在文件第 {seen_nos[sno]} 行已出现，本次跳过",
                        field="学号",
                        row=idx,
                        severity="warning",
                    )
                )
                continue
            seen_nos[sno] = idx
            class_names.add(cname)
            grade_y = (
                int(row["grade_year"])
                if row.get("grade_year") and row["grade_year"].isdigit()
                else None
            )
            students.append(
                {
                    "student_no": sno,
                    "source_row": idx,
                    "name": name,
                    "class_name": cname,
                    "college": row.get("college") or None,
                    "grade_year": grade_y,
                    "head_teacher": row.get("head_teacher") or None,
                    "counselor": row.get("counselor") or None,
                }
            )

        for cd in class_duties:
            class_names.add(cd["class_name"])

        payload = {"students": students, "class_duties": class_duties}
        # 原表可仅填工号；不要在学生规范化过程中丢失职责的唯一人员标识。
        if header_row_idx >= 0:
            headers = [_clean(cell) for cell in matrix[header_row_idx]]
            for record in [*students, *class_duties]:
                source_row = record.get("source_row")
                if source_row is None:
                    continue
                cells = matrix[int(source_row) - 1]
                for key, aliases in (
                    ("head_teacher_staff_no", ("班主任工号", "head_teacher_staff_no")),
                    ("counselor_staff_no", ("辅导员工号", "counselor_staff_no")),
                ):
                    index = next((i for i, header in enumerate(headers) if header in aliases), None)
                    if index is not None and index < len(cells):
                        record[key] = _clean(cells[index])
        summary = {
            "row_total": len(parsed_rows) + len(class_duties),
            "student_count": len(students),
            "class_duties_count": len(class_duties),
            "classes_count": len(class_names),
            "class_names": sorted(class_names),
        }
        if attendance:
            summary.update(
                {
                    key: attendance[key]
                    for key in ("source_sheet", "verified_auxiliary_sheets", "ignored_sheets")
                }
            )
            for student in students:
                student["source_sheet"] = attendance["source_sheet"]
        return payload, issues, summary

    def _apply_admin_roster(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        students_data: list[dict] = payload.get("students") or []
        class_duties: list[dict] = payload.get("class_duties") or []
        if "student_baseline" not in payload:
            raise ConflictError(message="旧版名单预览缺少学籍版本，请重新上传预览")
        # 老师旧文件只能增量维护，禁止隐式转班或复活离校身份。
        for item in students_data:
            current = self._academic.get_student_by_no(item["student_no"])
            baseline = payload["student_baseline"].get(item["student_no"])
            if (baseline is None and current is not None) or (
                baseline is not None
                and (
                    current is None
                    or str(current.id) != baseline["id"]
                    or current.lock_version != baseline["version"]
                )
            ):
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT, "学生资料在预览后已变化，请重新上传，整批未应用"
                )
            if current is not None:
                if current.name != item["name"]:
                    raise ConflictError(
                        message="学号对应姓名与档案不一致，请先核对原表或明确修改学生档案"
                    )
                ac = (
                    self._academic.get_admin_class(current.administrative_class_id)
                    if current.administrative_class_id
                    else None
                )
                if (
                    current.status != "ACTIVE"
                    or ac is None
                    or normalize_class_name(ac.class_name)
                    != normalize_class_name(item["class_name"])
                ):
                    raise ConflictError(
                        message="名单包含转班或非在读学生，请使用学生数据差异预览及学籍异动流程，整批未应用"
                    )
        if not students_data and not class_duties:
            return {"students_created": 0, "students_updated": 0, "classes_created": 0}

        ac_map: dict[str, AdministrativeClass] = {}
        classes_created = 0

        existing_acs = list(self._session.execute(select(AdministrativeClass)).scalars().all())
        ac_by_exact = {ac.class_name: ac for ac in existing_acs}
        ac_by_code = {ac.class_code: ac for ac in existing_acs}
        ac_by_norm = {normalize_class_name(ac.class_name): ac for ac in existing_acs}

        # 先处理纯责任区班主任辅导员名单
        for duty in class_duties:
            cname = duty["class_name"]
            target_ac = (
                ac_by_exact.get(cname)
                or ac_by_code.get(cname)
                or ac_by_norm.get(normalize_class_name(cname))
            )
            if target_ac is None:
                target_ac = AdministrativeClass(
                    class_code=cname,
                    class_name=cname,
                    college=duty.get("college"),
                    grade_year=duty.get("grade_year"),
                    head_teacher=duty.get("head_teacher"),
                    counselor=duty.get("counselor"),
                    status="ACTIVE",
                )
                self._academic.add(target_ac)
                self._academic.flush()
                classes_created += 1
                ac_by_exact[cname] = target_ac
                ac_by_code[cname] = target_ac
                ac_by_norm[normalize_class_name(cname)] = target_ac
            else:
                if duty.get("head_teacher"):
                    target_ac.head_teacher = duty["head_teacher"]
                if duty.get("counselor"):
                    target_ac.counselor = duty["counselor"]
                if duty.get("college") and not target_ac.college:
                    target_ac.college = duty["college"]
                self._academic.flush()
            ac_map[cname] = target_ac

        for item in students_data:
            cname = item["class_name"]
            if cname in ac_map:
                target_ac = ac_map[cname]
                if item.get("head_teacher") and not target_ac.head_teacher:
                    target_ac.head_teacher = item["head_teacher"]
                if item.get("counselor") and not target_ac.counselor:
                    target_ac.counselor = item["counselor"]
                continue
            target_ac = (
                ac_by_exact.get(cname)
                or ac_by_code.get(cname)
                or ac_by_norm.get(normalize_class_name(cname))
            )
            if target_ac is None:
                target_ac = AdministrativeClass(
                    class_code=cname,
                    class_name=cname,
                    college=item.get("college"),
                    grade_year=item.get("grade_year"),
                    head_teacher=item.get("head_teacher"),
                    counselor=item.get("counselor"),
                    status="ACTIVE",
                )
                self._academic.add(target_ac)
                self._academic.flush()
                classes_created += 1
                ac_by_exact[cname] = target_ac
                ac_by_code[cname] = target_ac
                ac_by_norm[normalize_class_name(cname)] = target_ac
            else:
                if not target_ac.college and item.get("college"):
                    target_ac.college = item.get("college")
                if not target_ac.grade_year and item.get("grade_year"):
                    target_ac.grade_year = item.get("grade_year")
                if item.get("head_teacher") and not target_ac.head_teacher:
                    target_ac.head_teacher = item["head_teacher"]
                if item.get("counselor") and not target_ac.counselor:
                    target_ac.counselor = item["counselor"]
                self._academic.flush()
            ac_map[cname] = target_ac

        students_created = 0
        students_updated = 0
        students_transferred = 0
        affected_students = set()

        for item in students_data:
            sno = item["student_no"]
            ac = ac_map[item["class_name"]]
            stu = self._academic.get_student_by_no(sno)
            if stu is None:
                stu = Student(
                    student_no=sno,
                    name=item["name"],
                    administrative_class_id=ac.id,
                    status="ACTIVE",
                )
                self._academic.add(stu)
                self._academic.flush()
                from app.modules.academic.enrollment_service import EnrollmentService

                EnrollmentService(self._session)._baseline(stu)
                affected_students.add(stu.id)
                students_created += 1
            else:
                name_changed = stu.name != item["name"]
                if name_changed:
                    stu.lock_version += 1
                stu.name = item["name"]
                if stu.administrative_class_id is not None and stu.administrative_class_id != ac.id:
                    students_transferred += 1
                students_updated += 1
                if name_changed:
                    affected_students.add(stu.id)
        self._academic.flush()

        if affected_students:
            from app.modules.academic.enrollment_service import EnrollmentService

            lifecycle = EnrollmentService(self._session)
            lifecycle._refresh_tasks(0, lifecycle.today, actor.id, student_ids=affected_students)

        return {
            "classes_created": classes_created,
            "students_created": students_created,
            "students_updated": students_updated,
            "students_transferred": students_transferred,
            "total_students": len(students_data),
            "resource_type": "administrative_class",
            "resource_id": str(batch.id),
        }

    # ================================================================== #
    # 学校网格课表导入 (GRID_TIMETABLE)
    # ================================================================== #
    def _check_grid_target_empty(self, administrative_class, semester_id):
        from app.modules.academic.enrollment_models import TeachingClassAudience

        existing = self._session.scalar(
            select(CourseSchedule.id).join(TeachingClass,
                TeachingClass.id == CourseSchedule.teaching_class_id)
            .outerjoin(TeachingClassAudience,
                TeachingClassAudience.teaching_class_id == TeachingClass.id)
            .where(CourseSchedule.semester_id == semester_id,
                   CourseSchedule.status == "ACTIVE",
                   or_(TeachingClassAudience.administrative_class_id == administrative_class.id,
                       TeachingClass.class_code == administrative_class.class_code,
                       TeachingClass.class_code.startswith(
                           administrative_class.class_code + "_", autoescape=True)))
            .limit(1).with_for_update()
        )
        if existing is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT,
                "该行政班已有有效课表，不能把整张网格课表再次追加；请先明确处理旧课表后再导入")

    def _check_schedule_overlap(self, candidate, weeks):
        from app.modules.academic.schedule_integrity import require_no_schedule_overlap

        existing = list(self._session.scalars(
            select(CourseSchedule).where(
                CourseSchedule.teaching_class_id == candidate.teaching_class_id,
                CourseSchedule.semester_id == candidate.semester_id,
                CourseSchedule.weekday == candidate.weekday,
                CourseSchedule.status == "ACTIVE",
                CourseSchedule.start_period <= candidate.end_period,
                CourseSchedule.end_period >= candidate.start_period,
            ).with_for_update()
        ))
        week_map = {row.id: [] for row in existing}
        for sid, week in self._session.execute(
            select(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no).where(
                CourseScheduleWeek.schedule_id.in_(week_map)
            )
        ):
            week_map[sid].append(week)
        week_map[None] = weeks
        require_no_schedule_overlap([*existing, candidate], week_map)

    def grid_slot_mapping(self, semester_id: int) -> dict[int, int]:
        periods = set(self._session.scalars(
            select(PeriodDefinition.period_no).where(PeriodDefinition.semester_id == semester_id)
        ))
        if periods == set(range(1, 13)):
            return {number: number for number in periods}
        if periods == set(range(1, 6)):
            return SCHOOL_SLOT_MAPPING
        raise AppError(ErrorCode.VALIDATION_ERROR,
                       "学期节次口径不明确，请使用已配置教务小节映射的学院导入入口", 422)

    def _parse_grid_timetable(
        self, content: bytes, semester_id: int | None, filename: str | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        sem = self._academic.get_semester(semester_id) if semester_id else None
        if sem is None:
            issues.append(_issue("missing_semester", "必须指定有效学期"))
            return {"class_name": "", "courses": []}, issues, {"course_count": 0}

        try:
            class_id, raw_rows = load_grid(content)
        except Exception as exc:
            issues.append(_issue("grid_parse_error", f"网格课表解析失败：{exc}"))
            return {"class_name": "", "courses": []}, issues, {"course_count": 0}

        if not class_id and filename:
            clean_fn = re.sub(r"\.(xlsx|xls)$", "", filename, flags=re.IGNORECASE).strip()
            class_id = re.sub(r"课表.*$", "", clean_fn).strip()

        if not class_id:
            issues.append(_issue("missing_class_name", "无法从课表文件提取行政班名称"))
            return {"class_name": "", "courses": []}, issues, {"course_count": 0}

        parsed_courses: list[dict] = []
        try:
            slot_mapping = self.grid_slot_mapping(sem.id)
        except AppError as exc:
            issues.append(_issue("missing_grid_mapping", str(exc)))
            return {"class_name": class_id, "courses": []}, issues, {"course_count": 0}
        for idx, row in enumerate(raw_rows, start=1):
            idx = int(row.get("source_row") or idx)
            course_name = row.get("course_name", "").strip()
            if not course_name:
                continue
            try:
                wd = parse_weekday(row.get("weekday", ""))
                weeks = parse_weeks(row.get("weeks", ""), sem.total_weeks)
                slots = parse_period(row.get("period", ""), slot_mapping=slot_mapping)
                if slots != list(range(min(slots), max(slots) + 1)):
                    raise ValueError("小节映射跨越未授课的节次，请拆为连续课程行")
                start_p = min(slots)
                end_p = max(slots)
            except Exception as exc:
                issues.append(
                    _issue("bad_time_slot", f"课程【{course_name}】时间段解析异常：{exc}", row=idx)
                )
                continue

            parsed_courses.append(
                {
                    "source_row": int(row["source_row"]) if row.get("source_row") else None,
                    "source_sheet": row.get("source_sheet"),
                    "source_column": row.get("source_column"),
                    "course_name": course_name,
                    "weekday": wd,
                    "start_period": start_p,
                    "end_period": end_p,
                    "weeks": weeks,
                    "classroom": row.get("location", "").strip(),
                    "teacher": row.get("teacher", "").strip(),
                    "student_count": row.get("count", ""),
                }
            )

        payload = {
            "semester_id": sem.id,
            "class_name": class_id,
            "courses": parsed_courses,
        }
        summary = {
            "class_name": class_id,
            "course_count": len(parsed_courses),
            "total_occurrences": sum(len(c["weeks"]) for c in parsed_courses),
        }
        return payload, issues, summary

    def _apply_grid_timetable(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        sem = self._require_active_semester_for_confirm(batch.semester_id)
        resolved_type_id = self._resolve_course_type(
            batch.college_id, payload.get("course_type_id")
        )
        class_name = payload.get("class_name") or ""
        courses_data: list[dict] = payload.get("courses") or []

        existing_acs = list(self._session.execute(select(AdministrativeClass)).scalars().all())
        target_ac = None
        for ac in existing_acs:
            if ac.class_name == class_name or ac.class_code == class_name:
                target_ac = ac
                break
            if normalize_class_name(ac.class_name) == normalize_class_name(class_name):
                target_ac = ac
                break

        if target_ac is None:
            target_ac = AdministrativeClass(
                class_code=class_name,
                class_name=class_name,
                status="ACTIVE",
            )
            self._academic.add(target_ac)
            self._academic.flush()

        self._check_grid_target_empty(target_ac, sem.id)

        students = list(
            self._session.execute(
                select(Student).where(
                    Student.administrative_class_id == target_ac.id,
                    Student.status == "ACTIVE",
                )
            )
            .scalars()
            .all()
        )

        courses_created = 0
        tcs_created = 0
        schedules_created = 0
        students_linked = 0

        for item in courses_data:
            cname = item["course_name"]
            course = self._session.execute(
                select(Course).where(Course.course_name == cname)
            ).scalar_one_or_none()
            if course is None:
                code_hash = hashlib.md5(cname.encode("utf-8")).hexdigest()[:8].upper()
                course = Course(
                    course_code=f"C_{code_hash}",
                    course_name=cname,
                    status="ACTIVE",
                )
                self._academic.add(course)
                self._academic.flush()
                courses_created += 1

            t_name = item.get("teacher") or None
            tc_code = f"{target_ac.class_code}_{course.course_code}"
            tc = self._academic.get_teaching_class_by_key(sem.id, course.id, tc_code)
            if tc is None:
                tc = TeachingClass(
                    semester_id=sem.id,
                    course_id=course.id,
                    college_id=batch.college_id,
                    course_type_id=resolved_type_id,
                    class_code=tc_code,
                    class_name=f"{target_ac.class_name}-{cname}",
                    teacher_name=t_name,
                    status="ACTIVE",
                )
                self._academic.add(tc)
                self._academic.flush()
                tcs_created += 1
            else:
                if t_name and not tc.teacher_name:
                    tc.teacher_name = t_name
                if resolved_type_id and not tc.course_type_id:
                    tc.course_type_id = resolved_type_id

            from app.modules.academic.enrollment_models import TeachingClassAudience

            if self._session.get(TeachingClassAudience, (tc.id, target_ac.id)) is None:
                self._session.add(
                    TeachingClassAudience(
                        teaching_class_id=tc.id, administrative_class_id=target_ac.id
                    )
                )

            schedule = CourseSchedule(
                semester_id=sem.id,
                teaching_class_id=tc.id,
                weekday=item["weekday"],
                start_period=item["start_period"],
                end_period=item["end_period"],
                classroom=item["classroom"] or None,
                teacher=t_name,
                status="ACTIVE",
            )
            self._check_schedule_overlap(schedule, item["weeks"])
            self._academic.add(schedule)
            self._academic.flush()
            self._academic.set_schedule_weeks(schedule, item["weeks"])
            schedules_created += 1

            if students:
                existing_sids = set(
                    self._session.execute(
                        select(TeachingClassStudent.student_id).where(
                            TeachingClassStudent.teaching_class_id == tc.id
                        )
                    )
                    .scalars()
                    .all()
                )
                for st in students:
                    if st.id not in existing_sids:
                        self._session.add(
                            TeachingClassStudent(teaching_class_id=tc.id, student_id=st.id)
                        )
                        existing_sids.add(st.id)
                        students_linked += 1
                self._academic.flush()

        return {
            "administrative_class": target_ac.class_name,
            "courses_created": courses_created,
            "teaching_classes_created": tcs_created,
            "schedules_created": schedules_created,
            "students_linked": students_linked,
            "enrolled_student_count": len(students),
            "resource_type": "teaching_class",
            "resource_id": str(target_ac.id),
        }

    # ================================================================== #
    # 选修课/分班课精确名单导入 (ELECTIVE_COURSE)
    # ================================================================== #
    def _parse_elective_course(
        self, rows: list[dict[str, str]], semester_id: int | None
    ) -> tuple[dict, list[dict], dict]:
        issues: list[dict] = []
        sem = self._academic.get_semester(semester_id) if semester_id else None
        if sem is None:
            issues.append(_issue("missing_semester", "必须指定有效学期"))
            return {"groups": []}, issues, {"teaching_classes_count": 0}

        groups_map: dict[tuple, list[str]] = {}
        group_sources = {}
        unique_students = set()

        for idx, raw in enumerate(rows, start=2):
            idx = int(raw.get("_source_row", idx))
            cname = pick(raw, "课程名称", "课程", "course_name")
            code = pick(raw, "教学班码", "教学班", "class_code")
            tname = pick(raw, "教学班名", "教学班名称", "class_name") or f"{cname}-{code}"
            weekday_raw = pick(raw, "星期", "weekday", "周")
            start_raw = pick(raw, "开始大节", "start_period", "起节")
            end_raw = pick(raw, "结束大节", "end_period", "止节")
            weeks_raw = pick(raw, "周次", "weeks", "上课周")
            classroom = pick(raw, "上课地点", "地点", "教室", "classroom")
            sno = pick(raw, "学号", "选课学生学号", "student_no", "no")

            if not cname:
                issues.append(
                    _issue("missing_course_name", "课程名称为空", field="课程名称", row=idx)
                )
                continue
            if not code:
                issues.append(
                    _issue("missing_class_code", "教学班码为空", field="教学班码", row=idx)
                )
                continue
            if not sno:
                issues.append(_issue("missing_student_no", "学生学号为空", field="学号", row=idx))
                continue

            try:
                wd = parse_weekday(weekday_raw)
                start = int(start_raw)
                end = int(end_raw)
                weeks = parse_weeks(weeks_raw, sem.total_weeks)
            except Exception as exc:
                issues.append(_issue("bad_time_field", f"时段解析失败：{exc}", row=idx))
                continue

            stu = self._academic.get_student_by_no(sno)
            if stu is None:
                issues.append(
                    _issue("unknown_student", f"学号 {sno} 不存在于学生档案", field="学号", row=idx)
                )
                continue

            key = (cname, code, tname, wd, start, end, tuple(sorted(weeks)), classroom)
            if key not in groups_map:
                groups_map[key] = []
            if sno not in groups_map[key]:
                groups_map[key].append(sno)
            group_sources.setdefault(key, {}).setdefault(
                sno, {"row": idx, "sheet": raw.get("_source_sheet")}
            )
            unique_students.add(sno)

        groups = []
        for group_key, snos in groups_map.items():
            cname, code, tname, wd, start, end, weeks, classroom = group_key
            first_source = next(iter(group_sources[group_key].values()))
            groups.append(
                {
                    "course_name": cname,
                    "class_code": code,
                    "class_name": tname,
                    "weekday": wd,
                    "start_period": start,
                    "end_period": end,
                    "weeks": list(weeks),
                    "classroom": classroom,
                    "student_nos": snos,
                    "source_row": first_source["row"],
                    "source_sheet": first_source["sheet"],
                    "student_sources": group_sources[group_key],
                }
            )

        payload = {"semester_id": sem.id, "groups": groups}
        summary = {
            "row_total": len(rows),
            "teaching_classes_count": len(groups),
            "unique_students": len(unique_students),
        }
        return payload, issues, summary

    def _apply_elective_course(
        self, actor: CurrentUser, batch: ImportBatch, payload: dict, request_id: str | None
    ) -> dict:
        sem = self._require_active_semester_for_confirm(batch.semester_id)
        resolved_type_id = self._resolve_course_type(
            batch.college_id, payload.get("course_type_id")
        )
        groups = payload.get("groups") or []

        courses_created = 0
        tcs_created = 0
        schedules_created = 0
        students_linked = 0

        for g in groups:
            cname = g["course_name"]
            course = self._session.execute(
                select(Course).where(Course.course_name == cname)
            ).scalar_one_or_none()
            if course is None:
                code_hash = hashlib.md5(cname.encode("utf-8")).hexdigest()[:8].upper()
                course = Course(
                    course_code=f"C_{code_hash}",
                    course_name=cname,
                    status="ACTIVE",
                )
                self._academic.add(course)
                self._academic.flush()
                courses_created += 1

            tc = self._academic.get_teaching_class_by_key(sem.id, course.id, g["class_code"])
            if tc is None:
                tc = TeachingClass(
                    semester_id=sem.id,
                    course_id=course.id,
                    college_id=batch.college_id,
                    course_type_id=resolved_type_id,
                    class_code=g["class_code"],
                    class_name=g["class_name"],
                    status="ACTIVE",
                )
                self._academic.add(tc)
                self._academic.flush()
                tcs_created += 1
            elif resolved_type_id and not tc.course_type_id:
                tc.course_type_id = resolved_type_id

            if not (payload.get("preserve_existing") and g.get("schedule_unchanged")):
                schedule = CourseSchedule(
                    semester_id=sem.id,
                    teaching_class_id=tc.id,
                    weekday=g["weekday"],
                    start_period=g["start_period"],
                    end_period=g["end_period"],
                    classroom=g["classroom"] or None,
                    status="ACTIVE",
                )
                self._check_schedule_overlap(schedule, g["weeks"])
                self._academic.add(schedule)
                self._academic.flush()
                self._academic.set_schedule_weeks(schedule, g["weeks"])
                schedules_created += 1

            nos = g.get("student_nos") or []
            sids = [
                self._academic.get_student_by_no(no).id
                for no in nos
                if self._academic.get_student_by_no(no) is not None
            ]
            if payload.get("preserve_existing"):
                from app.modules.academic.roster_lifecycle import record_roster_replacement
                from app.modules.identity.role_scope import business_today
                sids = sorted(set(sids) | {s.id for s in self._academic.get_roster_students(tc.id)})
                record_roster_replacement(self._session, tc.id, sids, business_today())
            self._academic.set_roster(tc.id, sids)
            if payload.get("preserve_existing"):
                from app.modules.academic.enrollment_service import EnrollmentService
                lifecycle = EnrollmentService(self._session)
                lifecycle._refresh_tasks(0, lifecycle.today, actor.id, teaching_class_id=tc.id)
            students_linked += len(sids)

        return {
            "courses_created": courses_created,
            "teaching_classes_created": tcs_created,
            "schedules_created": schedules_created,
            "students_linked": students_linked,
            "resource_type": "teaching_class",
            "resource_id": str(batch.id),
        }

    def import_bulk_files(
        self,
        actor: CurrentUser,
        semester_id: int,
        files: list[tuple[str, bytes]],
        course_type_id: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, object]:
        """批量导入多个名单和课表文件，支持 ZIP 压缩包自动解压并按顺序执行。"""
        import io
        import zipfile

        from app.modules.importer.models import ImportTarget

        # 1. 展开 ZIP 压缩包或收集表格文件
        expanded_files: list[tuple[str, bytes]] = []
        for filename, data in files:
            if filename.lower().endswith((".xlsx", ".xls", ".csv")):
                base_name = filename.replace("\\", "/").split("/")[-1]
                expanded_files.append((base_name, data))
            elif filename.lower().endswith(".zip") or data.startswith(b"PK\x03\x04"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        for info in z.infolist():
                            if info.is_dir():
                                continue
                            fname = info.filename
                            if any(
                                p in fname
                                for p in ["__MACOSX", "._", ".DS_Store", "desktop.ini", "Thumbs.db"]
                            ):
                                continue
                            try:
                                clean_name = info.filename.encode("cp437").decode("gbk")
                            except Exception:
                                try:
                                    clean_name = info.filename.encode("cp437").decode("utf-8")
                                except Exception:
                                    clean_name = info.filename
                            base_name = clean_name.replace("\\", "/").split("/")[-1]
                            if base_name and base_name.lower().endswith((".xlsx", ".xls", ".csv")):
                                expanded_files.append((base_name, z.read(info)))
                except Exception as exc:
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR, f"ZIP压缩包解析失败：{exc}", http_status=422
                    ) from exc

        if not expanded_files:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "未找到任何有效的表格文件（.xlsx / .xls / .csv）",
                http_status=422,
            )

        # 2. 分类：名单类文件 vs 课表类文件
        roster_files: list[tuple[str, bytes]] = []
        timetable_files: list[tuple[str, bytes]] = []
        for fn, data in expanded_files:
            lower_fn = fn.lower()
            if "课表" in fn or "排课" in fn or "timetable" in lower_fn:
                timetable_files.append((fn, data))
            elif (
                "考勤" in fn
                or "花名册" in fn
                or "名单" in fn
                or "学生" in fn
                or "责任区" in fn
                or "班主任" in fn
                or "辅导员" in fn
                or "roster" in lower_fn
            ):
                roster_files.append((fn, data))
            else:
                # 尝试通过内容关键字做轻量嗅探
                sniff_txt = ""
                with suppress(Exception):
                    sniff_txt = data[:8192].decode("utf-8", errors="ignore") + data[:8192].decode(
                        "gbk", errors="ignore"
                    )
                if "星期" in sniff_txt or "周一" in sniff_txt:
                    timetable_files.append((fn, data))
                elif "学号" in sniff_txt:
                    roster_files.append((fn, data))
                else:
                    # 默认降级为花名册
                    roster_files.append((fn, data))

        total_classes_created = 0
        total_students_created = 0
        total_students_updated = 0
        total_transferred = 0
        total_students_count = 0
        total_courses_created = 0
        total_schedules_created = 0
        file_results: list[dict] = []

        # 3. 先执行所有花名册 (ADMIN_ROSTER)
        for fn, data in roster_files:
            try:
                preview = self.create_preview(
                    actor,
                    target=ImportTarget.ADMIN_ROSTER.value,
                    content=data,
                    semester_id=semester_id,
                    teaching_class_id=None,
                    filename=fn,
                    replace=False,
                    request_id=request_id,
                )
                if not preview.can_confirm:
                    err_msg = "存在格式错误"
                    if preview.errors:
                        err_msg = "；".join(
                            str(e.get("message") if isinstance(e, dict) else e)
                            for e in preview.errors[:3]
                        )
                    file_results.append(
                        {
                            "filename": fn,
                            "type": "ADMIN_ROSTER",
                            "status": "FAILED",
                            "error": err_msg,
                        }
                    )
                    continue
                confirmed = self.confirm(actor, batch_id=int(preview.id), request_id=request_id)
                summary = confirmed.summary or {}
                total_classes_created += summary.get("classes_created", 0)
                total_students_created += summary.get("students_created", 0)
                total_students_updated += summary.get("students_updated", 0)
                total_transferred += summary.get("students_transferred", 0)
                total_students_count += summary.get(
                    "total_students", summary.get("student_count", 0)
                )
                file_results.append(
                    {
                        "filename": fn,
                        "type": "ADMIN_ROSTER",
                        "status": "SUCCESS",
                        "summary": summary,
                    }
                )
            except Exception as exc:
                file_results.append(
                    {
                        "filename": fn,
                        "type": "ADMIN_ROSTER",
                        "status": "FAILED",
                        "error": str(exc),
                    }
                )

        # 4. 后执行所有课表 (GRID_TIMETABLE)
        for fn, data in timetable_files:
            try:
                preview = self.create_preview(
                    actor,
                    target=ImportTarget.GRID_TIMETABLE.value,
                    content=data,
                    semester_id=semester_id,
                    teaching_class_id=None,
                    course_type_id=course_type_id,
                    filename=fn,
                    replace=False,
                    request_id=request_id,
                )
                if not preview.can_confirm:
                    err_msg = "存在排课错误"
                    if preview.errors:
                        err_msg = "；".join(
                            str(e.get("message") if isinstance(e, dict) else e)
                            for e in preview.errors[:3]
                        )
                    file_results.append(
                        {
                            "filename": fn,
                            "type": "GRID_TIMETABLE",
                            "status": "FAILED",
                            "error": err_msg,
                        }
                    )
                    continue
                confirmed = self.confirm(actor, batch_id=int(preview.id), request_id=request_id)
                summary = confirmed.summary or {}
                total_courses_created += summary.get("courses_created", 0)
                total_schedules_created += summary.get("schedules_created", 0)
                file_results.append(
                    {
                        "filename": fn,
                        "type": "GRID_TIMETABLE",
                        "status": "SUCCESS",
                        "summary": summary,
                    }
                )
            except Exception as exc:
                file_results.append(
                    {
                        "filename": fn,
                        "type": "GRID_TIMETABLE",
                        "status": "FAILED",
                        "error": str(exc),
                    }
                )

        return {
            "total_files": len(expanded_files),
            "rosters_count": len(roster_files),
            "timetables_count": len(timetable_files),
            "classes_created": total_classes_created,
            "students_created": total_students_created,
            "students_updated": total_students_updated,
            "students_transferred": total_transferred,
            "total_students": total_students_count,
            "courses_created": total_courses_created,
            "schedules_created": total_schedules_created,
            "file_results": file_results,
        }
