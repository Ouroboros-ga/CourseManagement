"""已存资料补关联：预览无写入，确认绑定学院/账号/学期/日期/人员来源版本。"""

import hashlib
import json

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.modules.academic.models import AdministrativeClass, Course, CourseSchedule, TeachingClass
from app.modules.identity.role_scope import business_today
from app.modules.importer.person_links import apply_links, plan_links, summary


class PersonLinkReconciliation:
    def __init__(self, service):
        self.service = service
        self.db = service._session

    def _plan(self, kind, semester_id):
        if semester_id is not None and not 0 < semester_id < 2**63:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学期 ID 不合法", 422)
        if kind not in {"teaching", "responsibility"}:
            raise AppError(ErrorCode.VALIDATION_ERROR, "未知人员关联类型", 422)
        cid = self.service.cid
        if kind == "teaching":
            self.service._require_active_semester_for_confirm(semester_id)
            rows = self.db.execute(
                select(TeachingClass, Course.course_code)
                .join(Course)
                .where(
                    TeachingClass.college_id == cid,
                    TeachingClass.semester_id == semester_id,
                    TeachingClass.status == "ACTIVE",
                )
            ).all()
            if len(rows) > get_settings().import_max_rows:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, "教学班过多，请分批通过授课关系模板补关联", 422
                )
            teachers = {}
            for tid, name in self.db.execute(
                select(CourseSchedule.teaching_class_id, CourseSchedule.teacher).where(
                    CourseSchedule.college_id == cid,
                    CourseSchedule.semester_id == semester_id,
                    CourseSchedule.status == "ACTIVE",
                    CourseSchedule.teacher.is_not(None),
                )
            ):
                if name.strip():
                    teachers.setdefault(tid, set()).add(name)
            payload = {
                "rows": [
                    {"class_code": tc.class_code, "course_code": code, "teacher": name}
                    for tc, code in rows
                    for name in sorted(teachers.get(tc.id) or {tc.teacher_name or ""})
                ]
            }
            target = "timetable"
        else:
            if semester_id is not None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, "班级责任关系跨学期生效，请勿指定学期", 422
                )
            rows = list(
                self.db.scalars(
                    select(AdministrativeClass).where(
                        AdministrativeClass.college_id == cid,
                        AdministrativeClass.status == "ACTIVE",
                    )
                )
            )
            payload = {
                "class_duties": [
                    {
                        "class_name": ac.class_name,
                        "head_teacher": ac.head_teacher,
                        "counselor": ac.counselor,
                    }
                    for ac in rows
                ]
            }
            target = "admin_roster"
        links = plan_links(self.service, target, payload, semester_id)
        if len(links["links"]) + len(links["pending"]) > get_settings().import_max_rows:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人员关联过多，请分批通过关系模板处理", 422)
        revision = hashlib.sha256(
            json.dumps(
                {
                    "actor": self.service.actor.id,
                    "college": cid,
                    "kind": kind,
                    "semester": semester_id,
                    "today": str(business_today()),
                    "source": self.service.source_revision(),
                    "plan": links,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        return {**links, "summary": summary(links), "revision": revision}

    def preview(self, kind, semester_id):
        with self.service.operation("staff.manage"):
            return self._plan(kind, semester_id)

    def confirm(self, kind, semester_id, revision, request_id):
        with self.service.operation("staff.manage"):
            plan = self._plan(kind, semester_id)
            if plan["revision"] != revision:
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT, "人员、课表或任职关系已变化，请重新核对"
                )
            result = apply_links(self.service, plan, semester_id, request_id)
            self.db.commit()
            return {**result, "summary": plan["summary"]}
