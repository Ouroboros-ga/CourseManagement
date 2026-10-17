"""教职工档案、班级责任关系与任课教师授课关系的导入适配器（T02）。

设计要点：
- 前导零：工号以字符串处理，严格保留前导零；
- 明确匹配：工号唯一匹配；仅有姓名时若存在同名或未知教工，阻断并要求工号，不自动授权；
- 缺行/空列不撤销：名单/责任表中缺失行或空责任列不结束现有任职；
- 交接与重叠：交接日同时为旧关系结束日和新关系开始日（半开区间 [effective_from, effective_to)）；
- 无学期与有学期分离：档案无学期，授课必须绑定明确学期与教学班；
- 共享授课：SHARED 锚点列出已覆盖的学院视图；
- 无 commit 内部单元：所有 apply 方法只 flush，统一由确认集合单次提交。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.common.parsing.xlsx_tabular import _clean, pick, read_tabular_rows
from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.academic.models import AdministrativeClass, Semester, TeachingClass
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.academic.staff_repository import StaffRepository
from app.modules.academic.staff_rules import (
    TeachingOverlap,
    classify_teaching_overlap,
    handover_start_allowed,
    latest_responsibility,
)
from app.modules.identity.role_scope import business_today
from app.modules.importer.schemas import ImportTemplateResponse
from app.modules.organization.models import College

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.modules.identity.service import CurrentUser
    from app.modules.importer.models import ImportBatch


STAFF_ARCHIVE_TARGETS = {"faculty_staff", "staff"}
# class_duty 是既有名单模板的显示责任列（行政班 head_teacher/counselor 文本），
# 不构成任职授权；教职工责任关系另用 class_responsibility，两者不得互相顶替。
CLASS_RESPONSIBILITY_TARGETS = {"class_responsibility", "class_staff_responsibility"}
TEACHING_ASSIGNMENT_TARGETS = {
    "teaching_assignment",
    "teaching_staff_assignment",
    "teaching_staff",
}
STAFF_TARGETS = (
    STAFF_ARCHIVE_TARGETS | CLASS_RESPONSIBILITY_TARGETS | TEACHING_ASSIGNMENT_TARGETS
)


def is_staff_target(target: str) -> bool:
    return target in STAFF_TARGETS


def normalize_staff_target(target: str) -> str:
    if target in STAFF_ARCHIVE_TARGETS:
        return "faculty_staff"
    if target in CLASS_RESPONSIBILITY_TARGETS:
        return "class_responsibility"
    if target in TEACHING_ASSIGNMENT_TARGETS:
        return "teaching_assignment"
    return target


def get_scope_fields(target: str) -> tuple[str, ...]:
    norm = normalize_staff_target(target)
    if norm == "teaching_assignment":
        return ("semester_id",)
    return ()


def validate_scope(
    target: str,
    *,
    semester_id: int | None,
    teaching_class_id: int | None,
    academic: Any,
) -> None:
    norm = normalize_staff_target(target)
    if norm == "teaching_assignment":
        if semester_id is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "任课教师授课关系必须提供 semester_id",
                http_status=422,
                field_errors={"semester_id": "required"},
            )
        if academic.get_semester(semester_id) is None:
            raise NotFoundError("学期不存在")


def get_template(target: str) -> ImportTemplateResponse:
    norm = normalize_staff_target(target)
    if norm == "faculty_staff":
        return ImportTemplateResponse(
            target="faculty_staff",
            scope_fields=[],
            columns=[
                {
                    "key": "staff_no",
                    "header": "工号",
                    "aliases": ["工号", "staff_no", "staffno", "teacher_no", "教工号"],
                    "required": True,
                },
                {
                    "key": "name",
                    "header": "姓名",
                    "aliases": ["姓名", "name", "teacher_name", "教职工姓名"],
                    "required": True,
                },
                {
                    "key": "college",
                    "header": "所属学院",
                    "aliases": ["所属学院", "学院", "college", "department"],
                    "required": False,
                },
                {
                    "key": "phone",
                    "header": "联系电话",
                    "aliases": ["联系电话", "电话", "手机号", "phone", "mobile"],
                    "required": False,
                },
                {
                    "key": "status",
                    "header": "启停状态",
                    "aliases": ["启停状态", "状态", "status"],
                    "required": False,
                },
            ],
            example_rows=[
                {
                    "工号": "001001",
                    "姓名": "张三",
                    "所属学院": "软件学院",
                    "联系电话": "13800000001",
                    "启停状态": "正常",
                },
                {
                    "工号": "001002",
                    "姓名": "李四",
                    "所属学院": "软件学院",
                    "联系电话": "13800000002",
                    "启停状态": "正常",
                },
            ],
        )
    if norm == "class_responsibility":
        return ImportTemplateResponse(
            target="class_responsibility",
            scope_fields=[],
            columns=[
                {
                    "key": "class_name",
                    "header": "行政班",
                    "aliases": [
                        "行政班",
                        "班级",
                        "班级名称",
                        "班级代码",
                        "class_name",
                        "class_code",
                        "class",
                    ],
                    "required": True,
                },
                {
                    "key": "head_teacher_staff_no",
                    "header": "班主任工号",
                    "aliases": [
                        "班主任工号",
                        "班主任号",
                        "head_teacher_staff_no",
                        "head_teacher_no",
                    ],
                    "required": False,
                },
                {
                    "key": "head_teacher_name",
                    "header": "班主任姓名",
                    "aliases": ["班主任", "班主任姓名", "head_teacher", "headteacher"],
                    "required": False,
                },
                {
                    "key": "counselor_staff_no",
                    "header": "辅导员工号",
                    "aliases": [
                        "辅导员工号",
                        "辅导员号",
                        "counselor_staff_no",
                        "counselor_no",
                    ],
                    "required": False,
                },
                {
                    "key": "counselor_name",
                    "header": "辅导员姓名",
                    "aliases": ["辅导员", "辅导员姓名", "counselor"],
                    "required": False,
                },
                {
                    "key": "effective_from",
                    "header": "生效日期",
                    "aliases": ["生效日期", "开始日期", "effective_from"],
                    "required": False,
                },
                {
                    "key": "effective_to",
                    "header": "结束日期",
                    "aliases": ["结束日期", "effective_to"],
                    "required": False,
                },
            ],
            example_rows=[
                {
                    "行政班": "软工2201",
                    "班主任工号": "001001",
                    "班主任姓名": "张三",
                    "辅导员工号": "001002",
                    "辅导员姓名": "李四",
                    "生效日期": "2026-09-01",
                    "结束日期": "",
                }
            ],
        )
    # teaching_assignment
    return ImportTemplateResponse(
        target="teaching_assignment",
        scope_fields=["semester_id"],
        columns=[
            {
                "key": "class_code",
                "header": "教学班码",
                "aliases": [
                    "教学班码",
                    "教学班",
                    "教学班标识",
                    "class_code",
                    "teaching_class_code",
                ],
                "required": True,
            },
            {
                "key": "staff_no",
                "header": "教师工号",
                "aliases": ["教师工号", "工号", "staff_no", "teacher_no"],
                "required": False,
            },
            {
                "key": "teacher_name",
                "header": "任课教师",
                "aliases": [
                    "任课教师",
                    "教师姓名",
                    "教师",
                    "老师",
                    "teacher_name",
                    "teacher",
                ],
                "required": False,
            },
            {
                "key": "effective_from",
                "header": "生效日期",
                "aliases": ["生效日期", "开始日期", "effective_from"],
                "required": False,
            },
            {
                "key": "effective_to",
                "header": "结束日期",
                "aliases": ["结束日期", "effective_to"],
                "required": False,
            },
            {
                "key": "anchor_type",
                "header": "锚点类型",
                "aliases": ["锚点类型", "anchor_type"],
                "required": False,
            },
        ],
        example_rows=[
            {
                "教学班码": "TC_SE_01",
                "教师工号": "001001",
                "任课教师": "张三",
                "生效日期": "2026-09-01",
                "结束日期": "2027-01-15",
                "锚点类型": "LOCAL",
            }
        ],
    )


def _parse_date(val: Any) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _college(db: Session, college_id: int | None) -> College:
    """学院缺失即视为批次归属失效；不能回落到硬编码学校 1 写档案。"""
    college = db.get(College, college_id) if college_id is not None else None
    if college is None:
        raise NotFoundError("学院不存在，无法核对教职工归属")
    return college


def _require_semester(batch: ImportBatch) -> int:
    """授课关系批次必须有学期：预览已按 scope_fields 强制，这里只把类型收窄。"""
    if batch.semester_id is None:
        raise NotFoundError("授课关系批次缺少学期")
    return batch.semester_id


def _teaching_overlap(
    repo: StaffRepository,
    *,
    staff_id: int,
    semester_id: int,
    anchor_type: str,
    teaching_class_id: int | None,
    academic_offering_id: str | None,
    start: date,
    end: date | None,
) -> TeachingOverlap:
    """重叠任命分类：与院级管理接口使用 `academic.staff_rules` 的同一判定。"""
    return classify_teaching_overlap(
        repo.overlapping_teaching(staff_id, semester_id, start, end),
        anchor_type=anchor_type,
        teaching_class_id=teaching_class_id,
        academic_offering_id=academic_offering_id,
        covered_offering_id=academic_offering_id or repo.class_offering(teaching_class_id),
    )


def _split_conflicts(
    overlap: TeachingOverlap, anchor_type: str
) -> tuple[list[TeachingStaffAssignment], list[TeachingStaffAssignment]]:
    """按锚点拆开冲突，只为给预览不同的错误码；规则本身不区分来源。"""
    same = [row for row in overlap.conflicts if row.anchor_type == anchor_type]
    other = [row for row in overlap.conflicts if row.anchor_type != anchor_type]
    return same, other


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
    row: int | None = None,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "field": field,
        "row": row,
        "severity": severity,
    }


def parse_faculty_staff(
    db: Session,
    content: bytes,
    college_id: int,
    filename: str | None,
) -> tuple[dict, list[dict], dict]:
    issues: list[dict] = []
    try:
        raw_rows = read_tabular_rows(content, include_source=True)
    except Exception as exc:
        return (
            {"rows": [], "staff_baseline": {}, "import_type": "faculty_staff"},
            [_issue("parse_failed", f"文件解析失败：{exc}")],
            {"row_total": 0, "create_count": 0, "update_count": 0, "unchanged_count": 0},
        )

    college = _college(db, college_id)
    school_id = college.school_id

    parsed_rows: list[dict] = []
    staff_baseline: dict[str, dict] = {}
    seen_nos: set[str] = set()

    for idx, raw in enumerate(raw_rows, start=2):
        row_num = int(raw.get("_source_row", idx))
        source_sheet = raw.get("_source_sheet")

        raw_sno = pick(raw, "工号", "staff_no", "staffno", "teacher_no", "教工号")
        staff_no = _clean(raw_sno)
        if not staff_no:
            issues.append(
                _issue("MISSING_STAFF_NO", "工号不能为空", field="staff_no", row=row_num)
            )
            continue

        raw_name = pick(raw, "姓名", "name", "teacher_name", "教职工姓名")
        name = _clean(raw_name)
        if not name:
            issues.append(
                _issue("MISSING_NAME", "姓名不能为空", field="name", row=row_num)
            )
            continue

        if staff_no in seen_nos:
            issues.append(
                _issue(
                    "DUPLICATE_STAFF_NO",
                    f"文件中存在重复工号：{staff_no}",
                    field="staff_no",
                    row=row_num,
                )
            )
            continue
        seen_nos.add(staff_no)

        col_text = _clean(pick(raw, "所属学院", "学院", "college", "department"))
        if col_text and college and col_text != college.name:
            issues.append(
                _issue(
                    "COLLEGE_MISMATCH",
                    f"所属学院 '{col_text}' 与当前工作区学院 '{college.name}' "
                    "不一致，跨学院教职工档案不可导入",
                    field="college",
                    row=row_num,
                )
            )
            continue

        phone = _clean(pick(raw, "联系电话", "电话", "手机号", "phone", "mobile")) or None
        status_raw = _clean(pick(raw, "启停状态", "状态", "status"))
        status = "ACTIVE"
        if status_raw:
            if status_raw.upper() in ("INACTIVE", "0", "停用", "禁用", "否", "FALSE"):
                status = "INACTIVE"
            elif status_raw.upper() in ("ACTIVE", "1", "正常", "启用", "是", "TRUE"):
                status = "ACTIVE"
            else:
                issues.append(
                    _issue(
                        "INVALID_STATUS",
                        f"无法识别的启停状态：{status_raw}",
                        field="status",
                        row=row_num,
                    )
                )

        # 检查数据库中已存在的教职工
        existing = db.scalar(
            select(FacultyStaff).where(
                FacultyStaff.school_id == school_id,
                FacultyStaff.staff_no == staff_no,
            )
        )
        if existing is not None:
            if existing.college_id != college_id:
                issues.append(
                    _issue(
                        "STAFF_FOREIGN_COLLEGE",
                        f"工号 '{staff_no}' 已在学校其他学院建档，无法跨院覆盖",
                        field="staff_no",
                        row=row_num,
                    )
                )
                continue
            staff_baseline[staff_no] = {
                "id": existing.id,
                "lock_version": existing.lock_version,
                "name": existing.name,
                "phone": existing.phone,
                "status": existing.status,
            }

        parsed_rows.append(
            {
                "staff_no": staff_no,
                "name": name,
                "phone": phone,
                "status": status,
                "source_row": row_num,
                "source_sheet": source_sheet,
            }
        )

    creates = sum(1 for r in parsed_rows if r["staff_no"] not in staff_baseline)
    updates = 0
    unchanged = 0
    for r in parsed_rows:
        if r["staff_no"] in staff_baseline:
            b = staff_baseline[r["staff_no"]]
            if (
                b["name"] == r["name"]
                and (b.get("phone") or None) == (r.get("phone") or None)
                and b["status"] == r["status"]
            ):
                unchanged += 1
            else:
                updates += 1

    summary = {
        "row_total": len(parsed_rows),
        "create_count": creates,
        "update_count": updates,
        "unchanged_count": unchanged,
    }
    payload = {
        "rows": parsed_rows,
        "staff_baseline": staff_baseline,
        "import_type": "faculty_staff",
    }
    return payload, issues, summary


def parse_class_responsibility(
    db: Session,
    content: bytes,
    college_id: int,
    filename: str | None,
) -> tuple[dict, list[dict], dict]:
    issues: list[dict] = []
    try:
        raw_rows = read_tabular_rows(content, include_source=True)
    except Exception as exc:
        return (
            {"duties": [], "responsibility_baseline": {}, "import_type": "class_responsibility"},
            [_issue("parse_failed", f"文件解析失败：{exc}")],
            {"row_total": 0, "duty_count": 0},
        )

    school_id = _college(db, college_id).school_id
    today = business_today()

    parsed_duties: list[dict] = []
    responsibility_baseline: dict[str, dict] = {}

    all_acs = list(
        db.scalars(
            select(AdministrativeClass).where(AdministrativeClass.college_id == college_id)
        )
    )
    ac_by_name = {ac.class_name: ac for ac in all_acs}
    ac_by_code = {ac.class_code: ac for ac in all_acs}

    # 读取当前学院所有有效档案供姓名/工号匹配
    all_staff = list(
        db.scalars(
            select(FacultyStaff).where(
                FacultyStaff.school_id == school_id,
                FacultyStaff.college_id == college_id,
            )
        )
    )
    staff_by_no = {s.staff_no: s for s in all_staff}
    staff_by_name: dict[str, list[FacultyStaff]] = {}
    for s in all_staff:
        staff_by_name.setdefault(s.name, []).append(s)

    for idx, raw in enumerate(raw_rows, start=2):
        row_num = int(raw.get("_source_row", idx))
        source_sheet = raw.get("_source_sheet")

        class_text = _clean(
            pick(
                raw,
                "行政班",
                "班级",
                "班级名称",
                "班级代码",
                "class_name",
                "class_code",
                "class",
            )
        )
        if not class_text:
            issues.append(
                _issue("MISSING_CLASS", "行政班不能为空", field="class_name", row=row_num)
            )
            continue

        ac = ac_by_name.get(class_text) or ac_by_code.get(class_text)
        if ac is None:
            issues.append(
                _issue(
                    "CLASS_NOT_FOUND",
                    f"行政班 '{class_text}' 不存在或不在当前学院",
                    field="class_name",
                    row=row_num,
                )
            )
            continue

        # 解析生效与结束日期
        raw_from = _clean(pick(raw, "生效日期", "开始日期", "effective_from"))
        effective_from = _parse_date(raw_from) or today
        raw_to = _clean(pick(raw, "结束日期", "effective_to"))
        effective_to = _parse_date(raw_to)
        if effective_to is not None and effective_to <= effective_from:
            issues.append(
                _issue(
                    "INVALID_DATE_RANGE",
                    f"结束日期 ({effective_to}) 必须大于生效日期 ({effective_from})",
                    row=row_num,
                )
            )
            continue

        duties_to_check = [
            (
                "HEAD_TEACHER",
                _clean(
                    pick(
                        raw,
                        "班主任工号",
                        "班主任号",
                        "head_teacher_staff_no",
                        "head_teacher_no",
                    )
                ),
                _clean(
                    pick(raw, "班主任", "班主任姓名", "head_teacher", "headteacher")
                ),
            ),
            (
                "COUNSELOR",
                _clean(
                    pick(
                        raw,
                        "辅导员工号",
                        "辅导员号",
                        "counselor_staff_no",
                        "counselor_no",
                    )
                ),
                _clean(pick(raw, "辅导员", "辅导员姓名", "counselor")),
            ),
        ]

        for duty, staff_no, staff_name in duties_to_check:
            # 缺行与空责任列不撤销：若工号与姓名均为空，则本职责完全跳过
            if not staff_no and not staff_name:
                continue

            matched_staff: FacultyStaff | None = None
            if staff_no:
                matched_staff = staff_by_no.get(staff_no)
                if matched_staff is None:
                    issues.append(
                        _issue(
                            "STAFF_NOT_FOUND",
                            f"未找到工号为 '{staff_no}' 的有效教职工档案",
                            row=row_num,
                        )
                    )
                    continue
                if matched_staff.status != "ACTIVE":
                    issues.append(
                        _issue(
                            "STAFF_INACTIVE",
                            f"教职工 '{matched_staff.name}' (工号 {staff_no}) 已停用，不能任命",
                            row=row_num,
                        )
                    )
                    continue
                if staff_name and matched_staff.name != staff_name:
                    issues.append(
                        _issue(
                            "STAFF_NAME_MISMATCH",
                            f"工号 '{staff_no}' 对应的档案姓名 '{matched_staff.name}' "
                            f"与文件中的姓名 '{staff_name}' 不符",
                            row=row_num,
                        )
                    )
                    continue
            else:
                # 仅有姓名
                candidates = staff_by_name.get(staff_name, [])
                active_candidates = [s for s in candidates if s.status == "ACTIVE"]
                if not active_candidates:
                    issues.append(
                        _issue(
                            "STAFF_NAME_NOT_FOUND",
                            f"未找到名为 '{staff_name}' 的有效教职工档案，仅有姓名不能授权",
                            row=row_num,
                        )
                    )
                    continue
                if len(active_candidates) > 1:
                    issues.append(
                        _issue(
                            "STAFF_NAME_AMBIGUOUS",
                            f"学院存在多名同名为 '{staff_name}' 的教职工，"
                            "必须提供明确工号以确认任命",
                            row=row_num,
                        )
                    )
                    continue
                matched_staff = active_candidates[0]

            # 查出与该区间重叠的该班职责记录（基线）
            key = f"{ac.class_name}/{duty}"
            incumbent, overlap_count = latest_responsibility(
                StaffRepository(db).overlapping_responsibilities(
                    ac.id, duty, effective_from, effective_to, lock=False
                )
            )
            if overlap_count > 1:
                issues.append(
                    _issue(
                        "MULTIPLE_CURRENT_RESPONSIBILITY",
                        f"行政班 '{ac.class_name}' 的该职责已有 {overlap_count} 条重叠任职，"
                        "无法确定在任者，请先人工核对",
                        row=row_num,
                    )
                )
                continue
            existing_resp = incumbent
            if existing_resp is not None:
                cur_staff = db.get(FacultyStaff, existing_resp.staff_id)
                responsibility_baseline[key] = {
                    "id": existing_resp.id,
                    "staff_id": existing_resp.staff_id,
                    "staff_no": cur_staff.staff_no if cur_staff else "",
                    "staff_name": cur_staff.name if cur_staff else "",
                    "lock_version": existing_resp.lock_version,
                    "effective_from": existing_resp.effective_from.isoformat()
                    if existing_resp.effective_from
                    else None,
                    "effective_to": existing_resp.effective_to.isoformat()
                    if existing_resp.effective_to
                    else None,
                }
                if effective_from < existing_resp.effective_from:
                    issues.append(
                        _issue(
                            "HANDOVER_DATE_INVALID",
                            f"任命生效日期 ({effective_from}) "
                            f"不能早于当前在任起始日期 ({existing_resp.effective_from})",
                            row=row_num,
                        )
                    )
                    continue

            parsed_duties.append(
                {
                    "class_id": ac.id,
                    "class_name": ac.class_name,
                    "duty": duty,
                    "staff_id": matched_staff.id,
                    "staff_no": matched_staff.staff_no,
                    "staff_name": matched_staff.name,
                    "effective_from": effective_from.isoformat() if effective_from else None,
                    "effective_to": effective_to.isoformat() if effective_to else None,
                    "source_row": row_num,
                    "source_sheet": source_sheet,
                }
            )

    summary = {
        "row_total": len(raw_rows),
        "duty_count": len(parsed_duties),
    }
    payload = {
        "duties": parsed_duties,
        "responsibility_baseline": responsibility_baseline,
        "import_type": "class_responsibility",
    }
    return payload, issues, summary


def parse_teaching_assignment(
    db: Session,
    content: bytes,
    semester_id: int,
    college_id: int,
    filename: str | None,
) -> tuple[dict, list[dict], dict]:
    issues: list[dict] = []
    try:
        raw_rows = read_tabular_rows(content, include_source=True)
    except Exception as exc:
        return (
            {"assignments": [], "assignment_baseline": {}, "import_type": "teaching_assignment"},
            [_issue("parse_failed", f"文件解析失败：{exc}")],
            {"row_total": 0, "assignment_count": 0},
        )

    sem = db.get(Semester, semester_id)
    if sem is None:
        return (
            {"assignments": [], "assignment_baseline": {}, "import_type": "teaching_assignment"},
            [_issue("SEMESTER_NOT_FOUND", "指定的学期不存在")],
            {"row_total": 0, "assignment_count": 0},
        )

    school_id = _college(db, college_id).school_id
    default_from = sem.start_date
    default_to = sem.end_date

    # 预加载该学期当前学院的教学班
    all_tcs = list(
        db.scalars(
            select(TeachingClass).where(
                TeachingClass.semester_id == semester_id,
                TeachingClass.college_id == college_id,
            )
        )
    )
    tc_by_code = {tc.class_code: tc for tc in all_tcs}

    # 预加载学校所有有效档案
    all_staff = list(
        db.scalars(
            select(FacultyStaff).where(FacultyStaff.school_id == school_id)
        )
    )
    staff_by_no = {s.staff_no: s for s in all_staff}
    staff_by_name: dict[str, list[FacultyStaff]] = {}
    for s in all_staff:
        staff_by_name.setdefault(s.name, []).append(s)

    parsed_assignments: list[dict] = []
    assignment_baseline: dict[str, dict] = {}
    seen_keys: set[tuple[int, int, str]] = set()

    for idx, raw in enumerate(raw_rows, start=2):
        row_num = int(raw.get("_source_row", idx))
        source_sheet = raw.get("_source_sheet")

        class_code = _clean(
            pick(
                raw,
                "教学班码",
                "教学班",
                "教学班标识",
                "class_code",
                "teaching_class_code",
            )
        )
        if not class_code:
            issues.append(
                _issue("MISSING_CLASS_CODE", "教学班码不能为空", field="class_code", row=row_num)
            )
            continue

        tc = tc_by_code.get(class_code)
        if tc is None:
            issues.append(
                _issue(
                    "TEACHING_CLASS_NOT_FOUND",
                    f"教学班 '{class_code}' 在当前学期及学院中不存在",
                    field="class_code",
                    row=row_num,
                )
            )
            continue

        staff_no = _clean(pick(raw, "教师工号", "工号", "staff_no", "teacher_no"))
        teacher_text = _clean(
            pick(
                raw,
                "任课教师",
                "教师姓名",
                "教师",
                "老师",
                "teacher_name",
                "teacher",
            )
        )
        if not staff_no and not teacher_text:
            issues.append(
                _issue(
                    "MISSING_TEACHER",
                    "必须提供教师工号或教师姓名",
                    row=row_num,
                )
            )
            continue

        raw_from = _clean(pick(raw, "生效日期", "开始日期", "effective_from"))
        effective_from = _parse_date(raw_from) or default_from
        raw_to = _clean(pick(raw, "结束日期", "effective_to"))
        effective_to = _parse_date(raw_to) or default_to
        if effective_to is not None and effective_to <= effective_from:
            issues.append(
                _issue(
                    "INVALID_DATE_RANGE",
                    f"结束日期 ({effective_to}) 必须大于生效日期 ({effective_from})",
                    row=row_num,
                )
            )
            continue

        anchor_input = _clean(pick(raw, "锚点类型", "anchor_type")).upper()
        if anchor_input not in ("", "LOCAL", "SHARED"):
            issues.append(
                _issue(
                    "INVALID_ANCHOR_TYPE",
                    f"锚点类型 '{anchor_input}' 无效，只能是 LOCAL 或 SHARED",
                    field="anchor_type",
                    row=row_num,
                )
            )
            continue
        # 锚点必须显式：留空一律按 LOCAL。教学班恰好挂了共享身份就自动升成 SHARED，
        # 会把只读本班的关系静默放大为跨学院可见范围。
        anchor_type = anchor_input or "LOCAL"
        academic_offering_id: str | None = None
        teaching_class_id: int | None = tc.id

        if anchor_type == "SHARED":
            if tc.academic_offering_id is None:
                issues.append(
                    _issue(
                        "SHARED_OFFERING_NOT_AVAILABLE",
                        f"教学班 '{class_code}' 未关联共享课程身份，无法建立 SHARED 授课关系",
                        row=row_num,
                    )
                )
                continue
            academic_offering_id = tc.academic_offering_id
            teaching_class_id = None

        # 多教师与姓名/工号匹配
        matched_staff_list: list[FacultyStaff] = []
        if staff_no:
            st = staff_by_no.get(staff_no)
            if st is None:
                issues.append(
                    _issue("STAFF_NOT_FOUND", f"未知教师工号：{staff_no}", row=row_num)
                )
                continue
            if st.status != "ACTIVE":
                issues.append(
                    _issue(
                        "STAFF_INACTIVE",
                        f"教师 '{st.name}' (工号 {staff_no}) 已停用，不能授课",
                        row=row_num,
                    )
                )
                continue
            matched_staff_list.append(st)
        else:
            # 仅有教师文本：支持多教师拆分 (逗号、斜杠、顿号、空格)
            names = [
                n.strip()
                for n in re.split(r"[/,，、\s]+", teacher_text)
                if n.strip()
            ]
            has_error = False
            for tname in names:
                cands = staff_by_name.get(tname, [])
                # 优先当前学院，若无则全校
                col_cands = [
                    s for s in cands
                    if s.college_id == college_id and s.status == "ACTIVE"
                ]
                act_cands = col_cands or [s for s in cands if s.status == "ACTIVE"]
                if not act_cands:
                    issues.append(
                        _issue(
                            "TEACHER_NAME_NOT_FOUND",
                            f"未找到任课教师 '{tname}' 的档案，仅有姓名不能自动授权",
                            row=row_num,
                        )
                    )
                    has_error = True
                    break
                if len(act_cands) > 1:
                    issues.append(
                        _issue(
                            "TEACHER_NAME_AMBIGUOUS",
                            f"存在多名同名为 '{tname}' 的教师，无法自动关联授课权限，请提供工号",
                            row=row_num,
                        )
                    )
                    has_error = True
                    break
                matched_staff_list.append(act_cands[0])
            if has_error:
                continue

        # 若是共享课程，查询覆盖的学院视图
        covered_colleges: list[str] = []
        if anchor_type == "SHARED" and academic_offering_id:
            tc_t = TeachingClass.__table__
            cids = list(
                db.scalars(
                    select(tc_t.c.college_id)
                    .where(
                        tc_t.c.academic_offering_id == academic_offering_id,
                        tc_t.c.semester_id == semester_id,
                    )
                    .distinct()
                )
            )
            col_t = College.__table__
            covered_colleges = list(
                db.scalars(select(col_t.c.name).where(col_t.c.id.in_(cids)))
            )

        for st in matched_staff_list:
            dedup_key = (tc.id, st.id, anchor_type)
            if dedup_key in seen_keys:
                issues.append(
                    _issue(
                        "DUPLICATE_ASSIGNMENT",
                        f"文件中对同一教师 '{st.name}' (工号 {st.staff_no}) "
                        f"与教学班 '{class_code}' 存在重复指派",
                        row=row_num,
                    )
                )
                continue
            seen_keys.add(dedup_key)

            key = f"{class_code}/{st.staff_no}"
            # 与新区间重叠的同锚点任命才是本行的对照基线
            overlap = _teaching_overlap(
                StaffRepository(db),
                staff_id=st.id,
                semester_id=semester_id,
                anchor_type=anchor_type,
                teaching_class_id=teaching_class_id,
                academic_offering_id=academic_offering_id,
                start=effective_from,
                end=effective_to,
            )
            duplicates, cross_anchor = _split_conflicts(overlap, anchor_type)
            if duplicates:
                issues.append(
                    _issue(
                        "MULTIPLE_TEACHING_OVERLAP",
                        f"教师 '{st.name}' 在教学班 '{class_code}' 已有 "
                        f"{len(duplicates) + 1} 条重叠任命，无法确定要更新的记录",
                        row=row_num,
                    )
                )
                continue
            if cross_anchor:
                issues.append(
                    _issue(
                        "ANCHOR_OVERLAP",
                        f"教师 '{st.name}' 已以另一锚点覆盖同一共享课程身份，"
                        "请先核对 LOCAL/SHARED 的任职来源",
                        row=row_num,
                    )
                )
                continue
            existing_assign = overlap.same_anchor
            if existing_assign is not None:
                assignment_baseline[key] = {
                    "id": existing_assign.id,
                    "staff_id": existing_assign.staff_id,
                    "staff_no": st.staff_no,
                    "teacher_name": st.name,
                    "anchor_type": existing_assign.anchor_type,
                    "lock_version": existing_assign.lock_version,
                    "effective_from": existing_assign.effective_from.isoformat()
                    if existing_assign.effective_from
                    else None,
                    "effective_to": existing_assign.effective_to.isoformat()
                    if existing_assign.effective_to
                    else None,
                }

            parsed_assignments.append(
                {
                    "class_code": class_code,
                    "teaching_class_id": teaching_class_id,
                    "academic_offering_id": academic_offering_id,
                    "anchor_type": anchor_type,
                    "staff_id": st.id,
                    "staff_no": st.staff_no,
                    "teacher_name": st.name,
                    "effective_from": effective_from.isoformat() if effective_from else None,
                    "effective_to": effective_to.isoformat() if effective_to else None,
                    "covered_colleges": covered_colleges,
                    "source_row": row_num,
                    "source_sheet": source_sheet,
                }
            )

    summary = {
        "row_total": len(raw_rows),
        "assignment_count": len(parsed_assignments),
    }
    payload = {
        "assignments": parsed_assignments,
        "assignment_baseline": assignment_baseline,
        "import_type": "teaching_assignment",
    }
    return payload, issues, summary


def changes_for_staff(service: Any, batch: ImportBatch) -> dict[str, Any]:
    db = service._session
    payload = batch.payload_json or {}
    import_type = payload.get("import_type")
    changes: list[dict] = []
    issues: list[dict] = []

    def issue(message: str, row: int | None = None) -> None:
        issues.append(
            {
                "code": "CONFIRMATION_CONFLICT",
                "severity": "error",
                "message": message,
                "row": row,
                "filename": batch.filename,
            }
        )

    def change(
        action: str,
        entity: str,
        key: str,
        before: dict | None,
        after: dict,
        row: int | None = None,
        sheet: str | None = None,
        column: str | None = None,
        extra: dict | None = None,
    ) -> None:
        entry = {
            "action": action,
            "entity": entity,
            "key": key,
            "before": before,
            "after": after,
            "source": {
                "filename": batch.filename,
                "row": row,
                "sheet": sheet,
                "column": column,
            },
        }
        if extra:
            entry.update(extra)
        changes.append(entry)

    school_id = _college(db, batch.college_id).school_id

    if import_type == "faculty_staff":
        baseline = payload.get("staff_baseline", {})
        for r in payload.get("rows", []):
            sno = r["staff_no"]
            cur = db.scalar(
                select(FacultyStaff).where(
                    FacultyStaff.school_id == school_id,
                    FacultyStaff.staff_no == sno,
                )
            )
            base = baseline.get(sno)
            if (base is None and cur is not None) or (
                base is not None
                and (cur is None or cur.lock_version != base["lock_version"])
            ):
                issue(
                    f"教职工 '{sno}' 档案版本在预览后已变化，请重新核对上传",
                    r.get("source_row"),
                )

            before = (
                {
                    "name": base["name"],
                    "phone": base.get("phone"),
                    "status": base["status"],
                }
                if base
                else None
            )
            after = {
                "name": r["name"],
                "phone": r.get("phone"),
                "status": r.get("status", "ACTIVE"),
            }
            action = (
                "CREATE"
                if base is None
                else "UNCHANGED"
                if before == after
                else "UPDATE"
            )
            change(
                action,
                "faculty_staff",
                sno,
                before,
                after,
                r.get("source_row"),
                r.get("source_sheet"),
            )

    elif import_type == "class_responsibility":
        baseline = payload.get("responsibility_baseline", {})
        for d in payload.get("duties", []):
            key = f"{d['class_name']}/{d['duty']}"
            base = baseline.get(key)
            # 核对预览选中的同一条记录，而不是重新任取一条
            if base is not None:
                cur = db.get(ClassStaffResponsibility, base["id"])
            else:
                incumbent, _candidates = latest_responsibility(
                    StaffRepository(db).overlapping_responsibilities(
                        d["class_id"],
                        d["duty"],
                        _parse_date(d["effective_from"]) or business_today(),
                        _parse_date(d.get("effective_to")),
                        lock=False,
                    )
                )
                cur = incumbent
            if (base is None and cur is not None) or (
                base is not None
                and (cur is None or cur.lock_version != base["lock_version"])
            ):
                issue(
                    f"行政班 '{d['class_name']}' 的责任关系在预览后已变化，请重新核对上传",
                    d.get("source_row"),
                )

            before = (
                {
                    "staff_no": base["staff_no"],
                    "staff_name": base["staff_name"],
                    "effective_from": str(base["effective_from"]),
                    "effective_to": str(base["effective_to"])
                    if base.get("effective_to")
                    else None,
                }
                if base
                else None
            )
            after = {
                "staff_no": d["staff_no"],
                "staff_name": d["staff_name"],
                "effective_from": str(d["effective_from"]),
                "effective_to": str(d["effective_to"]) if d.get("effective_to") else None,
            }
            action = (
                "CREATE"
                if base is None
                else "UNCHANGED"
                if before == after
                else "UPDATE"
            )
            change(
                action,
                "class_responsibility",
                key,
                before,
                after,
                d.get("source_row"),
                d.get("source_sheet"),
            )

    elif import_type == "teaching_assignment":
        baseline = payload.get("assignment_baseline", {})
        for a in payload.get("assignments", []):
            key = f"{a['class_code']}/{a['staff_no']}"
            base = baseline.get(key)
            if base is not None:
                cur = db.get(TeachingStaffAssignment, base["id"])
            else:
                cur = _teaching_overlap(
                    StaffRepository(db),
                    staff_id=a["staff_id"],
                    semester_id=_require_semester(batch),
                    anchor_type=a["anchor_type"],
                    teaching_class_id=a.get("teaching_class_id"),
                    academic_offering_id=a.get("academic_offering_id"),
                    start=_parse_date(a["effective_from"]) or business_today(),
                    end=_parse_date(a.get("effective_to")),
                ).same_anchor
            if (base is None and cur is not None) or (
                base is not None
                and (cur is None or cur.lock_version != base["lock_version"])
            ):
                issue(
                    f"教学班 '{a['class_code']}' 教师 '{a['staff_no']}' "
                    "授课指派已发生变化，请重新核对",
                    a.get("source_row"),
                )

            before = (
                {
                    "staff_no": base["staff_no"],
                    "teacher_name": base["teacher_name"],
                    "anchor_type": base["anchor_type"],
                    "effective_from": str(base["effective_from"]),
                    "effective_to": str(base["effective_to"])
                    if base.get("effective_to")
                    else None,
                }
                if base
                else None
            )
            after = {
                "staff_no": a["staff_no"],
                "teacher_name": a["teacher_name"],
                "anchor_type": a["anchor_type"],
                "effective_from": str(a["effective_from"]),
                "effective_to": str(a["effective_to"]) if a.get("effective_to") else None,
            }
            action = (
                "CREATE"
                if base is None
                else "UNCHANGED"
                if before == after
                else "UPDATE"
            )
            extra = {}
            if a.get("covered_colleges"):
                extra["covered_colleges"] = a["covered_colleges"]
            change(
                action,
                "teaching_assignment",
                key,
                before,
                after,
                a.get("source_row"),
                a.get("source_sheet"),
                extra=extra,
            )

    if changes and all(c["action"] == "UNCHANGED" for c in changes):
        payload["confirmation_skip"] = True

    return {"changes": changes, "issues": issues, "payload": payload}


def apply_faculty_staff(
    db: Session,
    actor: CurrentUser,
    batch: ImportBatch,
    payload: dict,
    request_id: str | None,
) -> dict[str, int]:
    school_id = _college(db, batch.college_id).school_id
    baseline = payload.get("staff_baseline", {})

    created = 0
    updated = 0

    for r in payload.get("rows", []):
        sno = r["staff_no"]
        existing = db.scalar(
            select(FacultyStaff).where(
                FacultyStaff.school_id == school_id,
                FacultyStaff.staff_no == sno,
            )
        )
        base = baseline.get(sno)
        if (base is None and existing is not None) or (
            base is not None
            and (existing is None or existing.lock_version != base["lock_version"])
        ):
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"教职工 '{sno}' 档案版本已变化，整批未保存",
            )

        if existing is None:
            new_staff = FacultyStaff(
                school_id=school_id,
                college_id=batch.college_id,
                staff_no=sno,
                name=r["name"],
                phone=r.get("phone"),
                status=r.get("status", "ACTIVE"),
                lock_version=1,
            )
            db.add(new_staff)
            created += 1
        else:
            changed = False
            if existing.name != r["name"]:
                existing.name = r["name"]
                changed = True
            if (existing.phone or None) != (r.get("phone") or None):
                existing.phone = r.get("phone")
                changed = True
            if existing.status != r.get("status", "ACTIVE"):
                existing.status = r.get("status", "ACTIVE")
                changed = True
            if changed:
                existing.lock_version += 1
                updated += 1

    db.flush()
    return {"created": created, "updated": updated}


def apply_class_responsibility(
    db: Session,
    actor: CurrentUser,
    batch: ImportBatch,
    payload: dict,
    request_id: str | None,
) -> dict[str, int]:
    baseline = payload.get("responsibility_baseline", {})
    created = 0
    updated = 0

    for d in payload.get("duties", []):
        key = f"{d['class_name']}/{d['duty']}"
        base = baseline.get(key)
        eff_from = _parse_date(d["effective_from"]) or business_today()
        eff_to = _parse_date(d.get("effective_to"))
        rows = StaffRepository(db).overlapping_responsibilities(
            d["class_id"], d["duty"], eff_from, eff_to
        )
        cur, candidates = latest_responsibility(rows)
        if candidates > 1:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"行政班 '{d['class_name']}' 该职责存在重叠任职，无法确定在任者，整批未保存",
            )
        if base is None:
            if cur is not None:
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT,
                    f"行政班 '{d['class_name']}' 在预览后出现新的任职记录，整批未保存",
                )
        elif cur is None or cur.id != base["id"]:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"行政班 '{d['class_name']}' 责任关系在预览后已变化，整批未保存",
            )
        elif cur.lock_version != base["lock_version"]:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"行政班 '{d['class_name']}' 责任关系版本已变化，整批未保存",
            )

        if cur is None:
            new_resp = ClassStaffResponsibility(
                staff_id=d["staff_id"],
                administrative_class_id=d["class_id"],
                duty=d["duty"],
                effective_from=eff_from,
                effective_to=eff_to,
                lock_version=1,
            )
            db.add(new_resp)
            created += 1
        else:
            if cur.staff_id != d["staff_id"]:
                # 交接：旧关系在 eff_from 结束，新关系在 eff_from 开始
                if not handover_start_allowed(cur.effective_from, eff_from):
                    raise ConflictError(
                        ErrorCode.VERSION_CONFLICT,
                        "交接生效日期必须晚于在任起始日期，整批未保存",
                    )
                cur.effective_to = eff_from
                cur.lock_version += 1
                new_resp = ClassStaffResponsibility(
                    staff_id=d["staff_id"],
                    administrative_class_id=d["class_id"],
                    duty=d["duty"],
                    effective_from=eff_from,
                    effective_to=eff_to,
                    lock_version=1,
                )
                db.add(new_resp)
                created += 1
                updated += 1
            else:
                # 相同人员，更新日期
                changed = False
                if cur.effective_from != eff_from:
                    cur.effective_from = eff_from
                    changed = True
                if cur.effective_to != eff_to:
                    cur.effective_to = eff_to
                    changed = True
                if changed:
                    cur.lock_version += 1
                    updated += 1

    db.flush()
    return {"created": created, "updated": updated}


def apply_teaching_assignment(
    db: Session,
    actor: CurrentUser,
    batch: ImportBatch,
    payload: dict,
    request_id: str | None,
) -> dict[str, int]:
    baseline = payload.get("assignment_baseline", {})
    created = 0
    updated = 0
    repo = StaffRepository(db)
    semester_id = _require_semester(batch)

    for a in payload.get("assignments", []):
        key = f"{a['class_code']}/{a['staff_no']}"
        base = baseline.get(key)
        eff_from = _parse_date(a["effective_from"]) or business_today()
        eff_to = _parse_date(a.get("effective_to"))
        # 串行点与院级管理接口一致：先锁本人档案，再判定重叠，避免同名双写。
        repo.lock_profile(a["staff_id"])
        overlap = _teaching_overlap(
            repo,
            staff_id=a["staff_id"],
            semester_id=semester_id,
            anchor_type=a["anchor_type"],
            teaching_class_id=a.get("teaching_class_id"),
            academic_offering_id=a.get("academic_offering_id"),
            start=eff_from,
            end=eff_to,
        )
        duplicates, cross_anchor = _split_conflicts(overlap, a["anchor_type"])
        if duplicates:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"教学班 '{a['class_code']}' 教师授课关系存在重叠任命，整批未保存",
            )
        if cross_anchor:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"教师 '{a['staff_no']}' 已以另一锚点覆盖同一共享课程，整批未保存",
            )
        cur = overlap.same_anchor
        if base is None:
            if cur is not None:
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT,
                    f"教学班 '{a['class_code']}' 在预览后出现新的任命，整批未保存",
                )
        elif cur is None or cur.id != base["id"]:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"教学班 '{a['class_code']}' 教师授课关系在预览后已变化，整批未保存",
            )
        elif cur.lock_version != base["lock_version"]:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                f"教学班 '{a['class_code']}' 教师授课关系版本已变化，整批未保存",
            )

        if cur is None:
            new_assign = TeachingStaffAssignment(
                staff_id=a["staff_id"],
                semester_id=semester_id,
                anchor_type=a["anchor_type"],
                teaching_class_id=a.get("teaching_class_id"),
                academic_offering_id=a.get("academic_offering_id"),
                effective_from=eff_from,
                effective_to=eff_to,
                lock_version=1,
            )
            db.add(new_assign)
            created += 1
        else:
            changed = False
            if cur.effective_from != eff_from:
                cur.effective_from = eff_from
                changed = True
            if cur.effective_to != eff_to:
                cur.effective_to = eff_to
                changed = True
            if changed:
                cur.lock_version += 1
                updated += 1

    db.flush()
    return {"created": created, "updated": updated}


def apply_staff(
    db: Session,
    actor: CurrentUser,
    batch: ImportBatch,
    payload: dict,
    request_id: str | None,
) -> dict:
    try:
        return _apply_staff_inner(db, actor, batch, payload, request_id)
    except IntegrityError as exc:
        # 约束冲突（唯一工号、锚点 CHECK、任职区间、外键）一律 409，不暴露成 500。
        raise ConflictError(
            ErrorCode.VERSION_CONFLICT, "教职工资料违反唯一性或区间约束，整批未保存"
        ) from exc


def _apply_staff_inner(
    db: Session,
    actor: CurrentUser,
    batch: ImportBatch,
    payload: dict,
    request_id: str | None,
) -> dict:
    import_type = payload.get("import_type")
    if import_type == "faculty_staff":
        return apply_faculty_staff(db, actor, batch, payload, request_id)
    if import_type == "class_responsibility":
        return apply_class_responsibility(db, actor, batch, payload, request_id)
    if import_type == "teaching_assignment":
        return apply_teaching_assignment(db, actor, batch, payload, request_id)
    return {}
