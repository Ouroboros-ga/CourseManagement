"""Prepare a new semester explicitly without cloning identities or support grants."""

from copy import deepcopy
from datetime import date

from pydantic import Field, model_validator
from sqlalchemy import func, select

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import TeachingClass, VolunteerQualification
from app.modules.academic.qualification_policy import qualified_on
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.models import GroupConfigVersion, GroupScopeType
from app.modules.volunteer.preparation_models import GroupSemesterPreparation, semester_group_config


class SemesterPreparation(StrictModel):
    source_semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    member_ids: list[str] = Field(default_factory=list, max_length=200)
    effective_from: date
    effective_to: date
    teaching_class_mapping: dict[str, str] = Field(default_factory=dict, max_length=500)

    @model_validator(mode="after")
    def valid(self):
        ids = [
            self.source_semester_id,
            *self.member_ids,
            *self.teaching_class_mapping.keys(),
            *self.teaching_class_mapping.values(),
        ]
        if any(not x.isascii() or not x.isdecimal() or not 0 < int(x) < 2**63 for x in ids):
            raise ValueError("资源标识无效")
        if (
            len(set(self.member_ids)) != len(self.member_ids)
            or len(set(self.teaching_class_mapping.values())) != len(self.teaching_class_mapping)
            or self.effective_from >= self.effective_to
        ):
            raise ValueError("成员不能重复，有效期结束须晚于开始")
        return self


