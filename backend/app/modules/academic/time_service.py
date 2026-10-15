import hashlib
import json
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.academic.calendar import TeachingDayOverride, resolve_teaching_day
from app.modules.academic.models import (
    CalendarOverride,
    CourseSchedule,
    PeriodDefinition,
    Semester,
    TeachingClass,
)
from app.modules.academic.time_models import CollegeTimeProfile, CollegeTimeVersion
from app.modules.academic.time_schemas import TimeCalendarOverride, TimeConfiguration
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.role_scope import business_today
from app.modules.inspection.models import InspectionTask
from app.modules.organization.service import atomic_write, validated


class CollegeTimeService:
    def __init__(self, db: Session, actor, cid: int, sid: int, *, profile_id: int | None = None):
        self.db, self.actor, self.cid, self.sid = db, actor, cid, sid
        self.profile_id = profile_id

    def _versions(self, *, lock=False):
        stmt = (
            select(CollegeTimeVersion)
            .where(
                CollegeTimeVersion.college_id == self.cid,
                CollegeTimeVersion.semester_id == self.sid,
                CollegeTimeVersion.profile_id == self.profile_id,
            )
            .order_by(CollegeTimeVersion.version)
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update()
        return list(self.db.scalars(stmt))

    def versions(self):
        resolve_scope(self.db, self.actor, self.cid, "academic.read")
        return [
            {
                "id": str(v.id),
                "version": v.version,
                "effective_from": v.effective_from,
                "configuration": v.configuration,
                "source_template_id": str(v.source_template_id) if v.source_template_id else None,
            }
            for v in self._versions()
        ]

    def _preview(self, data, *, lock=False):
        scope = resolve_scope(self.db, self.actor, self.cid, "academic.manage", write=lock)
        body = validated(TimeConfiguration, data)
        profile = None
        if self.profile_id is not None:
            profile = self.db.scalar(select(CollegeTimeProfile).where(CollegeTimeProfile.id == self.profile_id,
                CollegeTimeProfile.college_id == self.cid, CollegeTimeProfile.semester_id == self.sid).with_for_update(read=not lock).execution_options(populate_existing=True))
            if profile is None or profile.status == "ARCHIVED":
                raise ConflictError(message="作息方案已归档或不属于本院本学期")
            if body.calendar or body.grid_slot_mapping:
                raise ConflictError(message="教学班方案只调整时段；校历与教务映射统一由学院默认方案管理")
        stmt = select(Semester).where(Semester.id == self.sid)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        semester = self.db.scalar(stmt)
        if semester is None:
            raise NotFoundError("学期不存在")
        if semester.status != "ACTIVE":
            raise ConflictError(message="学期已停用")
        if not semester.start_date <= body.effective_from <= semester.end_date:
            raise AppError(ErrorCode.VALIDATION_ERROR, "生效日期须在学期内", 422)
        if any(not semester.start_date <= c.date <= semester.end_date for c in body.calendar):
            raise AppError(ErrorCode.VALIDATION_ERROR, "学院校历日期须在学期内", 422)
        if any(
            c.source_teaching_week is not None and c.source_teaching_week > semester.total_weeks
            for c in body.calendar
        ):
            raise AppError(ErrorCode.VALIDATION_ERROR, "学院校历来源周次超出学期", 422)
        versions = self._versions(lock=lock)
        if (
            versions
            and versions[-1].configuration.get("grid_slot_mapping")
            and versions[-1].configuration["grid_slot_mapping"] != body.grid_slot_mapping
        ):
            has_schedules = self.db.scalar(
                select(CourseSchedule.id)
                .where(
                    CourseSchedule.college_id == self.cid,
                    CourseSchedule.semester_id == self.sid,
                )
                .limit(1)
            )
            if has_schedules:
                raise ConflictError(
                    message="已有正式课表，不能隐式更换教务小节映射；请先核对并处理课表"
                )
        affected = list(
            self.db.execute(
                select(InspectionTask.id, InspectionTask.lock_version)
                .where(
                    InspectionTask.college_id == self.cid,
                    InspectionTask.semester_id == self.sid,
                    InspectionTask.inspection_date >= max(body.effective_from, business_today()),
                    InspectionTask.canceled_at.is_(None),
                    (InspectionTask.teaching_class_id.in_(select(TeachingClass.id).where(TeachingClass.time_profile_id == self.profile_id))
                     if self.profile_id is not None else True),
                )
                .order_by(InspectionTask.id)
            )
        )
        snapshot = body.model_dump(mode="json", exclude={"confirm_existing_tasks"})
        sequence = max(self.db.scalars(select(CollegeTimeVersion.version).where(
            CollegeTimeVersion.college_id == self.cid, CollegeTimeVersion.semester_id == self.sid
        ).with_for_update(read=True)), default=0)
        source = {
            "version_sequence": sequence,
            "profile": [profile.id, profile.lock_version] if profile else None,
            "college": self.cid,
            "semester": [
                self.sid,
                str(semester.start_date),
                str(semester.end_date),
                str(semester.first_monday),
                semester.total_weeks,
            ],
            "authorization_revision": scope.authorization_revision,
            "versions": [v.id for v in versions],
            "configuration": snapshot,
            "affected": [list(r) for r in affected],
        }
        revision = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        return (
            body,
            snapshot,
            versions,
            {
                "revision": revision,
                "next_version": sequence + 1,
                "retained_future_task_ids": [str(r.id) for r in affected],
                "existing_tasks_keep_snapshot": True,
            },
        )

    def preview(self, data):
        return self._preview(data)[3]

    @atomic_write
    def publish(self, data, revision: str, *, source_template_id: int | None = None, commit=True):
        body, snapshot, versions, preview = self._preview(data, lock=True)
        if revision != preview["revision"]:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "配置、任务或授权已变化，请重新预览")
        if preview["retained_future_task_ids"] and not body.confirm_existing_tasks:
            raise ConflictError(message="已有未来任务保留原时间，请确认影响后发布")
        row = CollegeTimeVersion(
            college_id=self.cid,
            semester_id=self.sid,
            profile_id=self.profile_id,
            version=preview["next_version"],
            effective_from=body.effective_from,
            configuration=snapshot,
            published_by=self.actor.id,
            source_template_id=source_template_id or (versions[-1].source_template_id if versions else None),
        )
        if self.profile_id is not None:
            profile = self.db.get(CollegeTimeProfile, self.profile_id)
            profile.status = "ACTIVE"
            profile.lock_version += 1
        self.db.add(row)
        self.db.flush()
        from app.modules.academic.time_profiles import validate_profile_schedules
        validate_profile_schedules(self.db, self.actor, self.cid, self.sid, profile_id=self.profile_id)

        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="academic.time.publish",
                resource_type="college_time_version",
                resource_id=str(row.id),
                after_json=scoped_snapshot(snapshot, self.cid),
            )
        )
        from app.modules.organization.impact_service import capture_impacts
        capture_impacts(self.db, self.cid, "time_version", row.id, row.version,
                        task_ids=[int(value) for value in preview["retained_future_task_ids"]], after=snapshot)
        if commit:
            self.db.commit()
        return {"id": str(row.id), "version": row.version, **preview}


