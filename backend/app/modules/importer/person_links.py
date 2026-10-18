"""把导入的人员文字解析为稳定档案关系；不以姓名绑定登录账号。

同名/缺档案/既有职责冲突是可见的待办，不阻断教务资料本身。仅补建缺失关系，
换人和改变既有有效期仍走明确的交接流程，避免重导旧表恢复已撤销的历史权限。
"""

import hashlib
import re
from datetime import timedelta

from sqlalchemy import or_, select

from app.common.parsing.grid import normalize_class_name
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.academic.models import AdministrativeClass, Course, Semester, TeachingClass
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.academic.staff_repository import StaffRepository, interval_overlaps
from app.modules.audit.models import AuditLog
from app.modules.identity.role_scope import business_today
from app.modules.organization.models import College

TARGETS = {"timetable", "grid_timetable", "admin_roster"}


def match_staff(profiles, name, number=""):
    """工号优先且姓名须一致；无工号时不以本院优先掩盖跨院同名。"""
    if number:
        candidates = [s for s in profiles if s.staff_no == number]
    else:
        candidates = [s for s in profiles if s.name == name and s.status == "ACTIVE"]
    if len(candidates) != 1:
        return None, "存在同名教职工，请补充工号" if len(
            candidates
        ) > 1 else "未找到有效教职工档案，请先补录档案"
    staff = candidates[0]
    if staff.status != "ACTIVE":
        return None, "教职工档案已停用"
    if number and name and staff.name != name:
        return None, "工号与姓名不一致，请核对原表"
    return staff, None


