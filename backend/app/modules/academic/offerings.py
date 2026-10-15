"""Recommend matching metadata, but merge identities only after explicit confirmation."""

import unicodedata
from datetime import timedelta

from pydantic import Field
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import (
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    TeachingClass,
)
from app.modules.academic.offering_models import AcademicOffering, ImportSourceAssertion
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.role_scope import business_today
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import InspectionTask, TaskScheduleSource
from app.modules.organization.models import College
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write


def normalized(value):
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def teaching_facts(db, tid):
    teaching = db.get(TeachingClass, tid)
    if teaching is None:
        raise NotFoundError("教学班不存在")
    course = db.get(Course, teaching.course_id)
    from app.modules.academic.time_service import TimeResolver

    resolver = TimeResolver(db)
    resolver.prefetch(teaching.college_id, teaching.semester_id)
    semester = db.get(Semester, teaching.semester_id)
    schedules = list(
        db.scalars(
            select(CourseSchedule)
            .where(CourseSchedule.teaching_class_id == tid, CourseSchedule.status == "ACTIVE")
            .order_by(CourseSchedule.id)
            .execution_options(populate_existing=True)
        )
    )
    facts = []
    for row in schedules:
        weeks = sorted(
            db.scalars(
                select(CourseScheduleWeek.week_no).where(CourseScheduleWeek.schedule_id == row.id)
            )
        )
        times = []
        for week in weeks:
            day = semester.first_monday + timedelta(days=(week - 1) * 7 + row.weekday - 1)
            version = resolver.version(
                teaching.college_id, teaching.semester_id, day, profile_id=teaching.time_profile_id
            )
            if version is None and teaching.time_profile_id:
                version = resolver.version(teaching.college_id, teaching.semester_id, day)
            if version:
                periods = {
                    p["period_no"]: (p["start_time"], p["end_time"])
                    for p in version.configuration["periods"]
                }
            else:
                periods = resolver._period_cache[teaching.semester_id]
            pairs = [periods.get(number) for number in range(row.start_period, row.end_period + 1)]
            times.append(
                {
                    "week": week,
                    "start": str(pairs[0][0])[:5] if pairs and pairs[0] and pairs[0][0] else None,
                    "end": str(pairs[-1][1])[:5] if pairs and pairs[-1] and pairs[-1][1] else None,
                }
            )
        facts.append(
            {
                "weekday": row.weekday,
                "start_period": row.start_period,
                "end_period": row.end_period,
                "room": normalized(row.classroom),
                "teacher": normalized(row.teacher or teaching.teacher_name),
                "weeks": weeks,
                "times": times,
            }
        )
    return {
        "semester_id": str(teaching.semester_id),
        "course_name": normalized(course.course_name),
        "meetings": sorted(facts, key=fingerprint),
    }, schedules


def assert_shared_consistent(db, tid):
    teaching = db.get(TeachingClass, tid)
    if teaching is None or not teaching.academic_offering_id:
        return
    views = list(
        db.scalars(
            select(TeachingClass).where(
                TeachingClass.academic_offering_id == teaching.academic_offering_id,
                TeachingClass.status == "ACTIVE",
            )
        )
    )
    facts = {fingerprint(teaching_facts(db, row.id)[0]) for row in views}
    if len(facts) > 1:
        raise ConflictError(
            message="共享教学班的课程、周次或时间地点来源冲突；请各维护学院核对后再生成该班任务"
        )


class OfferingLink(StrictModel):
    target_teaching_class_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    reason: str = Field(min_length=1, max_length=512)


