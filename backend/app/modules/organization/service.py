"""配置事务：最新账号/角色与学院锚点复核，关键事实和审计同事务。"""

import unicodedata
import uuid
from datetime import datetime
from functools import wraps

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import iso_utc, utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.academic.campus_models import CourseType
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.authorization import (
    CAMPUS_ACTIONS,
    effective_actions,
    fixed_college_actions,
)
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.organization.future_impact import confirm_impact, future_impact
from app.modules.organization.models import College, School, ScopedGrant
from app.modules.organization.repository import CampusRepository
from app.modules.organization.schemas import (
    CollegeCreate,
    CollegeUpdate,
    GrantCreate,
    GroupCreate,
    GroupPublish,
    GroupUpdate,
    SchoolCreate,
    TypeCreate,
    TypeUpdate,
)
from app.modules.volunteer.models import GroupConfigVersion, GroupScopeType, VolunteerGroup


def normalized_name(name: str) -> str:
    key = unicodedata.normalize("NFKC", name).strip().casefold()
    if not key or len(key) > 128:
        raise AppError(ErrorCode.VALIDATION_ERROR, "规范化后的名称须为 1—128 字符", 422)
    return key


def validated(schema, data):
    try:
        return schema.model_validate(data, context={"internal": True})
    except ValidationError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "配置格式无效，请检查字段", 422) from exc


def atomic_write(method):
    """内部调用亦回滚失败写，避免同 Session 的后续提交保留部分变更。"""

    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            (self.db if hasattr(self, "db") else self._session).rollback()
            raise

    return call


