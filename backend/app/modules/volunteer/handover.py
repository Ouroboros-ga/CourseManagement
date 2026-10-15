"""Transfer a dedicated owner grant without revoking independent permissions."""

from pydantic import Field
from sqlalchemy import select

from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.authorization import fixed_college_actions
from app.modules.identity.grant_scope import GROUP_ACTIONS, TASK_ACTIONS, resource_definition
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import InspectionTask
from app.modules.organization.models import ScopedGrant
from app.modules.organization.schemas import GrantCreate, StrictModel
from app.modules.organization.service import CampusService, atomic_write, validated
from app.modules.volunteer.member_service import GroupMemberService


class Handover(StrictModel):
    owner_user_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    reason: str = Field(min_length=1, max_length=512)


class HandoverConfirm(Handover):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


OWNER_ACTIONS = sorted(GROUP_ACTIONS | TASK_ACTIONS)


def permission_sources(db, uid, cid):
    """Expose actual active sources; the normal authorization engine stays authoritative."""
    user = db.get(UserAccount, uid)
    if user is None or user.status != "ACTIVE":
        return []
    result = []
    actions = fixed_college_actions(db, uid, cid)
    if actions:
        result.append(
            {
                "kind": "FIXED_IDENTITY",
                "actions": sorted(actions),
                "scope": {"kind": "COLLEGE", "ids": []},
            }
        )
    now = utcnow()
    for grant in db.scalars(
        select(ScopedGrant)
        .where(
            ScopedGrant.user_id == uid,
            ScopedGrant.college_id == cid,
            ScopedGrant.status == "ACTIVE",
        )
        .order_by(ScopedGrant.id)
    ):
        if (grant.starts_at and grant.starts_at > now) or (
            grant.expires_at and grant.expires_at <= now
        ):
            continue
        result.append(
            {
                "kind": "GROUP_OWNER" if grant.owner_group_id else "EXPLICIT_GRANT",
                "id": str(grant.id),
                "owner_group_id": str(grant.owner_group_id) if grant.owner_group_id else None,
                "actions": grant.actions,
                "scope": resource_definition(grant),
                "expires_at": grant.expires_at,
            }
        )
    return result


