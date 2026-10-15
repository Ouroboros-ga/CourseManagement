"""只读工作台聚合：每项复用真实动作范围，不根据前端菜单推断授权。"""

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.models import (
    CourseSchedule,
    PeriodDefinition,
    Semester,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.academic.publication_models import AcademicPublication
from app.modules.academic.scoped_repository import ScopedAcademicRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.role_scope import business_today
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.objection.models import Objection
from app.modules.objection.repository import ObjectionRepository
from app.modules.organization.service import CampusService
from app.modules.volunteer.eligibility_index import EligibilityIndex
from app.modules.volunteer.member_models import VolunteerGroupMember
from app.modules.volunteer.models import VolunteerGroup


class WorkspaceOverviewService:
    def __init__(self, db, actor, college_id):
        self.db, self.actor, self.cid = db, actor, college_id

    def _scope(self, action):
        try:
            return resolve_scope(self.db, self.actor, self.cid, action)
        except (PermissionDeniedError, NotFoundError):
            return None

    def _count(self, statement):
        return self.db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))

    def read(self, semester_id):
        campus = CampusService(self.db)
        workspace = campus.capabilities(self.actor, self.cid)
        if not workspace["capabilities"]:
            raise PermissionDeniedError()
        semester = self.db.get(Semester, semester_id)
        if semester is None:
            raise NotFoundError("学期不存在")
        day = business_today()
        items = []

        def item(key, label, count, path, tab, *, pending=False, scope_label="本学期"):
            items.append(
                {
                    "id": key,
                    "label": label,
                    "count": count,
                    "status": ("ACTION_REQUIRED" if count else "COMPLETE")
                    if pending
                    else ("AVAILABLE" if count else "EMPTY"),
                    "scope_label": scope_label,
                    "destination": {"path": f"/dashboard/{path}", "query": {"tab": tab}},
                }
            )

        scope = self._scope("student.read")
        if scope:
            repo = ScopedAcademicRepository(self.db, scope)
            item(
                "students",
                "当前学生档案",
                self._count(repo.query("students")),
                "students",
                "directory",
                scope_label="当前档案",
            )

        scope = self._scope("academic.read")
        if scope:
            repo = ScopedAcademicRepository(self.db, scope)
            item(
                "classes",
                "行政班",
                self._count(repo.query("administrative_classes")),
                "students",
                "directory",
                scope_label="跨学期基础库",
            )
            item(
                "schedules",
                "正式课表条目",
                self._count(
                    repo.query("schedules").where(CourseSchedule.semester_id == semester_id)
                ),
                "academic",
                "timetable",
            )
            item(
                "unclassified",
                "尚未分类的教学班",
                self._count(
                    repo.query("teaching_classes").where(
                        TeachingClass.semester_id == semester_id,
                        TeachingClass.course_type_id.is_(None),
                        TeachingClass.status == "ACTIVE",
                    )
                ),
                "academic",
                "classes",
                pending=True,
            )
            item(
                "periods",
                "已配置起止时间的学校节次",
                self._count(
                    select(PeriodDefinition.id).where(
                        PeriodDefinition.semester_id == semester_id,
                        PeriodDefinition.start_time.is_not(None),
                        PeriodDefinition.end_time.is_not(None),
                    )
                ),
                "settings" if "academic.manage" in workspace["capabilities"] else "academic",
                "" if "academic.manage" in workspace["capabilities"] else "timetable",
                scope_label="本学期学校默认",
            )
            # 只读用户可看到已发布状态，但不获得发布操作权。
            item(
                "publications",
                "正式发布版本",
                self._count(
                    select(AcademicPublication.id).where(
                        AcademicPublication.college_id == self.cid,
                        AcademicPublication.semester_id == semester_id,
                    )
                ),
                "academic",
                "timetable",
            )

        scope = self._scope("volunteer.read")
        if scope:
            qualifications = list(
                self.db.scalars(
                    ScopedAcademicRepository(self.db, scope)
                    .query("qualifications")
                    .where(VolunteerQualification.semester_id == semester_id)
                )
            )
            eligibility = EligibilityIndex(self.db, [row.student_id for row in qualifications], [])
            count = sum(eligibility.qualified(row, day, self.cid) for row in qualifications)
            item(
                "qualifications",
                "当日有效资格人数",
                count,
                "organizations",
                "qualifications",
                scope_label=f"本学期 · {day.isoformat()}",
            )

        scope = self._scope("volunteer.group.read")
        if scope:
            query = select(VolunteerGroup.id).where(
                VolunteerGroup.college_id == self.cid,
                VolunteerGroup.status == "ACTIVE",
                (VolunteerGroup.starts_on.is_(None) | (VolunteerGroup.starts_on <= day)),
                (VolunteerGroup.ends_on.is_(None) | (VolunteerGroup.ends_on >= day)),
            )
            if not scope.unrestricted:
                ids = {
                    int(value)
                    for clause in scope.constraints
                    if clause["kind"] == "GROUPS"
                    for value in clause["ids"]
                }
                query = query.where(VolunteerGroup.id.in_(ids))
            gids = list(self.db.scalars(query))
            item(
                "groups",
                "可见有效组织",
                len(gids),
                "organizations",
                "groups",
                scope_label="当前组织",
            )
            members = (
                select(VolunteerGroupMember.student_id)
                .where(
                    VolunteerGroupMember.college_id == self.cid,
                    VolunteerGroupMember.group_id.in_(gids),
                    VolunteerGroupMember.semester_id == semester_id,
                    VolunteerGroupMember.status == "ACTIVE",
                    VolunteerGroupMember.effective_from <= day,
                    VolunteerGroupMember.effective_to > day,
                )
                .distinct()
            )
            item(
                "members",
                "当日有效成员人数（去重）",
                self._count(members),
                "organizations",
                "members",
                scope_label=f"本学期 · {day.isoformat()}",
            )

        scope = self._scope("inspection.read")
        if scope:
            tasks = select(InspectionTask.id).where(
                scope.task_condition(),
                InspectionTask.semester_id == semester_id,
                InspectionTask.canceled_at.is_(None),
            )
            assigned = select(InspectionAssignment.task_id).where(
                InspectionAssignment.revoked_at.is_(None)
            )
            item(
                "unassigned",
                "未排班的有效任务",
                self._count(tasks.where(InspectionTask.id.not_in(assigned))),
                "inspections",
                "tasks",
                pending=True,
            )
            items[-1]["destination"]["query"]["needs_attention"] = "unassigned"
            item(
                "roster_review",
                "待核对名单的有效任务",
                self._count(tasks.where(InspectionTask.roster_review_required.is_(True))),
                "inspections",
                "tasks",
                pending=True,
            )
            items[-1]["destination"]["query"]["needs_attention"] = "roster"

        scope = self._scope("objection.read")
        if scope:
            from app.modules.attendance.models import AttendanceRecord

            stmt = (
                ObjectionRepository(self.db, scope)
                ._objections()
                .where(
                    Objection.final_status == "PENDING",
                    Objection.attendance_record_id.in_(
                        select(AttendanceRecord.id)
                        .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                        .where(InspectionTask.semester_id == semester_id)
                    ),
                )
            )
            item(
                "objections",
                "待审核学生异议",
                self._count(stmt),
                "attendance",
                "objections",
                pending=True,
            )
            items[-1]["destination"]["query"]["status"] = "PENDING_FINAL"

        settings = get_settings()
        return {
            "college_id": str(self.cid),
            "semester_id": str(semester_id),
            "semester_status": semester.status,
            "as_of": day.isoformat(),
            "items": items,
            "runtime": {
                "academic_scoped": settings.campus_academic_scoped_enabled,
                "business_scoped": settings.campus_business_scoped_enabled,
                "scheduling": settings.campus_scheduling_enabled,
            },
            "scheduling_note": (
                "成员与资格不等于可排班人数；请在具体任务预览中核对冲突、请假和配额。"
            ),
        }