class CampusService:
    def __init__(self, session: Session, request_id: str | None = None):
        self.db = session
        self.repo = CampusRepository(session)
        self.identity = IdentityRepository(session)
        self.request_id = request_id

    def _actor(self, actor: CurrentUser, *, lock=False) -> bool:
        user = (
            self.identity.get_user_by_id_for_update(actor.id)
            if lock
            else self.db.scalar(select(UserAccount).where(UserAccount.id == actor.id)
                .with_for_update(read=True).execution_options(populate_existing=True))
        )
        if user is None or user.status != "ACTIVE" or actor.pre_binding:
            raise PermissionDeniedError("账号无效或尚未绑定")
        roles = (
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == actor.id)
        )
        roles = roles.with_for_update(read=True)
        return "SUPER_ADMIN" in self.db.scalars(roles)

    def _super(self, actor: CurrentUser):
        if not self._actor(actor, lock=True):
            raise PermissionDeniedError("仅超级管理员可维护学校、学院和院级授权")

    def _teacher_college_id(self, actor, *, lock=False):
        from app.modules.academic.enrollment_models import TeacherCollegeBinding

        # 用最新数据库角色和绑定派生本院权限，不依赖 token 中的学院或角色标签。
        if "TEACHER_ADMIN" not in self.identity.list_role_codes(actor.id):
            return None
        query = select(TeacherCollegeBinding).where(TeacherCollegeBinding.user_id == actor.id)
        query = query.with_for_update(read=True)
        binding = self.db.scalar(query.execution_options(populate_existing=True))
        return binding.college_id if binding else None

    def _authorize(self, actor, cid, action, *, write=False, allow_restricted=False):
        is_super = self._actor(actor, lock=write)
        primary_cid = self._teacher_college_id(actor, lock=write) if not is_super else None
        college = self.repo.college(cid, lock=write)
        actions = (
            CAMPUS_ACTIONS
            if is_super or (primary_cid == cid and college and college.status == "ACTIVE")
            else fixed_college_actions(self.db, actor.id, cid) | effective_actions(
                self.repo.grants(actor.id, college_id=cid, lock=write), cid, utcnow(), include_restricted=allow_restricted
            )
        )
        if college is None or not actions:
            raise NotFoundError()
        if action not in actions:
            raise PermissionDeniedError()
        if write and college.status != "ACTIVE":
            raise ConflictError(message="学院已停用")
        return college

    @staticmethod
    def _version(row, version):
        if row.lock_version != version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "配置已变化，请刷新后重试")

    def _resource(self, model, cid, rid):
        row = self.repo.resource(model, cid, rid)
        if row is None or getattr(row, "deleted_at", None) is not None:
            raise NotFoundError()
        return row

    def _commit(
        self,
        actor,
        action,
        row,
        before=None,
        *,
        resource_id=None,
        resource_type="CourseType",
        impact_task_ids=None,
        group_config=None,
    ):
        try:
            self.db.flush()
            after = (
                (
                    self._dto(row, group_config=group_config, group_config_loaded=True)
                    if group_config is not None
                    else self._dto(row)
                )
                if row is not None
                else None
            )
            impact_fields = {
                "campus.type.update": ("status",),
                "campus.group.update": ("status", "starts_on", "ends_on"),
                "campus.group.publish": ("configuration",),
                "campus.college.update": ("status",),
            }.get(action, ())
            if before and any(before.get(key) != after.get(key) for key in impact_fields):
                from app.modules.organization.impact_service import capture_impacts
                kind = {"campus.type.update": "course_type", "campus.group.update": "group",
                        "campus.group.publish": "group", "campus.college.update": "college"}[action]
                capture_impacts(
                    self.db,
                    row.id if kind == "college" else row.college_id,
                    kind,
                    row.id,
                    row.lock_version,
                    task_ids=impact_task_ids,
                    before=before,
                    after=after,
                )
            self.db.add(
                AuditLog(
                    actor_user_id=actor.id,
                    action=action,
                    resource_type=type(row).__name__ if row is not None else resource_type,
                    resource_id=str(row.id) if row is not None else resource_id,
                    before_json=before,
                    after_json=scoped_snapshot(after, row.id if isinstance(row, College) else getattr(row, "college_id", None)),
                    request_id=self.request_id,
                )
            )
            self.db.commit()
            return after
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(message="名称/编码重复或资源已被引用，无法保存") from exc

    def _dto(self, row, *, group_config=None, group_config_loaded=False):
        data = {}
        for column in row.__table__.columns:
            if column.name in {"normalized_name", "singleton_key"}:
                continue
            value = getattr(row, column.name)
            if value is not None and (
                column.name == "id"
                or column.name.endswith("_id")
                or column.name in {"granted_by", "published_by"}
                or bool(column.foreign_keys)
            ):
                value = str(value)
            elif isinstance(value, datetime):
                value = iso_utc(value)
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            data[column.name] = value
        if isinstance(row, VolunteerGroup):
            config = group_config
            if not group_config_loaded:
                config = self.db.scalar(
                    select(GroupConfigVersion)
                    .where(
                        GroupConfigVersion.group_id == row.id,
                        GroupConfigVersion.version == row.config_version,
                    )
                    .with_for_update(read=True)
                )
            data["configuration"] = config.configuration if config else None
        return data

    def schools(self, actor):
        self._super(actor)
        return [self._dto(row) for row in self.db.scalars(select(School).order_by(School.id))]

    @atomic_write
    def create_school(self, actor, data):
        body = validated(SchoolCreate, data)
        self._super(actor)
        if self.db.scalar(select(School.id).limit(1)) is not None:
            raise ConflictError(message="当前版本按单学校部署，不创建第二学校")
        row = School(**body.model_dump())
        self.db.add(row)
        return self._commit(actor, "campus.school.create", row)

    @atomic_write
    def create_college(self, actor, school_id, data):
        body = validated(CollegeCreate, data)
        self._super(actor)
        if self.db.get(School, school_id) is None:
            raise NotFoundError()
        row = College(school_id=school_id, **body.model_dump())
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(message="学院编码重复，无法创建") from exc
        from app.modules.academic.default_types import ensure_initial_types
        ensure_initial_types(self.db, row.id)
        return self._commit(actor, "campus.college.create", row)

    @atomic_write
    def update_college(self, actor, cid, data):
        body = validated(CollegeUpdate, data)
        self._super(actor)
        row = self.repo.college(cid, lock=True)
        if row is None:
            raise NotFoundError()
        self._version(row, body.lock_version)
        if body.status == "INACTIVE" and row.status == "ACTIVE":
            from app.modules.identity.role_scope import business_today
            from app.modules.inspection.models import InspectionTask
            remaining = self.db.scalar(select(InspectionTask.id).where(
                InspectionTask.college_id == cid, InspectionTask.canceled_at.is_(None),
                InspectionTask.inspection_date >= business_today()).limit(1))
            if remaining is not None:
                raise ConflictError(message="学院仍有未来有效任务，请先完成或取消后再停用；历史数据继续保留")
        before = self._dto(row)
        for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
            if key != "lock_version":
                setattr(row, key, value)
        row.lock_version += 1
        if row.status != before["status"]:
            row.authorization_revision += 1
        return self._commit(actor, "campus.college.update", row, before)

    def workspaces(self, actor):
        is_super = self._actor(actor)
        primary_cid = self._teacher_college_id(actor) if not is_super else None
        grants = self.repo.grants(actor.id)
        result = []
        for college in self.db.scalars(select(College).order_by(College.id).execution_options(populate_existing=True)):
            actions = (
                CAMPUS_ACTIONS
                if is_super or (primary_cid == college.id and college.status == "ACTIVE")
                else fixed_college_actions(self.db, actor.id, college.id) | effective_actions(grants, college.id, utcnow(), include_restricted=True)
            )
            if actions:
                data = self._dto(college)
                data["capabilities"] = (
                    sorted(actions)
                    if college.status == "ACTIVE"
                    else sorted(action for action in actions if action.endswith(".read"))
                )
                data["business_ready"] = False
                result.append(data)
        return result

    def capabilities(self, actor, cid):
        for workspace in self.workspaces(actor):
            if workspace["id"] == str(cid):
                return workspace
        raise NotFoundError()

    def list_grants(self, actor, cid):
        self._super(actor)
        if self.repo.college(cid) is None:
            raise NotFoundError()
        return [self._dto(row) for row in self.repo.rows(ScopedGrant, cid)]

    def _grant_definition(self, cid, body):
        definition = body.resource_scope.model_dump()
        from app.modules.academic.models import TeachingClass
        resource_model = {"GROUPS": VolunteerGroup, "COURSE_TYPES": CourseType,
                          "TEACHING_CLASSES": TeachingClass}.get(definition["kind"])
        if resource_model:
            for value in definition["ids"]:
                resource = self._resource(resource_model, cid, int(value))
                if resource.status != "ACTIVE":
                    raise ConflictError(message="不能授权已停用资源")
        if definition["kind"] == "GROUPS":
            definition["bounds"] = {}
            for gid in definition["ids"]:
                group = self._resource(VolunteerGroup, cid, int(gid))
                version = self.db.scalar(select(GroupConfigVersion).where(
                    GroupConfigVersion.group_id == group.id, GroupConfigVersion.college_id == cid,
                    GroupConfigVersion.version == group.config_version).with_for_update(read=True))
                config = version.configuration if version else {}
                definition["bounds"][gid] = {key: config.get(key, default) for key, default in (
                    ("course_type_ids", []), ("class_mode", "SPECIFIC"), ("class_ids", []))}
        return definition

    def preview_grant(self, actor, cid, data):
        body = validated(GrantCreate, data)
        self._super(actor)
        college = self.repo.college(cid)
        if college is None:
            raise NotFoundError()
        definition = self._grant_definition(cid, body)
        from app.modules.inspection.assignment_fingerprint import fingerprint
        revision = fingerprint({"college_id": cid, "authorization_revision": college.authorization_revision,
            "definition": definition, "body": body.model_dump(mode="json", exclude={"preview_revision"})})
        return {"revision": revision, "resource_scope": definition, "actions": body.actions,
                "user_id": body.user_id}

    @atomic_write
    def create_grant(self, actor, cid, data):
        body = validated(GrantCreate, data)
        self._super(actor)
        college = self.repo.college(cid, lock=True)
        if college is None:
            raise NotFoundError()
        if college.status != "ACTIVE":
            raise ConflictError(message="学院已停用")
        target = self.db.get(UserAccount, int(body.user_id))
        if target is None or target.status != "ACTIVE":
            raise NotFoundError("目标账号无效")
        definition = self._grant_definition(cid, body)
        preview = self.preview_grant(actor, cid, body.model_dump())
        if (definition["kind"] != "COLLEGE" or body.preview_revision is not None) and body.preview_revision != preview["revision"]:
            raise ConflictError(message="授权范围或配置已变化，请重新预览后确认")
        row = ScopedGrant(
            college_id=cid,
            granted_by=actor.id,
            **body.model_dump(exclude={"user_id", "resource_scope", "preview_revision"}),
            resource_scope=definition,
            user_id=int(body.user_id),
        )
        self.db.add(row)
        college.authorization_revision += 1
        return self._commit(actor, "campus.grant.create", row)

    @atomic_write
    def revoke_grant(self, actor, cid, rid, version):
        self._super(actor)
        college = self.repo.college(cid, lock=True)
        if college is None:
            raise NotFoundError()
        row = self._resource(ScopedGrant, cid, rid)
        self._version(row, version)
        before = self._dto(row)
        row.status = "REVOKED"
        row.lock_version += 1
        college.authorization_revision += 1
        return self._commit(actor, "campus.grant.revoke", row, before)

    def configuration_impact(
        self, actor, cid, kind, rid, *, semester_id=None, configuration_only=False
    ):
        model, action = {
            "course_type": (CourseType, "academic.course_type.read"),
            "group": (VolunteerGroup, "volunteer.group.read"),
        }[kind]
        scope = None
        if kind == "group":
            from app.modules.identity.resource_scope import resolve_scope
            scope = resolve_scope(self.db, actor, cid,
                "volunteer.config.publish" if configuration_only else action)
            if not scope.permits_group(rid):
                raise NotFoundError()
        else:
            self._authorize(actor, cid, action)
        row = self._resource(model, cid, rid)
        return future_impact(
            self.db,
            cid,
            kind,
            row.id,
            row.lock_version,
            resource_scope=scope,
            semester_id=semester_id,
            inherited_only=configuration_only and semester_id is None,
        )

    def list_types(self, actor, cid, deleted_only=False):
        self._authorize(actor, cid, "academic.course_type.read")
        return [
            self._dto(row)
            for row in sorted(
                self.repo.rows(CourseType, cid), key=lambda row: (row.sort_order, row.id)
            )
            if (row.deleted_at is not None) == deleted_only
        ]

    @atomic_write
    def create_type(self, actor, cid, data):
        body = validated(TypeCreate, data)
        college = self._authorize(actor, cid, "academic.course_type.manage", write=True)
        row = CourseType(
            college_id=cid,
            code=uuid.uuid4().hex,
            normalized_name=normalized_name(body.name),
            **body.model_dump(),
        )
        self.db.add(row)
        college.configuration_revision += 1
        return self._commit(actor, "campus.type.create", row)

    @atomic_write
    def update_type(self, actor, cid, rid, data):
        body = validated(TypeUpdate, data)
        college = self._authorize(actor, cid, "academic.course_type.manage", write=True)
        row = self._resource(CourseType, cid, rid)
        self._version(row, body.lock_version)
        changes = {
            k: v
            for k, v in body.model_dump(exclude_unset=True, exclude_none=True).items()
            if k not in {"lock_version", "future_impact_revision"} and getattr(row, k) != v
        }
        if not changes:
            return self._dto(row)
        if "status" in changes:
            confirm_impact(self.db, cid, "course_type", row, body.future_impact_revision)
        before = self._dto(row)
        for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
            if key not in {"lock_version", "future_impact_revision"}:
                setattr(row, key, value)
        row.normalized_name = normalized_name(row.name)
        row.lock_version += 1
        if row.status != before["status"]:
            college.configuration_revision += 1
        return self._commit(actor, "campus.type.update", row, before)

    @atomic_write
    def delete_type(self, actor, cid, rid, version, deletion_revision=None):
        from app.modules.organization.resource_deletion import delete_resource
        return delete_resource(self, actor, cid, "course_type", rid, version, deletion_revision)

    def deletion_preview(self, actor, cid, kind, rid):
        from app.modules.organization.resource_deletion import preview
        return preview(self, actor, cid, kind, rid)[2]

    @atomic_write
    def restore_deleted(self, actor, cid, kind, rid, version, name=None):
        from app.modules.organization.resource_deletion import restore
        return restore(self, actor, cid, kind, rid, version, name)

    def _legacy_delete_type(self, actor, cid, rid, version):
        college = self._authorize(actor, cid, "academic.course_type.manage", write=True)
        row = self._resource(CourseType, cid, rid)
        self._version(row, version)
        if row.builtin_key is not None:
            raise ConflictError(message="初始课程类型保留稳定标识，只能停用或更名")
        if self.db.scalar(
            select(func.count())
            .select_from(GroupScopeType)
            .where(
                GroupScopeType.college_id == cid,
                GroupScopeType.course_type_id == rid,
            )
        ):
            raise ConflictError(message="课程类型已被组配置引用，只能停用")
        before = self._dto(row)
        self.db.delete(row)
        college.configuration_revision += 1
        self._commit(actor, "campus.type.delete", None, before, resource_id=str(rid))

    def list_groups(self, actor, cid, deleted_only=False):
        from app.modules.identity.resource_scope import resolve_scope
        scope = resolve_scope(self.db, actor, cid, "volunteer.group.read")
        query = select(VolunteerGroup).where(VolunteerGroup.college_id == cid).order_by(VolunteerGroup.id)
        query = query.where(VolunteerGroup.deleted_at.is_not(None) if deleted_only else VolunteerGroup.deleted_at.is_(None))
        if not scope.unrestricted:
            ids = {int(value) for clause in scope.constraints if clause["kind"] == "GROUPS" for value in clause["ids"]}
            query = query.where(VolunteerGroup.id.in_(ids))
        from sqlalchemy import tuple_

        rows = list(self.db.scalars(query))
        configs = (
            {
                (row.group_id, row.version): row
                for row in self.db.scalars(
                    select(GroupConfigVersion).where(
                        GroupConfigVersion.college_id == cid,
                        tuple_(GroupConfigVersion.group_id, GroupConfigVersion.version).in_(
                            {(row.id, row.config_version) for row in rows}
                        ),
                    )
                )
            }
            if rows
            else {}
        )
        return [
            self._dto(
                row,
                group_config=configs.get((row.id, row.config_version)),
                group_config_loaded=True,
            )
            for row in rows
        ]

    def group_references(self, actor, cid, gid):
        from app.modules.academic.models import AdministrativeClass, TeachingClass
        from app.modules.identity.resource_scope import resolve_scope
        scope = resolve_scope(self.db, actor, cid, "volunteer.group.read")
        if not scope.permits_group(gid):
            raise NotFoundError()
        self._resource(VolunteerGroup, cid, gid)
        classes = select(AdministrativeClass).where(AdministrativeClass.college_id == cid)
        teaching = select(TeachingClass).where(TeachingClass.college_id == cid)
        types = select(CourseType).where(
            CourseType.college_id == cid, CourseType.deleted_at.is_(None)
        )
        if not scope.unrestricted:
            bounds = [clause.get("bounds", {}).get(str(gid), {}) for clause in scope.constraints
                      if clause["kind"] == "GROUPS" and str(gid) in clause["ids"]]
            type_ids = {int(v) for bound in bounds for v in bound.get("course_type_ids", [])}
            types = types.where(CourseType.id.in_(type_ids))
            if not any(bound.get("class_mode") == "ALL_AUTHORIZED" for bound in bounds):
                class_ids = {int(v) for bound in bounds for v in bound.get("class_ids", [])}
                classes = classes.where(AdministrativeClass.id.in_(class_ids))
                # Selectors expose metadata only, never rosters or enrollment facts.
        # The check-target selector obeys frozen ceilings. Conflict exceptions need
        # same-college catalog metadata even for courses the group does not inspect.
        # No enrollment, student, schedule or roster facts are exposed here.
        conflicts = list(self.db.scalars(select(CourseType).where(
            CourseType.college_id == cid, CourseType.deleted_at.is_(None),
            CourseType.status == "ACTIVE",
        ).order_by(CourseType.id)))
        return {"conflict_types": [self._dto(row) for row in conflicts], "types": [self._dto(row) for row in self.db.scalars(types.order_by(CourseType.id))],
                "classes": [{"id": str(row.id), "class_name": row.class_name, "status": row.status}
                            for row in self.db.scalars(classes.order_by(AdministrativeClass.id))],
                "teaching_classes": [{"id": str(row.id), "class_name": row.class_name,
                    "semester_id": str(row.semester_id), "status": row.status}
                    for row in self.db.scalars(teaching.order_by(TeachingClass.id))]}

    def _authorize_group(self, actor, cid, action, gid, *, write=False, proposed=None):
        from app.modules.identity.resource_scope import resolve_scope
        scope = resolve_scope(self.db, actor, cid, action, write=write)
        if not scope.permits_group(gid):
            raise NotFoundError("组不在授权范围")
        group = self._resource(VolunteerGroup, cid, gid)
        if write and not scope.unrestricted:
            config = proposed or self._dto(group)["configuration"] or {}
            if not any(
                clause["kind"] == "GROUPS" and str(gid) in clause["ids"]
                and set(config.get("course_type_ids", [])) <= set(clause.get("bounds", {}).get(str(gid), {}).get("course_type_ids", []))
                and (clause.get("bounds", {}).get(str(gid), {}).get("class_mode") == "ALL_AUTHORIZED"
                     or (config.get("class_mode") == "SPECIFIC" and set(config.get("class_ids", [])) <= set(clause.get("bounds", {}).get(str(gid), {}).get("class_ids", []))))
                for clause in scope.constraints
            ):
                raise PermissionDeniedError("组查课范围超出授权时上限，请超管重新授权")
        return self.repo.college(cid, lock=write)

    def _owner(self, user_id):
        user = self.db.get(UserAccount, int(user_id))
        if user is None or user.status != "ACTIVE":
            raise NotFoundError("负责人账号无效")

    @staticmethod
    def _dates(row):
        if row.starts_on and row.ends_on and row.starts_on > row.ends_on:
            raise AppError(ErrorCode.VALIDATION_ERROR, "结束日期不能早于开始日期", 422)

    @atomic_write
    def create_group(self, actor, cid, data):
        body = validated(GroupCreate, data)
        college = self._authorize(actor, cid, "volunteer.group.manage", write=True)
        self._owner(body.owner_user_id)
        row = VolunteerGroup(
            college_id=cid,
            normalized_name=normalized_name(body.name),
            **body.model_dump(exclude={"owner_user_id"}),
            owner_user_id=int(body.owner_user_id),
        )
        self._dates(row)
        self.db.add(row)
        college.configuration_revision += 1
        return self._commit(actor, "campus.group.create", row)

    @atomic_write
    def update_group(self, actor, cid, rid, data):
        body = validated(GroupUpdate, data)
        college = self._authorize_group(actor, cid, "volunteer.group.manage", rid, write=True)
        row = self._resource(VolunteerGroup, cid, rid)
        self._version(row, body.lock_version)
        if body.owner_user_id is not None and int(body.owner_user_id) != row.owner_user_id:
            raise ConflictError(message="负责人变更请使用交接预览与确认，以同步负责人专属授权")
        from app.modules.identity.resource_scope import resolve_scope
        impact_scope = resolve_scope(self.db, actor, cid, "volunteer.group.manage", write=True)
        changes = {
            k: v
            for k, v in body.model_dump(exclude_unset=True).items()
            if k not in {"lock_version", "future_impact_revision"}
            and str(getattr(row, k)) != str(v)
        }
        if not changes:
            return self._dto(row)
        if {"status", "starts_on", "ends_on"} & changes.keys():
            confirm_impact(
                self.db, cid, "group", row, body.future_impact_revision, resource_scope=impact_scope
            )
        before = self._dto(row)
        for key, value in body.model_dump(exclude_unset=True).items():
            if key not in {"lock_version", "future_impact_revision"}:
                setattr(row, key, int(value) if key == "owner_user_id" and value else value)
        self._owner(row.owner_user_id)
        self._dates(row)
        row.normalized_name = normalized_name(row.name)
        if changes.get("status") == "ACTIVE":
            config = before["configuration"]
            if not config or not config["course_type_ids"]:
                raise ConflictError(message="组缺少已发布的查课范围")
            for type_id in config["course_type_ids"]:
                if self._resource(CourseType, cid, int(type_id)).status != "ACTIVE":
                    raise ConflictError(message="组引用已停用类型，需调整配置")
        row.lock_version += 1
        if row.status != before["status"]:
            college.configuration_revision += 1
        return self._commit(actor, "campus.group.update", row, before)

    @atomic_write
    def publish_group(self, actor, cid, rid, data, *, semester_id=None):
        body = validated(GroupPublish, data)
        college = self._authorize_group(actor, cid, "volunteer.config.publish", rid, write=True,
                                        proposed=body.model_dump())
        row = self._resource(VolunteerGroup, cid, rid)
        self._version(row, body.lock_version)
        from app.modules.identity.resource_scope import resolve_scope
        impact_scope = resolve_scope(self.db, actor, cid, "volunteer.config.publish", write=True)
        if not body.course_type_ids:
            raise ConflictError(message="必须明确选择查课类型，留空不表示全部")
        from app.modules.academic.models import AdministrativeClass, TeachingClass

        for class_id in body.class_ids:
            self._resource(AdministrativeClass, cid, int(class_id))
        for teaching_id in body.teaching_class_overrides:
            self._resource(TeachingClass, cid, int(teaching_id))
        type_ids = set(body.course_type_ids)
        for value in sorted(type_ids):
            if not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63:
                raise AppError(ErrorCode.VALIDATION_ERROR, "类型标识无效", 422)
            kind = self.repo.resource(CourseType, cid, int(value))
            if kind is None:
                raise NotFoundError()
            if kind.deleted_at is not None:
                raise ConflictError(message=(
                    "课程类型已删除，请刷新并移除对应的查课范围或冲突规则后重试"
                ))
            if kind.status != "ACTIVE":
                raise ConflictError(message="类型已停用")
        from app.modules.volunteer.preparation_models import (
            GroupSemesterPreparation,
            semester_group_config,
        )

        prepared = None
        if semester_id is not None:
            from app.modules.academic.models import Semester

            semester = self.db.scalar(
                select(Semester)
                .where(Semester.id == semester_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if semester is None:
                raise NotFoundError("学期不存在")
            if semester.status != "ACTIVE":
                raise ConflictError(message="该学期已归档，不可修改排班规则")
            prepared = self.db.scalar(
                select(GroupSemesterPreparation)
                .where(
                    GroupSemesterPreparation.group_id == rid,
                    GroupSemesterPreparation.college_id == cid,
                    GroupSemesterPreparation.semester_id == semester_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            current = semester_group_config(self.db, row, semester_id)
            before = self._dto(row, group_config=current, group_config_loaded=True)
        else:
            before = self._dto(row)
        configuration = body.model_dump(
            mode="json", exclude={"lock_version", "future_impact_revision"}
        )
        configuration["course_type_ids"] = sorted(body.course_type_ids, key=int)
        configuration["class_ids"] = sorted(body.class_ids, key=int)
        existing = before["configuration"]
        if existing is not None:
            normalized = {
                **GroupPublish(lock_version=1).model_dump(
                    mode="json", exclude={"lock_version", "future_impact_revision"}
                ),
                **existing,
            }
            normalized["course_type_ids"] = sorted(normalized["course_type_ids"], key=int)
            normalized["class_ids"] = sorted(normalized["class_ids"], key=int)
            if normalized == configuration:
                return before
        impact = confirm_impact(
            self.db,
            cid,
            "group",
            row,
            body.future_impact_revision,
            resource_scope=impact_scope,
            semester_id=semester_id,
            inherited_only=semester_id is None,
        )
        next_version = (
            self.db.scalar(
                select(func.max(GroupConfigVersion.version)).where(
                    GroupConfigVersion.group_id == row.id
                )
            )
            or 0
        ) + 1
        if semester_id is None or row.config_version == 0:
            row.config_version = next_version
        row.lock_version += 1
        college.configuration_revision += 1
        config = GroupConfigVersion(
            college_id=cid,
            group_id=rid,
            version=next_version,
            configuration=configuration,
            published_by=actor.id,
        )
        self.db.add(config)
        self.db.flush()
        # 新版本只记录被查课程类型，冲突统一采用默认规则。
        self.db.add_all(
            [
                GroupScopeType(
                    college_id=cid,
                    config_id=config.id,
                    course_type_id=int(value),
                    is_inspection_scope=value in body.course_type_ids,
                )
                for value in type_ids
            ]
        )
        if semester_id is not None:
            if prepared is None:
                self.db.add(
                    GroupSemesterPreparation(
                        college_id=cid,
                        group_id=rid,
                        semester_id=semester_id,
                        source_semester_id=semester_id,
                        config_id=config.id,
                    )
                )
            else:
                prepared.config_id = config.id
                prepared.lock_version += 1
        return self._commit(
            actor,
            "campus.group.publish",
            row,
            before,
            impact_task_ids=[int(t) for t in impact["retained_future_task_ids"]],
            group_config=config,
        )

    @atomic_write
    def delete_group(self, actor, cid, rid, version, deletion_revision=None):
        from app.modules.organization.resource_deletion import delete_resource
        return delete_resource(self, actor, cid, "group", rid, version, deletion_revision)

    def _legacy_delete_group(self, actor, cid, rid, version):
        college = self._authorize(actor, cid, "volunteer.group.manage", write=True)
        row = self._resource(VolunteerGroup, cid, rid)
        self._version(row, version)
        before = self._dto(row)
        from app.modules.organization.deletion import remove_unused_group_configuration
        remove_unused_group_configuration(self.db, row)
        self.db.delete(row)
        college.configuration_revision += 1
        self._commit(
            actor,
            "campus.group.delete",
            None,
            before,
            resource_id=str(rid),
            resource_type="VolunteerGroup",
        )
