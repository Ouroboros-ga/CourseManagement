"""Named college time drafts; published versions remain immutable."""
from pydantic import Field, field_validator
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester, TeachingClass
from app.modules.academic.time_models import CollegeTimeProfile
from app.modules.academic.time_schemas import TimeConfiguration
from app.modules.academic.time_service import CollegeTimeService
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.organization.future_impact import future_impact
from app.modules.organization.impact_service import capture_impacts
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import CampusService, atomic_write, normalized_name, validated


class ProfileDraft(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    configuration: TimeConfiguration


class ProfileSave(ProfileDraft):
    lock_version: int = Field(ge=1)


class ProfilePublish(StrictModel):
    lock_version: int = Field(ge=1)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_existing_tasks: bool = False


class ProfileSelection(StrictModel):
    profile_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("profile_id")
    @classmethod
    def valid_id(cls, value):
        if value is not None and int(value) >= 2**63:
            raise ValueError("作息方案标识超出范围")
        return value


class ProfileBinding(ProfileSelection):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class TimeProfileService:
    def __init__(self, db, actor, cid, sid):
        self.db, self.actor, self.cid, self.sid = db, actor, cid, sid
        self.campus = CampusService(db)

    def _scope(self, *, write=False):
        scope = resolve_scope(self.db, self.actor, self.cid, "academic.manage" if write else "academic.read", write=write)
        semester = self.db.scalar(select(Semester).where(Semester.id == self.sid).with_for_update(read=not write).execution_options(populate_existing=True))
        if semester is None:
            raise NotFoundError("学期不存在")
        if write and semester.status != "ACTIVE":
            raise ConflictError(message="学期已停用")
        return scope

    def _row(self, pid, *, lock=False):
        row = self.db.scalar(select(CollegeTimeProfile).where(CollegeTimeProfile.id == pid,
            CollegeTimeProfile.college_id == self.cid, CollegeTimeProfile.semester_id == self.sid).with_for_update(read=not lock).execution_options(populate_existing=True))
        if row is None:
            raise NotFoundError("作息方案不属于本院本学期")
        return row

    def list(self):
        self._scope()
        return [self.campus._dto(row) for row in self.db.scalars(select(CollegeTimeProfile).where(
            CollegeTimeProfile.college_id == self.cid, CollegeTimeProfile.semester_id == self.sid).order_by(CollegeTimeProfile.id))]

    def _configuration(self, body):
        if body.configuration.calendar or body.configuration.grid_slot_mapping:
            raise ConflictError(message="方案只管理上课时段，校历与教务映射使用学院默认配置")
        semester = self.db.get(Semester, self.sid)
        if not semester.start_date <= body.configuration.effective_from <= semester.end_date:
            raise ConflictError(message="生效日期须在本学期内")
        return body.configuration.model_dump(mode="json", exclude={"confirm_existing_tasks"})

    @atomic_write
    def create(self, data):
        body = validated(ProfileDraft, data)
        self._scope(write=True)
        configuration = self._configuration(body)
        row = CollegeTimeProfile(college_id=self.cid, semester_id=self.sid, name=body.name,
            normalized_name=normalized_name(body.name), draft_configuration=configuration)
        self.db.add(row)
        return self.campus._commit(self.actor, "academic.time_profile.create", row)

    @atomic_write
    def save(self, pid, data):
        body = validated(ProfileSave, data)
        self._scope(write=True)
        row = self._row(pid, lock=True)
        self.campus._version(row, body.lock_version)
        if row.status == "ARCHIVED":
            raise ConflictError(message="归档方案只读")
        if row.draft_configuration.get("time_basis", "PERIODS") != body.configuration.time_basis:
            raise ConflictError(message="作息方案的时间来源不能切换，请新建独立方案并预览绑定影响")
        before = self.campus._dto(row)
        row.name, row.normalized_name = body.name, normalized_name(body.name)
        row.draft_configuration = self._configuration(body)
        row.lock_version += 1
        return self.campus._commit(self.actor, "academic.time_profile.draft.save", row, before)

    def preview(self, pid):
        self._scope()
        row = self._row(pid)
        return CollegeTimeService(self.db, self.actor, self.cid, self.sid, profile_id=pid).preview(row.draft_configuration)

    @atomic_write
    def publish(self, pid, version, revision, confirm):
        self._scope(write=True)
        row = self._row(pid, lock=True)
        self.campus._version(row, version)
        return CollegeTimeService(self.db, self.actor, self.cid, self.sid, profile_id=pid).publish(
            {**row.draft_configuration, "confirm_existing_tasks": confirm}, revision)

    @atomic_write
    def archive(self, pid, version):
        self._scope(write=True)
        row = self._row(pid, lock=True)
        self.campus._version(row, version)
        if row.status == "ARCHIVED":
            raise ConflictError(message="方案已归档")
        if self.db.scalar(select(TeachingClass.id).where(TeachingClass.time_profile_id == pid,
            TeachingClass.status == "ACTIVE").limit(1)) is not None:
            raise ConflictError(message="仍有有效教学班使用本方案，请先明确切回默认或其他方案")
        before = self.campus._dto(row)
        row.status, row.lock_version = "ARCHIVED", row.lock_version + 1
        return self.campus._commit(self.actor, "academic.time_profile.archive", row, before)

    def _binding(self, teaching_id, pid, *, write=False):
        scope = self._scope(write=write)
        teaching = self.db.scalar(select(TeachingClass).where(TeachingClass.id == teaching_id,
            TeachingClass.college_id == self.cid, TeachingClass.semester_id == self.sid).with_for_update(read=not write).execution_options(populate_existing=True))
        if teaching is None:
            raise NotFoundError("教学班不属于本院本学期")
        profile = self._row(pid, lock=write) if pid is not None else None
        if profile and profile.status != "ACTIVE":
            raise ConflictError(message="只能绑定已发布的有效方案")
        previous = self._row(teaching.time_profile_id, lock=write) if teaching.time_profile_id else None
        old_basis = previous.draft_configuration.get("time_basis", "PERIODS") if previous else "PERIODS"
        new_basis = profile.draft_configuration.get("time_basis", "PERIODS") if profile else "PERIODS"
        if old_basis != new_basis:
            raise ConflictError(message="独立时段与教学节次的时间来源不能互换，请新建相应排期并处置未来任务")
        impact = future_impact(self.db, self.cid, "teaching_class", teaching.id, teaching.classification_revision)
        source = {"teaching": [teaching.id, teaching.time_profile_id, teaching.ownership_version, teaching.classification_revision],
                  "profile": [profile.id, profile.lock_version] if profile else None,
                  "authorization": scope.authorization_revision, "impact": impact["revision"]}
        return teaching, impact, {"revision": fingerprint(source), "retained_future_task_ids": impact["retained_future_task_ids"],
            "existing_tasks_keep_snapshot": True, "profile_id": str(pid) if pid else None}

    def binding_preview(self, teaching_id, pid):
        return self._binding(teaching_id, pid)[2]

    @atomic_write
    def bind(self, teaching_id, pid, revision):
        teaching, impact, preview = self._binding(teaching_id, pid, write=True)
        if revision != preview["revision"]:
            raise ConflictError(message="教学班、方案或未来任务已变化，请重新预览")
        if teaching.time_profile_id == pid:
            self.db.commit()
            return self.campus._dto(teaching)
        before = self.campus._dto(teaching)
        teaching.time_profile_id = pid
        teaching.ownership_version += 1
        self.db.flush()
        validate_profile_schedules(self.db, self.actor, self.cid, self.sid, teaching_id=teaching.id)
        capture_impacts(self.db, self.cid, "time_binding", teaching.id, teaching.ownership_version,
            task_ids=[int(value) for value in impact["retained_future_task_ids"]], before=before, after=self.campus._dto(teaching))
        self.campus.repo.college(self.cid, lock=True).configuration_revision += 1
        return self.campus._commit(self.actor, "academic.time_profile.bind", teaching, before)


def validate_profile_schedules(db, actor, cid, sid, *, profile_id=None, teaching_id=None):
    from sqlalchemy.orm import selectinload

    from app.modules.academic.models import CourseSchedule
    from app.modules.academic.scoped_writes import ScopedAcademicWriteService
    from app.modules.academic.time_service import TimeResolver
    statement = select(CourseSchedule).options(selectinload(CourseSchedule.weeks)).join(
        TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id).where(
        CourseSchedule.college_id == cid, CourseSchedule.semester_id == sid,
        CourseSchedule.status == "ACTIVE", TeachingClass.status == "ACTIVE")
    if teaching_id is not None:
        statement = statement.where(TeachingClass.id == teaching_id)
    elif profile_id is not None:
        statement = statement.where(TeachingClass.time_profile_id == profile_id)
    resolver = TimeResolver(db)
    resolver.prefetch(cid, sid, lock=True)
    service = ScopedAcademicWriteService(db, actor, cid)
    semester = db.get(Semester, sid)
    for schedule in db.scalars(statement):
        service._schedule_time(schedule, semester, [week.week_no for week in schedule.weeks], resolver=resolver)