def source_facts(db, cid):
    """只返回参与指纹的数据，不对外泄露全校人员名单。"""
    school = db.scalar(select(College.school_id).where(College.id == cid))
    classes = select(AdministrativeClass.id).where(AdministrativeClass.college_id == cid)
    teaching = select(TeachingClass.id).where(TeachingClass.college_id == cid)
    offerings = select(TeachingClass.academic_offering_id).where(TeachingClass.college_id == cid)
    queries = [
        select(FacultyStaff).where(FacultyStaff.school_id == school),
        select(ClassStaffResponsibility).where(
            ClassStaffResponsibility.administrative_class_id.in_(classes)
        ),
        select(TeachingStaffAssignment).where(
            or_(
                TeachingStaffAssignment.teaching_class_id.in_(teaching),
                TeachingStaffAssignment.academic_offering_id.in_(offerings),
            )
        ),
    ]
    return [
        [
            [getattr(row, col.name) for col in row.__table__.columns]
            for row in db.scalars(
                query.order_by(query.column_descriptions[0]["entity"].id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ]
        for query in queries
    ]


def _resources(service, target, payload, semester_id):
    db, cid = service._session, service.cid
    if target == "admin_roster":
        result = {}
        class_cache = {}
        for row in [*payload.get("students", []), *payload.get("class_duties", [])]:
            for field, duty in (("head_teacher", "HEAD_TEACHER"), ("counselor", "COUNSELOR")):
                name, number = row.get(field) or "", row.get(f"{field}_staff_no") or ""
                if name or number:
                    if row["class_name"] not in class_cache:
                        class_cache[row["class_name"]] = _admin_class(db, cid, row["class_name"])
                    ac = class_cache[row["class_name"]]
                    class_name = ac.class_name if ac else normalize_class_name(row["class_name"])
                    key = (class_name, duty, name, number)
                    result[key] = {
                        "kind": "responsibility",
                        "class_name": class_name,
                        "duty": duty,
                        "name": name,
                        "staff_no": number,
                    }
        return list(result.values())
    rows = payload.get("courses" if target == "grid_timetable" else "rows", [])
    resources = []
    for row in rows:
        course_code, class_code = row.get("course_code"), row.get("class_code")
        if target == "grid_timetable":
            ac = _admin_class(db, cid, payload.get("class_name", ""))
            if ac is None:
                continue  # 正式资料差异已报告缺少行政班，不能另猜目标。
            course = db.scalar(select(Course).where(Course.course_name == row["course_name"]))
            course_code = (
                course.course_code
                if course
                else "C_" + hashlib.md5(row["course_name"].encode()).hexdigest()[:8].upper()
            )
            class_code = f"{ac.class_code}_{course_code}"
        names = [
            n.strip() for n in re.split(r"[/,，、;；\s]+", row.get("teacher") or "") if n.strip()
        ]
        numbers = [
            n.strip()
            for n in re.split(r"[/,，、;；\s]+", row.get("teacher_staff_no") or "")
            if n.strip()
        ]
        # 多教师工号与姓名必须逐项对应，不能把一个工号猜配多个姓名。
        if numbers and names and len(numbers) != len(names):
            resources.append(
                {
                    "kind": "teaching",
                    "class_code": class_code,
                    "course_code": course_code,
                    "name": row.get("teacher") or "",
                    "problem": "教师工号与姓名数量不一致",
                }
            )
            continue
        for index in range(max(len(names), len(numbers), 1)):
            resources.append(
                {
                    "kind": "teaching",
                    "class_code": class_code,
                    "course_code": course_code,
                    "name": names[index] if index < len(names) else "",
                    "staff_no": numbers[index] if index < len(numbers) else "",
                }
            )
    return list({str(sorted(r.items())): r for r in resources}.values())


def _admin_class(db, cid, name):
    rows = list(
        db.scalars(select(AdministrativeClass).where(AdministrativeClass.college_id == cid))
    )
    matches = [
        r
        for r in rows
        if r.class_code == name or normalize_class_name(r.class_name) == normalize_class_name(name)
    ]
    return matches[0] if len(matches) == 1 else None


def _teaching_class(db, cid, sid, resource):
    return db.scalar(
        select(TeachingClass)
        .join(Course, Course.id == TeachingClass.course_id)
        .where(
            TeachingClass.college_id == cid,
            TeachingClass.semester_id == sid,
            TeachingClass.class_code == resource["class_code"],
            Course.course_code == resource["course_code"],
        )
    )


def plan_links(service, target, payload, semester_id):
    if target not in TARGETS or not getattr(service, "cid", None):
        return {"links": [], "pending": []}
    db, cid = service._session, service.cid
    school_id = db.scalar(select(College.school_id).where(College.id == cid))
    profiles = list(
        db.scalars(
            select(FacultyStaff)
            .where(FacultyStaff.school_id == school_id)
            .execution_options(populate_existing=True)
        )
    )
    semester = db.get(Semester, semester_id) if semester_id else None
    today = business_today()
    start = max(today, semester.start_date) if semester else today
    end = semester.end_date + timedelta(days=1) if semester else None
    try:
        service._require(service.actor.id, "staff.manage")
        can_manage = True
    except PermissionDeniedError:
        can_manage = False
    plan = {"links": [], "pending": []}
    resources = _resources(service, target, payload, semester_id)
    resolved = {
        (r.get("name", ""), r.get("staff_no", "")): match_staff(
            profiles, r.get("name", ""), r.get("staff_no", "")
        )
        for r in resources
    }
    for resource in resources:
        row = {
            **resource,
            "effective_from": start.isoformat(),
            "effective_to": end.isoformat() if end else None,
        }
        staff, problem = resolved[(row.get("name", ""), row.get("staff_no", ""))]
        problem = row.get("problem") or problem
        if not row.get("name") and not row.get("staff_no"):
            problem = "课表未提供任课教师，请补充教师信息"
        if not can_manage:
            problem = "当前账号可导入资料，但需由有教职工管理权限的人员确认关联"
        if semester and (semester.status != "ACTIVE" or start >= end):
            problem = "该学期已结束或已归档，不自动补建历史授课权限"
        if problem:
            plan["pending"].append({**row, "message": problem})
            continue
        if row["kind"] == "responsibility" and staff.college_id != cid:
            plan["pending"].append({**row, "message": "责任人档案不属于本院，请先明确院内责任安排"})
            continue
        if (
            row["kind"] == "responsibility"
            and len(
                {
                    (r.get("staff_no"), r.get("name"))
                    for r in resources
                    if r["kind"] == "responsibility"
                    and r["class_name"] == row["class_name"]
                    and r["duty"] == row["duty"]
                }
            )
            > 1
        ):
            plan["pending"].append(
                {**row, "message": "同一行政班同一职责填写了不同人员，请核对责任表"}
            )
            continue
        row.update(staff_id=str(staff.id), staff_no=staff.staff_no, name=staff.name)
        if row["kind"] == "teaching":
            tc = _teaching_class(db, cid, semester_id, row)
            existing = []
            if tc:
                from app.modules.importer.staff_adapter import _teaching_overlap

                overlap = _teaching_overlap(
                    StaffRepository(db),
                    staff_id=staff.id,
                    semester_id=semester_id,
                    anchor_type="LOCAL",
                    teaching_class_id=tc.id,
                    academic_offering_id=None,
                    start=start,
                    end=end,
                )
                existing = ([overlap.same_anchor] if overlap.same_anchor else []) + list(
                    overlap.conflicts
                )
                # 其他教师已有任职，而导入文字不包含他时，不用重导完成隐式换人。
                teacher_ids = {
                    s.id
                    for r in resources
                    if r.get("class_code") == row["class_code"]
                    and r.get("course_code") == row["course_code"]
                    for s, error in [
                        resolved[(r.get("name", ""), r.get("staff_no", ""))]
                    ]
                    if s is not None and error is None
                }
                other = db.scalar(
                    select(TeachingStaffAssignment.id).where(
                        TeachingStaffAssignment.teaching_class_id == tc.id,
                        TeachingStaffAssignment.staff_id.not_in(teacher_ids),
                        interval_overlaps(TeachingStaffAssignment, start, end),
                    )
                )
                if other:
                    problem = "该教学班已有其他授课教师，请先核对并明确调整授课关系"
        else:
            ac = _admin_class(db, cid, row["class_name"])
            existing = (
                list(
                    db.scalars(
                        select(ClassStaffResponsibility).where(
                            ClassStaffResponsibility.administrative_class_id == ac.id,
                            ClassStaffResponsibility.duty == row["duty"],
                            interval_overlaps(ClassStaffResponsibility, start, end),
                        )
                    )
                )
                if ac
                else []
            )
        if existing and not (
            len(existing) == 1
            and existing[0].staff_id == staff.id
            and existing[0].effective_from <= start
            and (
                existing[0].effective_to is None
                or end is not None
                and existing[0].effective_to >= end
            )
        ):
            problem = "已有任职关系或有效期不同，请通过交接或人工调整，不能由重导覆盖"
        # 不恢复曾明确结束的同一资源关系。
        if not existing:
            if row["kind"] == "teaching" and tc:
                ended = db.scalar(
                    select(TeachingStaffAssignment.id).where(
                        TeachingStaffAssignment.staff_id == staff.id,
                        TeachingStaffAssignment.teaching_class_id == tc.id,
                    )
                )
            elif row["kind"] == "responsibility" and ac:
                ended = db.scalar(
                    select(ClassStaffResponsibility.id).where(
                        ClassStaffResponsibility.administrative_class_id == ac.id,
                        ClassStaffResponsibility.duty == row["duty"],
                    )
                )
            else:
                ended = None
            if ended:
                problem = "该资源已有结束的任职记录，请明确重新安排，不从旧表恢复权限"
        if problem:
            plan["pending"].append({**row, "message": problem})
        else:
            plan["links"].append({**row, "action": "UNCHANGED" if existing else "CREATE"})
    return plan


def summary(plan):
    return {
        "person_links_create": sum(r["action"] == "CREATE" for r in plan["links"]),
        "person_links_existing": sum(r["action"] == "UNCHANGED" for r in plan["links"]),
        "person_links_pending": len(plan["pending"]),
    }


def apply_links(service, plan, semester_id, request_id):
    db, created = service._session, 0
    for row in plan["links"]:
        if row["action"] != "CREATE":
            continue
        service._require(service.actor.id, "staff.manage")
        StaffRepository(db).lock_profile(int(row["staff_id"]))
        from datetime import date

        start = date.fromisoformat(row["effective_from"])
        end = date.fromisoformat(row["effective_to"]) if row["effective_to"] else None
        common = {
            "staff_id": int(row["staff_id"]),
            "effective_from": start,
            "effective_to": end,
            "lock_version": 1,
        }
        if row["kind"] == "teaching":
            tc = _teaching_class(db, service.cid, semester_id, row)
            if tc is None or tc.status != "ACTIVE":
                raise ConflictError(message="目标教学班不存在或已停用，关联未保存")
            if not tc.teacher_name:
                tc.teacher_name = "、".join(
                    dict.fromkeys(
                        r["name"]
                        for r in plan["links"]
                        if r["kind"] == "teaching"
                        and r["class_code"] == row["class_code"]
                        and r["course_code"] == row["course_code"]
                    )
                )
            relation = TeachingStaffAssignment(
                **common, semester_id=semester_id, anchor_type="LOCAL", teaching_class_id=tc.id
            )
        else:
            ac = _admin_class(db, service.cid, row["class_name"])
            if ac is None or ac.status != "ACTIVE":
                raise ConflictError(message="目标行政班不存在或已停用，关联未保存")
            setattr(
                ac, "head_teacher" if row["duty"] == "HEAD_TEACHER" else "counselor", row["name"]
            )
            relation = ClassStaffResponsibility(
                **common, administrative_class_id=ac.id, duty=row["duty"]
            )
        # 同一确认集合可能有多个文件包含同一关系，已写入的关系不得重复建。
        model = type(relation)
        target = (
            (model.teaching_class_id == relation.teaching_class_id)
            if row["kind"] == "teaching"
            else (
                (model.administrative_class_id == relation.administrative_class_id)
                & (model.duty == relation.duty)
            )
        )
        existing = list(
            db.scalars(select(model).where(target, interval_overlaps(model, start, end)))
        )
        if any(
            r.staff_id == relation.staff_id
            and r.effective_from <= start
            and (r.effective_to is None or end is not None and r.effective_to >= end)
            for r in existing
        ):
            continue
        if existing and row["kind"] == "responsibility":
            raise ConflictError(message="责任人员关系已变化，请重新核对")
        db.add(relation)
        db.flush()
        db.add(
            AuditLog(
                actor_user_id=service.actor.id,
                action="staff.relation.auto_link",
                resource_type=model.__tablename__,
                resource_id=str(relation.id),
                after_json={**row, "college_id": str(service.cid)},
                request_id=request_id,
            )
        )
        created += 1
    db.flush()
    return {"person_links_created": created, "person_links_pending": len(plan["pending"])}
