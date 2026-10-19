"""后台核对人员来源后建立临时档案；不按姓名绑定账号，不分配 Web 凭据。

每条来源单独核对，person_key 是操作人明确指定的同一人分组。原始来源和人员/任职
修订参与指纹；学院锁与幂等审计保证重复确认不重复建档。所有写入同事务完成。
"""

import hashlib
import json
import re

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.academic.staff_models import FacultyStaff
from app.modules.audit.models import AuditLog
from app.modules.identity.role_scope import business_today
from app.modules.importer.person_links import _resources, apply_links, plan_links
from app.modules.importer.person_reconciliation import PersonLinkReconciliation
from app.modules.organization.models import College, School


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class StaffOnboarding:
    def __init__(self, service):
        self.service = service
        self.db = service._session

    def _plan(self, semester_id, responsibility_payload):
        reconciler = PersonLinkReconciliation(self.service)
        resources = []
        if semester_id is not None:
            target, payload = reconciler.source_payload("teaching", semester_id)
            resources.extend(_resources(self.service, target, payload, semester_id))
        target, payload = reconciler.source_payload("responsibility", None)
        resources.extend(_resources(self.service, target, payload, None))
        if responsibility_payload:
            for duty in responsibility_payload.get("class_duties", []):
                resources.extend(
                    {
                        **r,
                        "source_file": responsibility_payload.get("source_file"),
                        "source_row": duty.get("source_row"),
                        "source_sheet": duty.get("source_sheet"),
                    }
                    for r in _resources(
                        self.service, "admin_roster", {"class_duties": [duty]}, None
                    )
                )
        candidates = sorted(
            {digest(r): {**r, "key": digest(r)} for r in resources}.values(),
            key=lambda r: r["key"],
        )
        if len(candidates) > get_settings().import_max_rows:
            raise ConflictError(message="候选过多，请按学院、学期分批核对")
        college = self.db.get(College, self.service.cid)
        profiles = list(
            self.db.scalars(select(FacultyStaff).where(FacultyStaff.school_id == college.school_id))
        )
        for row in candidates:
            row["matches"] = [
                {
                    "staff_id": str(s.id),
                    "college_id": str(s.college_id),
                    "staff_no": s.staff_no,
                    "status": s.status,
                }
                for s in profiles
                if s.name == row.get("name")
            ]
        result = {
            "college_id": str(self.service.cid),
            "actor_id": str(self.service.actor.id),
            "semester_id": str(semester_id) if semester_id else None,
            "date": str(business_today()),
            "candidates": candidates,
            "source_revision": self.service.source_revision(),
        }
        return {**result, "revision": digest(result)}

    def preview(self, semester_id=None, responsibility_payload=None):
        with self.service.operation("staff.manage"):
            return self._plan(semester_id, responsibility_payload)

    def confirm(self, plan, decisions, responsibility_payload=None):
        try:
            return self._confirm(plan, decisions, responsibility_payload)
        except Exception:
            self.db.rollback()
            raise

    def _confirm(self, plan, decisions, responsibility_payload):
        with self.service.operation("staff.manage"):
            college = self.db.get(College, self.service.cid)
            # 序列化同校临时编号分配和重复确认；不与既有登录账号发生自动关联。
            self.db.execute(
                select(School.id).where(School.id == college.school_id).with_for_update()
            ).all()
            operation_id = digest({"plan": plan, "decisions": decisions})
            receipt = self.db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "staff.onboarding.confirm",
                    AuditLog.resource_id == operation_id,
                    AuditLog.actor_user_id == self.service.actor.id,
                )
            )
            if receipt:
                return receipt.after_json
            semester_id = int(plan["semester_id"]) if plan.get("semester_id") else None
            fresh = self._plan(semester_id, responsibility_payload)
            if fresh != plan:
                raise ConflictError(message="来源、人员或任职已变化，请重新提取核对")
            by_key = {r["key"]: r for r in decisions}
            if len(by_key) != len(decisions) or set(by_key) != {
                r["key"] for r in plan["candidates"]
            }:
                raise ConflictError(message="每条候选必须且只能核对一次（CREATE/LINK/SKIP）")
            selected, people, roster = [], {}, {}
            for source in plan["candidates"]:
                choice = by_key[source["key"]]
                if choice.get("action") == "SKIP":
                    continue
                if not source.get("name") or source.get("problem"):
                    raise ConflictError(message="来源姓名缺失或格式冲突，请修正原始资料")
                if choice.get("action") == "CREATE":
                    if str(choice.get("home_college_id")) != str(self.service.cid):
                        raise ConflictError(
                            message="新建前必须明确确认归属本院；跨院人员先在归属学院建档"
                        )
                    key = str(choice.get("person_key") or "").strip()
                    if not key or len(key) > 128 or source.get("staff_no"):
                        raise ConflictError(
                            message="新建需要明确 person_key，已有工号须关联已有档案"
                        )
                    matching_ids = {r["staff_id"] for r in source["matches"]}
                    if (
                        matching_ids
                        and set(choice.get("distinct_from_staff_ids", [])) != matching_ids
                    ):
                        raise ConflictError(
                            message="存在同名档案；请 LINK，或逐个明确确认是不同人员后再新建"
                        )
                    if key not in people:
                        number = f"TMP_PENDING_{digest([operation_id, key])[:24].upper()}"
                        existing = self.db.scalar(
                            select(FacultyStaff)
                            .where(
                                FacultyStaff.school_id == college.school_id,
                                or_(
                                    FacultyStaff.staff_no == number,
                                    FacultyStaff.temporary_staff_no == number,
                                ),
                            )
                            .with_for_update()
                        )
                        if existing:
                            raise ConflictError(
                                message="人员分组已被使用，请重新提取并关联已有档案"
                            )
                        staff = FacultyStaff(
                            school_id=college.school_id,
                            college_id=self.service.cid,
                            name=source["name"],
                            staff_no=number,
                            temporary_staff_no=number,
                            status="ACTIVE",
                            lock_version=1,
                        )
                        self.db.add(staff)
                        self.db.flush()
                        # 主键取得后生成便于人工输入的短号，暂存编号不会提交到库中。
                        number = f"TMP_{college.school_id}_{staff.id:06d}"
                        occupied = self.db.scalar(
                            select(FacultyStaff.id).where(
                                FacultyStaff.school_id == college.school_id,
                                or_(
                                    FacultyStaff.staff_no == number,
                                    FacultyStaff.temporary_staff_no == number,
                                ),
                            )
                        )
                        if occupied:
                            raise ConflictError(message="临时工号与历史档案冲突，请人工核对")
                        staff.staff_no = number
                        staff.temporary_staff_no = number
                        self.db.flush()
                        self.db.add(
                            AuditLog(
                                actor_user_id=self.service.actor.id,
                                action="staff.onboarding.create",
                                resource_type="faculty_staff",
                                resource_id=str(staff.id),
                                after_json={
                                    "college_id": str(staff.college_id),
                                    "source_key": source["key"],
                                    "staff_no": number,
                                },
                            )
                        )
                        people[key] = staff
                    staff = people[key]
                elif choice.get("action") == "LINK":
                    staff = self.db.scalar(
                        select(FacultyStaff)
                        .where(
                            FacultyStaff.id == int(choice["staff_id"]),
                            FacultyStaff.school_id == college.school_id,
                        )
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                else:
                    raise ConflictError(message="未知核对动作，必须明确 CREATE/LINK/SKIP")
                if staff is None or staff.status != "ACTIVE" or staff.name != source["name"]:
                    raise ConflictError(message="指定档案不存在、已停用或姓名不一致")
                if source.get("staff_no") and source["staff_no"] != staff.staff_no:
                    raise ConflictError(message="来源工号与指定档案不一致")
                if source["kind"] == "responsibility" and staff.college_id != self.service.cid:
                    raise ConflictError(message="班级责任人必须是本院档案，不能推断跨院归属")
                selected.append({**source, "staff_no": staff.staff_no})
                roster[str(staff.id)] = {
                    "staff_id": str(staff.id),
                    "college_id": str(staff.college_id),
                    "name": staff.name,
                    "staff_no": staff.staff_no,
                    "temporary_staff_no": staff.temporary_staff_no,
                }
            payloads = {"timetable": {"rows": []}, "admin_roster": {"class_duties": []}}
            for row in selected:
                if row["kind"] == "teaching":
                    payloads["timetable"]["rows"].append(
                        {
                            "class_code": row["class_code"],
                            "course_code": row["course_code"],
                            "teacher": row["name"],
                            "teacher_staff_no": row["staff_no"],
                        }
                    )
                else:
                    field = "head_teacher" if row["duty"] == "HEAD_TEACHER" else "counselor"
                    payloads["admin_roster"]["class_duties"].append(
                        {
                            "class_name": row["class_name"],
                            field: row["name"],
                            f"{field}_staff_no": row["staff_no"],
                        }
                    )
            created = 0
            # 两类全部先规划再写入；任一冲突使本次新档案与任职一起回滚。
            plans = [
                (
                    target,
                    plan_links(
                        self.service,
                        target,
                        payload,
                        semester_id if target == "timetable" else None,
                    ),
                )
                for target, payload in payloads.items()
            ]
            for _, relations in plans:
                if relations["pending"]:
                    raise ConflictError(
                        message="任职关系存在冲突，请修正或明确跳过对应来源："
                        + relations["pending"][0]["message"]
                    )
            for target, relations in plans:
                created += apply_links(
                    self.service, relations, semester_id if target == "timetable" else None, None
                )["person_links_created"]
            result = {
                "staff": list(roster.values()),
                "person_links_created": created,
                "skipped": sum(r["action"] == "SKIP" for r in decisions),
            }
            self.db.add(
                AuditLog(
                    actor_user_id=self.service.actor.id,
                    action="staff.onboarding.confirm",
                    resource_type="staff_onboarding",
                    resource_id=operation_id,
                    after_json=result,
                )
            )
            self.db.commit()
            return result

    def set_real_number(self, staff_id, real_number, lock_version):
        """显式 ID + 版本补充真实工号，保留微信临时工号，不改账号/任职/历史。"""
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", real_number) or real_number.upper().startswith(
            "TMP_"
        ):
            raise ConflictError(message="真实工号格式无效，TMP_ 是临时工号保留前缀")
        try:
            with self.service.operation("staff.manage"):
                college = self.db.get(College, self.service.cid)
                self.db.execute(
                    select(School.id).where(School.id == college.school_id).with_for_update()
                ).all()
                staff = self.db.scalar(
                    select(FacultyStaff)
                    .where(
                        FacultyStaff.id == staff_id,
                        FacultyStaff.college_id == self.service.cid,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    staff is None
                    or staff.lock_version != lock_version
                    or not staff.temporary_staff_no
                    or staff.status != "ACTIVE"
                ):
                    raise ConflictError(message="档案不存在、已停用、非临时档案或版本已变化")
                if staff.staff_no != staff.temporary_staff_no and staff.staff_no != real_number:
                    raise ConflictError(message="已有其他真实工号，不允许通过补充操作覆盖")
                occupied = self.db.scalar(
                    select(FacultyStaff.id).where(
                        FacultyStaff.school_id == college.school_id,
                        FacultyStaff.id != staff.id,
                        or_(
                            FacultyStaff.staff_no == real_number,
                            FacultyStaff.temporary_staff_no == real_number,
                        ),
                    )
                )
                if occupied:
                    raise ConflictError(message="真实工号已属于其他教职工，不能合并")
                before = staff.staff_no
                staff.staff_no = real_number
                staff.lock_version += 1
                self.db.add(
                    AuditLog(
                        actor_user_id=self.service.actor.id,
                        action="staff.onboarding.real_number",
                        resource_type="faculty_staff",
                        resource_id=str(staff.id),
                        before_json={"staff_no": before},
                        after_json={"staff_no": real_number},
                    )
                )
                self.db.commit()
        except Exception:
            self.db.rollback()
            raise
