"""Explicit school-default adoption with a three-way merge of college exceptions."""

from copy import deepcopy
from datetime import date

from pydantic import Field
from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester
from app.modules.academic.time_models import SchoolSemesterDefault
from app.modules.academic.time_schemas import TimeConfiguration
from app.modules.academic.time_service import CollegeTimeService
from app.modules.audit.models import AuditLog
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.organization.models import College, School
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import CampusService, atomic_write, validated


class TemplatePublish(TimeConfiguration):
    name: str = Field(min_length=1, max_length=128)
    period_template_version_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")


class TemplateAdoption(StrictModel):
    template_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    effective_from: date
    confirm_existing_tasks: bool = False


class TemplateAdopt(TemplateAdoption):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def merge_defaults(incoming, local, base):
    """Only fields still equal to their adopted baseline follow a new default.

    An explicit college deletion also counts as an exception. Without provenance,
    retain all local entries conservatively rather than guessing their origins.
    """
    merged = deepcopy(incoming)
    retained = []
    for field, key in (("periods", "slot_id"), ("calendar", "date")):
        target = {str(v[key]): v for v in incoming.get(field, [])}
        ours = {str(v[key]): v for v in local.get(field, [])}
        before = {str(v[key]): v for v in base.get(field, [])}
        for identity in sorted(set(ours) | set(before)):
            if ours.get(identity) != before.get(identity):
                if identity in ours:
                    target[identity] = deepcopy(ours[identity])
                else:
                    target.pop(identity, None)
                retained.append(f"{field}:{identity}")
        merged[field] = sorted(
            target.values(), key=lambda v: v["period_no"] if field == "periods" else v["date"]
        )
    if local.get("grid_slot_mapping", {}) != base.get("grid_slot_mapping", {}):
        merged["grid_slot_mapping"] = deepcopy(local.get("grid_slot_mapping", {}))
        retained.append("grid_slot_mapping")
    return merged, retained


class SchoolTimeService:
    def __init__(self, db, actor, sid):
        self.db, self.actor, self.sid = db, actor, sid
        self.campus = CampusService(db)

    def _semester(self, *, lock=False):
        stmt = (
            select(Semester)
            .where(Semester.id == self.sid)
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update()
        row = self.db.scalar(stmt)
        if row is None:
            raise NotFoundError("学期不存在")
        if row.status != "ACTIVE":
            raise ConflictError(message="归档学期不能修改默认资料")
        return row

    def list(self, cid=None):
        if cid is None:
            self.campus._super(self.actor)
        else:
            resolve_scope(self.db, self.actor, cid, "academic.read")
        return [
            self.campus._dto(row)
            for row in self.db.scalars(
                select(SchoolSemesterDefault)
                .where(SchoolSemesterDefault.semester_id == self.sid)
                .order_by(SchoolSemesterDefault.version)
            )
        ]

    @atomic_write
    def publish(self, data):
        self.campus._super(self.actor)
        body = validated(TemplatePublish, data)
        school = self.db.scalar(select(School).with_for_update())
        if school is None:
            raise NotFoundError("请先建立学校")
        semester = self._semester(lock=True)
        if body.period_template_version_id:
            from app.modules.academic.school_time_models import (
                SchoolTimeTemplate,
                SchoolTimeTemplateVersion,
            )

            version = self.db.get(SchoolTimeTemplateVersion, int(body.period_template_version_id))
            template = self.db.get(SchoolTimeTemplate, version.template_id) if version else None
            if template is None or template.school_id != school.id or template.status != "ACTIVE":
                raise NotFoundError("所选学校节次模板已停用或不存在")
            periods = validated(
                TimeConfiguration,
                {
                    **body.model_dump(exclude={"name", "period_template_version_id"}),
                    "periods": version.periods,
                },
            ).periods
            if [p.model_dump() for p in periods] != [p.model_dump() for p in body.periods]:
                raise ConflictError(
                    message="下方节次已修改，不能仍声称来自原学校模板，请重新选取模板或按自定义节次发布"
                )
        if not semester.start_date <= body.effective_from <= semester.end_date or any(
            not semester.start_date <= c.date <= semester.end_date
            or (c.source_teaching_week or 1) > semester.total_weeks
            for c in body.calendar
        ):
            raise ConflictError(message="默认资料日期或来源周次超出学期")
        version = (
            self.db.scalar(
                select(func.max(SchoolSemesterDefault.version)).where(
                    SchoolSemesterDefault.school_id == school.id,
                    SchoolSemesterDefault.semester_id == self.sid,
                )
            )
            or 0
        ) + 1
        row = SchoolSemesterDefault(
            school_id=school.id,
            semester_id=self.sid,
            version=version,
            name=body.name,
            configuration=body.model_dump(
                mode="json",
                exclude={"name", "confirm_existing_tasks", "period_template_version_id"},
            ),
            published_by=self.actor.id,
            period_template_version_id=int(body.period_template_version_id)
            if body.period_template_version_id
            else None,
        )
        self.db.add(row)
        self.db.flush()
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="academic.school_time.publish",
                resource_type="school_semester_default",
                resource_id=str(row.id),
                after_json=self.campus._dto(row),
            )
        )
        self.db.commit()
        return self.campus._dto(row)

    def _adoption(self, cid, data, *, lock=False):
        body = validated(TemplateAdoption, data)
        resolve_scope(self.db, self.actor, cid, "academic.manage", write=lock)
        college = self.db.get(College, cid)
        template = self.db.get(SchoolSemesterDefault, int(body.template_id))
        if (
            template is None
            or template.semester_id != self.sid
            or template.school_id != college.school_id
        ):
            raise NotFoundError("模板不属于当前学校和学期")
        service = CollegeTimeService(self.db, self.actor, cid, self.sid)
        versions = service._versions(lock=lock)
        config, retained = deepcopy(template.configuration), []
        if versions:
            local = versions[-1]
            source = (
                self.db.get(SchoolSemesterDefault, local.source_template_id)
                if local.source_template_id
                else None
            )
            config, retained = merge_defaults(
                config, local.configuration, source.configuration if source else {}
            )
        config["effective_from"] = body.effective_from.isoformat()
        config["confirm_existing_tasks"] = body.confirm_existing_tasks
        preview = service._preview(config, lock=lock)[3]
        return (
            service,
            config,
            {
                **preview,
                "revision": fingerprint({"template": template.id, "preview": preview["revision"]}),
                "time_revision": preview["revision"],
                "template_id": str(template.id),
                "retained_college_exceptions": retained,
                "configuration": config,
            },
        )

    def preview_adoption(self, cid, data):
        return self._adoption(cid, data)[2]

    @atomic_write
    def adopt(self, cid, data):
        body = validated(TemplateAdopt, data)
        service, config, preview = self._adoption(
            cid, body.model_dump(exclude={"revision"}), lock=True
        )
        if preview["revision"] != body.revision:
            raise ConflictError(message="模板、学院资料、任务或权限已变化，请重新预览")
        result = service.publish(
            config, preview["time_revision"], source_template_id=int(body.template_id), commit=False
        )
        self.db.commit()
        return {
            **result,
            "template_id": body.template_id,
            "retained_college_exceptions": preview["retained_college_exceptions"],
        }