class TimeResolver:
    def __init__(self, db: Session):
        self.db = db
        self._profile_bindings: dict[int, int | None] = {}
        self._version_cache: dict[tuple[int, int], list[CollegeTimeVersion]] = {}
        self._period_cache: dict[int, dict[int, tuple[time | None, time | None]]] = {}
        self._calendar_cache: dict[int, dict[date, CalendarOverride]] = {}

    def prefetch(self, cid: int, sid: int, *, lock=False):
        def rows(stmt):
            if lock:
                stmt = stmt.with_for_update(read=True)
            return self.db.scalars(stmt.execution_options(populate_existing=True))

        versions = list(
            rows(
                select(CollegeTimeVersion).where(
                    CollegeTimeVersion.college_id == cid, CollegeTimeVersion.semester_id == sid
                )
            )
        )
        self._profile_bindings.update({row.id: row.time_profile_id for row in rows(
            select(TeachingClass).where(TeachingClass.college_id == cid, TeachingClass.semester_id == sid))})
        self._version_cache[cid, sid] = versions
        if sid not in self._period_cache:
            self._period_cache[sid] = {
                p.period_no: (p.start_time, p.end_time)
                for p in rows(select(PeriodDefinition).where(PeriodDefinition.semester_id == sid))
            }
            self._calendar_cache[sid] = {
                c.date: c
                for c in rows(select(CalendarOverride).where(CalendarOverride.semester_id == sid))
            }
        return versions

    def version(self, cid: int, sid: int, day: date, *, profile_id=None):
        if (cid, sid) in self._version_cache:
            return max(
                (v for v in self._version_cache[cid, sid] if v.effective_from <= day and v.profile_id == profile_id),
                key=lambda v: (v.effective_from, v.version),
                default=None,
            )
        return self.db.scalar(
            select(CollegeTimeVersion)
            .where(
                CollegeTimeVersion.college_id == cid,
                CollegeTimeVersion.semester_id == sid,
                CollegeTimeVersion.effective_from <= day,
                CollegeTimeVersion.profile_id == profile_id,
            )
            .order_by(CollegeTimeVersion.effective_from.desc(), CollegeTimeVersion.version.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )

    def teaching_day(self, cid: int | None, sid: int, day: date):
        if cid is None:
            raise ConflictError(message="正式课程学院归属未确认")
        semester = self.db.get(Semester, sid)
        if semester is None:
            raise NotFoundError("学期不存在")
        version = self.version(cid, sid, day)
        override: TeachingDayOverride | None = None
        if version:
            override = next(
                (
                    TimeCalendarOverride.model_validate(c)
                    for c in version.configuration["calendar"]
                    if c["date"] == day.isoformat()
                ),
                None,
            )
        if override is None and not (version and version.source_template_id):
            override = (
                self._calendar_cache[sid].get(day)
                if sid in self._calendar_cache
                else self.db.scalar(
                    select(CalendarOverride).where(
                        CalendarOverride.semester_id == sid, CalendarOverride.date == day
                    )
                )
            )
        return resolve_teaching_day(semester.first_monday, day, override)

    def calendar_provenance(self, cid, sid, day):
        from app.modules.academic.time_models import SchoolSemesterDefault
        version = self.version(cid, sid, day)
        if version:
            entry = next((c for c in version.configuration.get("calendar", []) if c["date"] == day.isoformat()), None)
            if version.source_template_id:
                template = self.db.get(SchoolSemesterDefault, version.source_template_id)
                base = next((c for c in template.configuration.get("calendar", []) if c["date"] == day.isoformat()), None)
                return "SCHOOL_CALENDAR" if entry == base else "COLLEGE_CALENDAR"
            if entry:
                return "COLLEGE_CALENDAR"
        return "SCHOOL_CALENDAR"

    def interval(self, cid: int | None, sid: int, day: date, start: int, end: int, *, teaching_class_id=None):
        if cid is None or start < 1 or end < start:
            raise ConflictError(message="课次归属或时间范围未确认")
        profile_id = None
        if teaching_class_id is not None:
            if teaching_class_id not in self._profile_bindings:
                teaching = self.db.get(TeachingClass, teaching_class_id)
                if teaching is None or teaching.college_id != cid or teaching.semester_id != sid:
                    raise ConflictError(message="教学班不属于当前作息工作区")
                self._profile_bindings[teaching_class_id] = teaching.time_profile_id
            profile_id = self._profile_bindings[teaching_class_id]
        version = self.version(cid, sid, day, profile_id=profile_id)
        if version is None and profile_id is not None:
            version = self.version(cid, sid, day)
        periods: dict[int, tuple[time | None, time | None]]
        if version:
            periods = {
                p["period_no"]: (
                    time.fromisoformat(p["start_time"]),
                    time.fromisoformat(p["end_time"]),
                )
                for p in version.configuration["periods"]
            }
        else:
            periods = (
                self._period_cache[sid]
                if sid in self._period_cache
                else {
                    p.period_no: (p.start_time, p.end_time)
                    for p in self.db.scalars(
                        select(PeriodDefinition).where(PeriodDefinition.semester_id == sid)
                    )
                }
            )
        values = [periods.get(p) for p in range(start, end + 1)]
        if not values or any(p is None or p[0] is None or p[1] is None for p in values):
            raise ConflictError(message="正式作息缺少所需节次的起止时刻")
        complete: list[tuple[time, time]] = []
        for pair in values:
            if pair is None or pair[0] is None or pair[1] is None:
                raise ConflictError(message="正式作息缺少所需节次的起止时刻")
            complete.append((pair[0], pair[1]))
        first, last = complete[0][0], complete[-1][1]
        if first >= last or any(a[1] > b[0] for a, b in zip(complete, complete[1:], strict=False)):
            raise ConflictError(message="正式作息起止顺序不合法")
        template_id = version.source_template_id if version else None
        source = "COLLEGE_VERSION" if version else "SCHOOL_PERIODS"
        if template_id:
            from app.modules.academic.time_models import SchoolSemesterDefault
            template = self.db.get(SchoolSemesterDefault, template_id)
            base_periods = {p["period_no"]: p for p in template.configuration["periods"]}
            selected_periods = {p["period_no"]: p for p in version.configuration["periods"]}
            if all(selected_periods.get(no) == base_periods.get(no) for no in range(start, end + 1)):
                source = "SCHOOL_TEMPLATE"
        return {
            "start_minute": first.hour * 60 + first.minute,
            "end_minute": last.hour * 60 + last.minute,
            "time_version_id": str(version.id) if version else None,
            "time_profile_id": str(version.profile_id) if version and version.profile_id else None,
            "source": source,
            "source_template_id": str(template_id) if template_id else None,
            "calendar_source": self.calendar_provenance(cid, sid, day),
        }