class OfferingLinkConfirm(OfferingLink):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class OfferingService:
    def __init__(self, db, actor, cid, tid):
        self.db, self.actor, self.cid, self.tid = db, actor, cid, tid

    def _own(self, *, write=False):
        resolve_scope(self.db, self.actor, self.cid, "academic.manage", write=write)
        row = self.db.scalar(
            select(TeachingClass)
            .where(TeachingClass.id == self.tid, TeachingClass.college_id == self.cid)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("教学班不属于当前学院")
        return row

    def candidates(self):
        own = self._own()
        ours, _ = teaching_facts(self.db, own.id)
        if not ours["meetings"]:
            return {"items": [], "message": "请先完善正式上课时间与周次"}
        school = self.db.get(College, self.cid).school_id
        # Shared metadata is the only cross-college read here; never query students/rosters.
        rows = self.db.execute(
            select(
                TeachingClass.id,
                TeachingClass.class_name,
                TeachingClass.college_id,
                College.name.label("college_name"),
            )
            .join(Course, Course.id == TeachingClass.course_id)
            .join(College, College.id == TeachingClass.college_id)
            .where(
                TeachingClass.semester_id == own.semester_id,
                TeachingClass.id != own.id,
                TeachingClass.status == "ACTIVE",
                College.school_id == school,
                Course.course_name == self.db.get(Course, own.course_id).course_name,
            )
            .order_by(TeachingClass.id)
            .limit(200)
        ).all()
        items = []
        for row in rows:
            facts, _ = teaching_facts(self.db, row.id)
            if facts == ours:
                items.append(
                    {
                        "teaching_class_id": str(row.id),
                        "college_id": str(row.college_id),
                        "college_name": row.college_name,
                        "class_name": row.class_name,
                        "facts": facts,
                        "already_linked": own.academic_offering_id is not None
                        and own.academic_offering_id
                        == self.db.get(TeachingClass, row.id).academic_offering_id,
                    }
                )
        return {"items": items, "automatic_merge": False, "candidate_limit": 200}

    def _preview(self, data, *, lock=False):
        from app.modules.organization.service import validated

        body = validated(OfferingLink, data)
        own = self._own()
        target = self.db.get(
            TeachingClass, int(body.target_teaching_class_id), populate_existing=True
        )
        if (
            target is None
            or target.id == own.id
            or target.semester_id != own.semester_id
            or target.status != "ACTIVE"
        ):
            raise NotFoundError("目标教学班不存在或不属于同一学期")
        source_college, target_college = (
            self.db.get(College, self.cid),
            self.db.get(College, target.college_id),
        )
        if not target_college or target_college.school_id != source_college.school_id:
            raise NotFoundError("目标教学班不属于本校")
        if lock:
            list(
                self.db.scalars(
                    select(College.id)
                    .where(College.id.in_(sorted({self.cid, target.college_id})))
                    .order_by(College.id)
                    .with_for_update()
                )
            )
            resolve_scope(self.db, self.actor, self.cid, "academic.manage", write=True)
            fresh = {
                t.id: t
                for t in self.db.scalars(
                    select(TeachingClass)
                    .where(TeachingClass.id.in_(sorted({own.id, target.id})))
                    .order_by(TeachingClass.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            }
            own, target = fresh[own.id], fresh[target.id]
        semester = self.db.get(Semester, own.semester_id)
        if semester.status != "ACTIVE":
            raise ConflictError(message="已归档学期不能关联教学班身份")
        ours, own_schedules = teaching_facts(self.db, own.id)
        theirs, target_schedules = teaching_facts(self.db, target.id)
        if not own_schedules or ours != theirs:
            raise ConflictError(
                message="课程名、完整周次、时间地点或教师不一致；请先核对资料，不按相似名称合并"
            )
        if len({fingerprint(m) for m in ours["meetings"]}) != len(ours["meetings"]):
            raise ConflictError(message="来源有重复上课条目，无法唯一映射，请先整理课表")
        assert_shared_consistent(self.db, target.id)
        already = (
            own.academic_offering_id is not None
            and own.academic_offering_id == target.academic_offering_id
        )
        if own.academic_offering_id and not already:
            raise ConflictError(
                message="本教学班已有确认身份；跨身份合并须另行核对，不覆盖既有关系"
            )
        tasks = list(
            self.db.scalars(
                select(InspectionTask.id).where(
                    InspectionTask.canceled_at.is_(None),
                    InspectionTask.inspection_date >= business_today(),
                    (InspectionTask.teaching_class_id == own.id)
                    | InspectionTask.id.in_(
                        select(TaskScheduleSource.task_id).where(
                            TaskScheduleSource.teaching_class_id == own.id
                        )
                    ),
                )
            )
        )
        if tasks and not already:
            raise ConflictError(
                message="本教学班已有未取消的今日或未来任务，请先处置任务再确认身份关联"
            )
        snapshot = {
            "actor": self.actor.id,
            "body": body.model_dump(),
            "source": [own.id, own.ownership_version, own.academic_offering_id],
            "target": [target.id, target.ownership_version, target.academic_offering_id],
            "facts": ours,
            "schedules": [
                [s.id, s.shared_meeting_key, s.shared_identity_from]
                for s in own_schedules + target_schedules
            ],
            "authorization": source_college.authorization_revision,
        }
        return (
            body,
            own,
            target,
            own_schedules,
            target_schedules,
            {
                "revision": fingerprint(snapshot),
                "facts": ours,
                "already_linked": already,
                "student_rosters_shared": False,
                "effective_from": business_today().isoformat(),
                "historical_tasks_unchanged": True,
            },
        )

    def preview(self, data):
        return self._preview(data)[5]

    @atomic_write
    def confirm(self, data):
        from app.modules.organization.service import validated

        body = validated(OfferingLinkConfirm, data)
        self.db.rollback()
        if self.db.get_bind().dialect.name == "mysql":
            self.db.connection(execution_options={"isolation_level": "READ COMMITTED"})
        _, own, target, own_schedules, target_schedules, preview = self._preview(
            body.model_dump(exclude={"revision"}), lock=True
        )
        if preview["already_linked"]:
            return {"academic_offering_id": own.academic_offering_id, "already_linked": True}
        if preview["revision"] != body.revision:
            raise ConflictError(message="教学资料、关联或权限已变化，请重新预览")
        if not target.academic_offering_id:
            offering = AcademicOffering(
                school_id=self.db.get(College, self.cid).school_id,
                semester_id=own.semester_id,
                course_name=self.db.get(Course, own.course_id).course_name,
            )
            self.db.add(offering)
            self.db.flush()
            target.academic_offering_id = offering.id
        own.academic_offering_id = target.academic_offering_id

        def key(s):
            return fingerprint(
                {
                    "weekday": s.weekday,
                    "start_period": s.start_period,
                    "end_period": s.end_period,
                    "room": normalized(s.classroom),
                    "teacher": normalized(s.teacher or own.teacher_name),
                    "weeks": sorted(w.week_no for w in s.weeks),
                }
            )

        target_by_key = {key(s): s for s in target_schedules}
        for schedule in own_schedules:
            peer = target_by_key[key(schedule)]
            if not peer.shared_meeting_key:
                peer.shared_meeting_key = f"s:{peer.id}"
                peer.shared_identity_from = business_today()
            schedule.shared_meeting_key = peer.shared_meeting_key
            schedule.shared_identity_from = business_today()
        for teaching in (own, target):
            self.db.add(
                ImportSourceAssertion(
                    offering_id=own.academic_offering_id,
                    teaching_class_id=teaching.id,
                    college_id=teaching.college_id,
                    assertion={
                        "facts": preview["facts"],
                        "reason": body.reason,
                        "source": "MANUAL_CONFIRMATION",
                    },
                    confirmed_by=self.actor.id,
                )
            )
        own.ownership_version += 1
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="academic.offering.link",
                resource_type="teaching_class",
                resource_id=str(own.id),
                after_json=scoped_snapshot(
                    {
                        "offering_id": own.academic_offering_id,
                        "target_teaching_class_id": str(target.id),
                        "reason": body.reason,
                        **preview,
                    },
                    self.cid,
                ),
            )
        )
        self.db.commit()
        return {
            "academic_offering_id": own.academic_offering_id,
            "already_linked": False,
            "student_rosters_shared": False,
        }