class PreparationConfirm(SemesterPreparation):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class GroupPreparationService:
    def __init__(self, db, actor, cid, gid, sid):
        self.db, self.actor, self.cid, self.gid, self.sid = db, actor, cid, gid, sid
        self.members = GroupMemberService(db, actor, cid, gid)

    def _preview(self, data):
        body = validated(SemesterPreparation, data)
        if int(body.source_semester_id) == self.sid:
            raise ConflictError(message="请选择不同的来源学期与目标学期")
        college, group = self.members._group(
            "volunteer.member.manage", write=True, semester_id=self.sid
        )
        self.members._scope("volunteer.config.publish", write=True)
        from app.modules.academic.models import Semester

        semester = self.db.get(Semester, self.sid)
        if self.db.get(Semester, int(body.source_semester_id)) is None:
            raise NotFoundError("来源学期不存在")
        from app.modules.identity.role_scope import business_today
        from app.modules.inspection.models import InspectionTask

        if self.db.scalar(
            select(InspectionTask.id)
            .where(
                InspectionTask.college_id == self.cid,
                InspectionTask.group_id == self.gid,
                InspectionTask.semester_id == self.sid,
                InspectionTask.inspection_date >= business_today(),
                InspectionTask.canceled_at.is_(None),
            )
            .limit(1)
        ):
            raise ConflictError(
                message="目标学期已有本组今日或未来有效任务，准备操作不覆盖其规则；新增成员请使用成员维护，规则变更先处置现有任务"
            )
        from datetime import timedelta

        if (
            semester is None
            or semester.status != "ACTIVE"
            or not (
                semester.start_date
                <= body.effective_from
                < body.effective_to
                <= semester.end_date + timedelta(days=1)
            )
        ):
            raise ConflictError(message="目标学期未开放或成员有效期超出学期")
        source = semester_group_config(self.db, group, int(body.source_semester_id))
        if source is None:
            raise ConflictError(message="来源组织尚无已发布规则")
        config = deepcopy(source.configuration)
        overrides = config.get("teaching_class_overrides", {})
        if set(body.teaching_class_mapping) != set(overrides):
            raise ConflictError(message="请为来源规则中每个教学班例外明确映射目标教学班")
        mapped = list(
            self.db.scalars(
                select(TeachingClass).where(
                    TeachingClass.college_id == self.cid,
                    TeachingClass.semester_id == self.sid,
                    TeachingClass.status == "ACTIVE",
                    TeachingClass.id.in_([int(x) for x in body.teaching_class_mapping.values()]),
                )
            )
        )
        if {str(t.id) for t in mapped} != set(body.teaching_class_mapping.values()):
            raise NotFoundError("目标教学班不属于本院目标学期或已停用")
        types = set(config["course_type_ids"]) | set(config.get("type_overrides", {}))
        active_types = list(
            self.db.scalars(
                select(CourseType).where(
                    CourseType.college_id == self.cid,
                    CourseType.id.in_([int(x) for x in types]),
                    CourseType.status == "ACTIVE",
                )
            )
        )
        if {str(t.id) for t in active_types} != types:
            raise ConflictError(message="来源规则含已停用课程类型，请先整理组织规则")
        config["teaching_class_overrides"] = {
            body.teaching_class_mapping[k]: v for k, v in overrides.items()
        }
        self.members.campus._authorize_group(
            self.actor, self.cid, "volunteer.config.publish", self.gid, write=True, proposed=config
        )
        source_members = list(
            self.db.scalars(
                select(VolunteerGroupMember)
                .where(
                    VolunteerGroupMember.college_id == self.cid,
                    VolunteerGroupMember.group_id == self.gid,
                    VolunteerGroupMember.semester_id == int(body.source_semester_id),
                    VolunteerGroupMember.id.in_([int(x) for x in body.member_ids]),
                    VolunteerGroupMember.status == "ACTIVE",
                )
                .order_by(VolunteerGroupMember.id)
            )
        )
        if {str(m.id) for m in source_members} != set(body.member_ids):
            raise NotFoundError("所选成员不是本组织来源学期的有效记录")
        prepared, items, qualifications = [], [], []
        for member in source_members:
            qualification = self.db.scalar(
                select(VolunteerQualification).where(
                    VolunteerQualification.student_id == member.student_id,
                    VolunteerQualification.semester_id == self.sid,
                )
            )
            qualifications.append(
                self.members.campus._dto(qualification) if qualification else None
            )
            item = {
                "source_member_id": str(member.id),
                "student_id": str(member.student_id),
                "ready": False,
            }
            try:
                row, _, _ = self.members._prepare_create(
                    {
                        "student_id": str(member.student_id),
                        "semester_id": str(self.sid),
                        "effective_from": body.effective_from,
                        "effective_to": body.effective_to,
                    }
                )
                if not qualified_on(self.db, qualification, body.effective_from):
                    raise ConflictError(message="目标学期志愿者资格未就绪，请先维护资格")
                prepared.append(row)
                item["ready"] = True
            except AppError as exc:
                item["reason"] = str(exc)
            items.append(item)
        target = self.db.scalar(
            select(GroupSemesterPreparation)
            .where(
                GroupSemesterPreparation.group_id == self.gid,
                GroupSemesterPreparation.semester_id == self.sid,
            )
            .with_for_update()
        )
        support = list(
            self.db.scalars(
                select(VolunteerGroupSupport)
                .where(
                    VolunteerGroupSupport.college_id == self.cid,
                    VolunteerGroupSupport.group_id == self.gid,
                    VolunteerGroupSupport.semester_id == self.sid,
                )
                .with_for_update()
            )
        )
        preview = {
            "configuration": config,
            "items": items,
            "can_confirm": all(i["ready"] for i in items),
            "source_config_id": str(source.id),
            "identities_reused": True,
            "support_grants_copied": False,
        }
        preview["revision"] = fingerprint(
            {
                "actor": self.actor.id,
                "body": body.model_dump(),
                "target_semester": self.sid,
                "college": [college.configuration_revision, college.authorization_revision],
                "group": self.members.campus._dto(group),
                "source": self.members.campus._dto(source),
                "members": [self.members.campus._dto(m) for m in source_members],
                "target": self.members.campus._dto(target) if target else None,
                "qualifications": qualifications,
                "support": [self.members.campus._dto(s) for s in support],
                "preview": preview,
            }
        )
        return body, college, group, target, prepared, preview

    def preview(self, data):
        return self._preview(data)[5]

    def source(self, source_sid, *, include_teaching_classes=True):
        _, group = self.members._group("volunteer.group.read")
        from app.modules.academic.models import Semester

        if self.db.get(Semester, source_sid) is None or self.db.get(Semester, self.sid) is None:
            raise NotFoundError("来源或目标学期不存在")
        config = semester_group_config(self.db, group, source_sid)
        if config is None:
            raise ConflictError(message="本组织尚无已发布规则")
        old_ids = [int(x) for x in config.configuration.get("teaching_class_overrides", {})]
        teaching = (
            list(
                self.db.scalars(
                    select(TeachingClass)
                    .where(
                        TeachingClass.college_id == self.cid,
                        (
                            (TeachingClass.semester_id == self.sid)
                            & (TeachingClass.status == "ACTIVE")
                        )
                        | TeachingClass.id.in_(old_ids),
                    )
                    .order_by(TeachingClass.id)
                    .limit(5000)
                )
            )
            if include_teaching_classes
            else []
        )
        return {
            "configuration": config.configuration,
            "source_config_id": str(config.id),
            "members": self.members.members(source_sid),
            "teaching_classes": [
                {"id": str(t.id), "name": t.class_name, "semester_id": str(t.semester_id)}
                for t in teaching
            ],
            "uses_semester_specific_rules": self.db.scalar(
                select(GroupSemesterPreparation.id).where(
                    GroupSemesterPreparation.group_id == self.gid,
                    GroupSemesterPreparation.semester_id == source_sid,
                )
            )
            is not None,
        }

    @atomic_write
    def confirm(self, data):
        body = validated(PreparationConfirm, data)
        _, college, group, target, members, preview = self._preview(
            body.model_dump(exclude={"revision"})
        )
        if body.revision != preview["revision"] or not preview["can_confirm"]:
            raise ConflictError(message="学期准备资料已变化或成员未就绪，请重新预览")
        version = (
            self.db.scalar(
                select(func.max(GroupConfigVersion.version)).where(
                    GroupConfigVersion.group_id == self.gid
                )
            )
            or 0
        ) + 1
        config = GroupConfigVersion(
            college_id=self.cid,
            group_id=self.gid,
            version=version,
            configuration=preview["configuration"],
            published_by=self.actor.id,
        )
        self.db.add(config)
        self.db.flush()
        type_ids = set(config.configuration["course_type_ids"]) | set(
            config.configuration.get("type_overrides", {})
        )
        self.db.add_all(
            [
                GroupScopeType(
                    config_id=config.id,
                    college_id=self.cid,
                    course_type_id=int(t),
                    is_inspection_scope=t in config.configuration["course_type_ids"],
                )
                for t in type_ids
            ]
        )
        if target is None:
            target = GroupSemesterPreparation(
                college_id=self.cid,
                group_id=self.gid,
                semester_id=self.sid,
                source_semester_id=int(body.source_semester_id),
                config_id=config.id,
            )
            self.db.add(target)
        else:
            target.config_id = config.id
            target.source_semester_id = int(body.source_semester_id)
            target.lock_version += 1
        for member in members:
            self.members._save(
                member, college, group, "volunteer.semester.member_prepare", commit=False
            )
        group.lock_version += 1
        college.configuration_revision += 1
        self.db.flush()
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="volunteer.semester.prepare",
                resource_type="group_semester_preparation",
                resource_id=str(target.id),
                after_json=scoped_snapshot(
                    {**preview, "target_semester_id": str(self.sid)}, self.cid
                ),
            )
        )
        self.db.commit()
        return {
            "id": str(target.id),
            "config_id": str(config.id),
            "created_members": len(members),
            "group_id": str(group.id),
            "support_grants_copied": False,
        }
