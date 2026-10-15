"""Template maintenance never writes college drafts or formal time versions."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.school_time_models import SchoolTimeTemplate, SchoolTimeTemplateVersion
from app.modules.academic.school_time_schemas import (
    TemplateContent,
    TemplateImport,
    TemplateRevision,
    TemplateStatus,
)
from app.modules.academic.time_models import CollegeTimeProfile
from app.modules.academic.time_profiles import ProfileDraft, TimeProfileService
from app.modules.organization.models import College, School
from app.modules.organization.service import CampusService, atomic_write, normalized_name, validated


class SchoolTimeTemplateService:
    def __init__(self, db, actor, request_id=None):
        self.db, self.actor = db, actor
        self.campus = CampusService(db, request_id)

    def _school(self, sid, *, write=False):
        if write:
            self.campus._super(self.actor)
        elif not self.campus._actor(self.actor):
            raise PermissionDeniedError("仅超管可管理学校模板，请通过学院目录查看")
        school = self.db.scalar(
            select(School).where(School.id == sid).with_for_update(read=not write)
        )
        if school is None:
            raise NotFoundError("学校不存在")

    def _template(self, sid, tid, *, lock=False):
        row = self.db.scalar(
            select(SchoolTimeTemplate)
            .where(SchoolTimeTemplate.id == tid, SchoolTimeTemplate.school_id == sid)
            .with_for_update(read=not lock)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("模板不属于本学校")
        return row

    def _catalog(self, sid):
        rows = self.db.execute(
            select(SchoolTimeTemplate, SchoolTimeTemplateVersion)
            .join(
                SchoolTimeTemplateVersion,
                (SchoolTimeTemplate.id == SchoolTimeTemplateVersion.template_id)
                & (SchoolTimeTemplateVersion.version == SchoolTimeTemplate.latest_version),
            )
            .where(SchoolTimeTemplate.school_id == sid)
            .order_by(SchoolTimeTemplate.id)
        )
        return [
            {**self.campus._dto(row), "latest": self.campus._dto(version)} for row, version in rows
        ]

    def catalog(self, sid):
        self._school(sid)
        return self._catalog(sid)

    def college_catalog(self, cid):
        college = self.campus._authorize(self.actor, cid, "academic.read")
        return self._catalog(college.school_id)

    def versions(self, sid, tid):
        self._school(sid)
        self._template(sid, tid)
        return [
            self.campus._dto(v)
            for v in self.db.scalars(
                select(SchoolTimeTemplateVersion)
                .where(SchoolTimeTemplateVersion.template_id == tid)
                .order_by(SchoolTimeTemplateVersion.version.desc())
            )
        ]

    def _append(self, row, body):
        self.db.add(
            SchoolTimeTemplateVersion(
                template_id=row.id,
                version=row.latest_version,
                name=body.name,
                periods=[p.model_dump(mode="json") for p in body.periods],
                published_by=self.actor.id,
            )
        )

    @atomic_write
    def create(self, sid, data):
        body = validated(TemplateContent, data)
        self._school(sid, write=True)
        row = SchoolTimeTemplate(
            school_id=sid,
            name=body.name,
            normalized_name=normalized_name(body.name),
            latest_version=1,
        )
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(message="学校模板名称重复，无法创建") from exc
        self._append(row, body)
        return self.campus._commit(self.actor, "academic.school_time_template.create", row)

    @atomic_write
    def revise(self, sid, tid, data):
        body = validated(TemplateRevision, data)
        self._school(sid, write=True)
        row = self._template(sid, tid, lock=True)
        self.campus._version(row, body.lock_version)
        if row.status != "ACTIVE":
            raise ConflictError(message="停用模板须先恢复后才能新增版本")
        before = self.campus._dto(row)
        row.name, row.normalized_name = body.name, normalized_name(body.name)
        row.latest_version += 1
        row.lock_version += 1
        self._append(row, body)
        return self.campus._commit(self.actor, "academic.school_time_template.revise", row, before)

    @atomic_write
    def set_status(self, sid, tid, data):
        body = validated(TemplateStatus, data)
        self._school(sid, write=True)
        row = self._template(sid, tid, lock=True)
        self.campus._version(row, body.lock_version)
        before = self.campus._dto(row)
        row.status = body.status
        row.lock_version += 1
        return self.campus._commit(self.actor, "academic.school_time_template.status", row, before)

    @atomic_write
    def import_draft(self, cid, sid, data):
        body = validated(TemplateImport, data)
        profiles = TimeProfileService(self.db, self.actor, cid, sid)
        profiles._scope(write=True)
        college = self.db.get(College, cid)
        # Parent lock serializes import with stop/revise. An explicit old version
        # remains importable while the template is active; never silently use latest.
        source = self.db.get(SchoolTimeTemplateVersion, int(body.template_version_id))
        if source is None:
            raise NotFoundError("模板版本不存在")
        template = self._template(college.school_id, source.template_id)
        if template.status != "ACTIVE":
            raise ConflictError(message="模板已停用，不能新建引用；既有学院作息继续有效")
        configuration = profiles._configuration(
            validated(
                ProfileDraft,
                {
                    "name": body.name,
                    "configuration": {
                        "effective_from": body.effective_from,
                        "periods": source.periods,
                    },
                },
            )
        )
        row = CollegeTimeProfile(
            college_id=cid,
            semester_id=sid,
            name=body.name,
            normalized_name=normalized_name(body.name),
            draft_configuration=configuration,
            source_template_version_id=source.id,
        )
        self.db.add(row)
        return self.campus._commit(self.actor, "academic.school_time_template.import", row)

    def updates(self, cid, sid):
        TimeProfileService(self.db, self.actor, cid, sid)._scope()
        rows = self.db.execute(
            select(CollegeTimeProfile, SchoolTimeTemplateVersion, SchoolTimeTemplate)
            .join(
                SchoolTimeTemplateVersion,
                CollegeTimeProfile.source_template_version_id == SchoolTimeTemplateVersion.id,
            )
            .join(
                SchoolTimeTemplate, SchoolTimeTemplateVersion.template_id == SchoolTimeTemplate.id
            )
            .where(
                CollegeTimeProfile.college_id == cid,
                CollegeTimeProfile.semester_id == sid,
                CollegeTimeProfile.status != "ARCHIVED",
            )
            .order_by(CollegeTimeProfile.id)
        )
        return [
            {
                "profile_id": str(profile.id),
                "profile_name": profile.name,
                "template_id": str(template.id),
                "template_name": template.name,
                "source_template_version_id": str(source.id),
                "source_version": source.version,
                "latest_version": template.latest_version,
                "template_status": template.status,
                "update_available": template.latest_version > source.version,
                "message": "学校模板有更新，可引用新版为新草稿；当前作息保持不变。"
                if template.latest_version > source.version
                else "学校模板已停用，当前作息保持不变。",
            }
            for profile, source, template in rows
            if template.latest_version > source.version or template.status == "INACTIVE"
        ]