class GroupHandoverService:
    def __init__(self, db, actor, cid, gid):
        self.db, self.actor, self.cid, self.gid = db, actor, cid, gid
        self.campus = CampusService(db)

    def authorize(self):
        roles = set(IdentityRepository(self.db).list_role_codes(self.actor.id))
        if not roles & {"SUPER_ADMIN", "TEACHER_ADMIN"}:
            raise PermissionDeniedError("负责人交接须由有本院管理权限的教师或超管执行")
        college = self.campus._authorize(self.actor, self.cid, "volunteer.group.manage", write=True)
        from app.modules.identity.resource_scope import resolve_scope

        # A cross-college group-management grant must not mint unrelated powers.
        for action in OWNER_ACTIONS:
            scope = resolve_scope(self.db, self.actor, self.cid, action, write=True)
            if not scope.unrestricted:
                raise PermissionDeniedError(
                    "交接者须具备所授全部动作的本院管理权限，不能扩大受限授权"
                )
        return college

    def _preview(self, data):
        body = validated(Handover, data)
        college = self.authorize()
        _, group = GroupMemberService(self.db, self.actor, self.cid, self.gid)._group(
            "volunteer.group.manage", write=True
        )
        target = self.db.scalar(
            select(UserAccount)
            .where(UserAccount.id == int(body.owner_user_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if target is None or target.status != "ACTIVE":
            raise NotFoundError("新负责人账号不存在或已停用")
        if not self.db.scalar(
            select(UserAccount.id).where(UserAccount.id == target.id, self._eligible_target())
        ):
            raise PermissionDeniedError("跨学院负责人任命须由超管明确授权")
        if group.status != "ACTIVE":
            raise ConflictError(message="请先启用并发布组织规则，再交接负责人及操作权限")
        grants = list(
            self.db.scalars(
                select(ScopedGrant)
                .where(
                    ScopedGrant.owner_group_id == self.gid,
                    ScopedGrant.college_id == self.cid,
                    ScopedGrant.status == "ACTIVE",
                )
                .order_by(ScopedGrant.id)
                .with_for_update()
            )
        )
        grant_body = validated(
            GrantCreate,
            {
                "user_id": str(target.id),
                "actions": OWNER_ACTIONS,
                "resource_scope": {"kind": "GROUPS", "ids": [str(group.id)]},
            },
        )
        definition = self.campus._grant_definition(self.cid, grant_body)
        tasks = list(
            self.db.execute(
                select(InspectionTask.id, InspectionTask.lock_version)
                .where(
                    InspectionTask.college_id == self.cid,
                    InspectionTask.group_id == self.gid,
                    InspectionTask.canceled_at.is_(None),
                )
                .order_by(InspectionTask.id)
            )
        )
        sources = permission_sources(self.db, group.owner_user_id, self.cid)
        revision = fingerprint(
            {
                "body": body.model_dump(),
                "group": self.campus._dto(group),
                "authorization_revision": college.authorization_revision,
                "target": self.campus._dto(target),
                "grants": [self.campus._dto(g) for g in grants],
                "definition": definition,
                "tasks": [list(t) for t in tasks],
                "sources": sources,
            }
        )
        preview = {
            "revision": revision,
            "old_owner_user_id": str(group.owner_user_id),
            "new_owner_user_id": str(target.id),
            "new_owner_name": target.display_name,
            "new_owner_web_login_ready": bool(target.username and target.password_hash),
            "grant_actions": OWNER_ACTIONS,
            "grant_scope": definition,
            "revoke_dedicated_grant_ids": [str(g.id) for g in grants],
            "old_owner_retained_sources": [
                s for s in sources if s.get("owner_group_id") != str(group.id)
            ],
            "retained_task_ids": [str(t.id) for t in tasks],
            "existing_assignments_preserved": True,
        }
        return college, group, grants, preview

    def _eligible_target(self):
        """An existing scoped grant is not permission to expand another user's powers."""
        from sqlalchemy import true

        from app.modules.academic.enrollment_models import StudentEnrollment, TeacherCollegeBinding
        from app.modules.academic.models import AdministrativeClass, Student
        from app.modules.identity.role_scope import business_today

        if "SUPER_ADMIN" in IdentityRepository(self.db).list_role_codes(self.actor.id):
            return true()
        today = business_today()
        dated = select(StudentEnrollment.student_id).where(
            StudentEnrollment.superseded.is_(False),
            StudentEnrollment.status == "ENROLLED",
            StudentEnrollment.college_id == self.cid,
            StudentEnrollment.effective_from <= today,
            StudentEnrollment.effective_to.is_(None) | (StudentEnrollment.effective_to > today),
        )
        # Legacy class ownership is usable only before a dated enrollment exists.
        legacy = (~Student.id.in_(select(StudentEnrollment.student_id))) & (
            Student.administrative_class_id.in_(
                select(AdministrativeClass.id).where(AdministrativeClass.college_id == self.cid)
            )
        )
        student_ids = select(Student.id).where(
            Student.status == "ACTIVE",
            Student.id.in_(dated) | legacy,
        )
        return UserAccount.student_id.in_(student_ids) | UserAccount.id.in_(
            select(TeacherCollegeBinding.user_id).where(
                TeacherCollegeBinding.college_id == self.cid
            )
        )

    def candidates(self, keyword=""):
        self.authorize()
        users = select(UserAccount).where(
            UserAccount.status == "ACTIVE",
            self._eligible_target(),
        )
        if keyword:
            users = users.where(
                UserAccount.display_name.contains(keyword, autoescape=True)
                | UserAccount.username.contains(keyword, autoescape=True)
            )
        return [
            {"id": str(u.id), "display_name": u.display_name, "username": u.username}
            for u in self.db.scalars(users.order_by(UserAccount.id).limit(100))
        ]

    def preview(self, data):
        return self._preview(data)[3]

    @atomic_write
    def confirm(self, data):
        body = validated(HandoverConfirm, data)
        college, group, grants, preview = self._preview(body.model_dump(exclude={"revision"}))
        if body.revision != preview["revision"]:
            raise ConflictError(message="负责人、任务或权限已变化，请重新预览交接")
        for grant in grants:
            grant.status = "REVOKED"
            grant.lock_version += 1
        group.owner_user_id = int(body.owner_user_id)
        group.lock_version += 1
        college.authorization_revision += 1
        college.configuration_revision += 1
        row = ScopedGrant(
            college_id=self.cid,
            user_id=group.owner_user_id,
            owner_group_id=group.id,
            granted_by=self.actor.id,
            actions=OWNER_ACTIONS,
            resource_scope=preview["grant_scope"],
        )
        self.db.add(row)
        self.db.flush()
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="volunteer.owner.handover",
                resource_type="volunteer_group",
                resource_id=str(group.id),
                after_json=scoped_snapshot(
                    {**preview, "reason": body.reason, "new_grant_id": str(row.id)}, self.cid
                ),
            )
        )
        self.db.commit()
        return {
            "group_id": str(group.id),
            "owner_user_id": str(group.owner_user_id),
            "lock_version": group.lock_version,
            "grant_id": str(row.id),
            "retained_task_ids": preview["retained_task_ids"],
        }
