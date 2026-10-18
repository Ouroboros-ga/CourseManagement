"""Bounded adapter for the six existing import algorithms, with an explicit college contract.

Only this operation installs the compatibility SQL/write guards on its Session.
No global Session filtering or implicit primary-college fallback is introduced.
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event, select

from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.academic.enrollment_models import (
    CourseParticipation,
    StudentEnrollment,
    TeachingClassAudience,
)
from app.modules.academic.models import (
    AdministrativeClass,
    CalendarOverride,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.academic.time_models import CollegeTimeVersion
from app.modules.identity.query_scope import filter_queries, protect_writes
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.role_scope import business_today
from app.modules.importer.models import ImportBatch
from app.modules.importer.repository import ImporterRepository
from app.modules.importer.service import ImporterService


class CollegeBatchRepository(ImporterRepository):
    def __init__(self, db, service):
        super().__init__(db)
        self.service = service

    def add(self, batch):
        batch.college_id = self.service.cid
        batch.payload_json = {
            **batch.payload_json,
            "workspace_source_revision": (
                getattr(self.service, "_draft_source_revision", None)
                or self.service.source_revision()
            ),
        }
        return super().add(batch)

    def get(self, batch_id):
        return self._session.scalar(
            select(ImportBatch)
            .where(ImportBatch.id == batch_id, ImportBatch.college_id == self.service.cid)
            .execution_options(populate_existing=True)
        )

    def get_for_update(self, batch_id):
        return self._session.scalar(
            select(ImportBatch)
            .where(ImportBatch.id == batch_id, ImportBatch.college_id == self.service.cid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )


class ScopedImporterService(ImporterService):
    def __init__(self, db, actor, cid):
        super().__init__(db)
        self.actor, self.cid = actor, cid
        self._repo = CollegeBatchRepository(db, self)

    def _parse_admin_roster(self, content, filename):
        from app.modules.importer.college_names import college_name_keys, normalize_college_name

        payload, issues, summary = super()._parse_admin_roster(content, filename)
        college_name, accepted_names = college_name_keys(self._session, self.cid)
        for row in [*payload.get("students", []), *payload.get("class_duties", [])]:
            if row.get("college") and normalize_college_name(row["college"]) not in accepted_names:
                issues.append({
                    "code": "COLLEGE_MISMATCH", "severity": "error", "field": "学院",
                    "row": row.get("source_row"),
                    "message": f"原表学院“{row['college']}”不能唯一对应当前工作区“{college_name}”，"
                               "请核对名称；不允许通过导入转移学院",
                })
            else:
                # 模板学院列选填；显式工作区提供归属，不把空文本写成外院资料。
                row["college"] = college_name
        return payload, issues, summary

    @contextmanager
    def draft_source_snapshot(self):
        """ZIP内的草稿共用起始指纹；正式预览/确认始终重新读取来源。

        草稿期间即使其他请求改动正式资料，后续确认也会因指纹不符被拒绝，
        不把此快照当成可跨请求或跨确认复用的缓存。
        """
        with self.operation("import.execute"):
            previous = getattr(self, "_draft_source_revision", None)
            self._draft_source_revision = previous or self.source_revision()
            try:
                yield
            finally:
                self._draft_source_revision = previous

    def grid_slot_mapping(self, semester_id):
        from app.core.config import get_settings

        # 学院数据隔离不等于启用学院独立作息。关闭后，正式业务仍使用
        # PeriodDefinition，导入也必须遵循同一学校节次口径。
        if not get_settings().campus_scheduling_enabled:
            try:
                return super().grid_slot_mapping(semester_id)
            except AppError as exc:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "学校本学期的节次配置缺失或无法识别，请联系管理员核对学校节次后重新上传课表；"
                    "当前使用学校统一作息，无需另建学院独立作息。",
                    422,
                ) from exc

        version = self._session.scalar(
            select(CollegeTimeVersion)
            .where(
                CollegeTimeVersion.college_id == self.cid,
                CollegeTimeVersion.semester_id == semester_id,
                CollegeTimeVersion.profile_id.is_(None),
            )
            .order_by(CollegeTimeVersion.version.desc())
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        mapping = (version.configuration if version else {}).get("grid_slot_mapping", {})
        if not mapping:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "本学院本学期尚未设置教务课表节次对应关系。请到“教务资料 → 本院作息与校历”"
                "采用含节次对应关系的学校默认作息，或完善对应关系并发布后，再重新上传课表。",
                422,
            )
        return {int(raw): target for raw, target in mapping.items()}

    def _require(self, actor_user_id, code):
        if actor_user_id != self.actor.id:
            raise PermissionDeniedError()
        resolve_scope(self._session, self.actor, self.cid, code, write=True)

    @contextmanager
    def operation(self, action):
        scope = resolve_scope(self._session, self.actor, self.cid, action, write=True)
        previous = self._session.info.get("college_query_scope")
        self._session.info["college_query_scope"] = {
            "college_id": self.cid,
            "actor_id": self.actor.id,
            "on_date": business_today(),
            "verified_scope": scope,
        }
        # Instance-local guards also support offline Session fixtures. They are
        # removed before any other domain reuses this request's Session.
        from app.modules.identity.query_scope import ScopedSession

        installed = not isinstance(self._session, ScopedSession) and not event.contains(
            self._session, "do_orm_execute", filter_queries
        )
        if installed:
            event.listen(self._session, "do_orm_execute", filter_queries)
            event.listen(self._session, "before_flush", protect_writes)
        try:
            # Match lifecycle lock order before the legacy batch lock/row writes.
            self._session.execute(select(Semester.id).order_by(Semester.id).with_for_update()).all()
            yield
        except Exception:
            self._session.rollback()
            raise
        finally:
            if installed:
                event.remove(self._session, "do_orm_execute", filter_queries)
                event.remove(self._session, "before_flush", protect_writes)
            if previous is None:
                self._session.info.pop("college_query_scope", None)
            else:
                self._session.info["college_query_scope"] = previous

    def source_revision(self):
        """Hash authorized source facts; never store names/rosters in a shared artifact."""
        db = self._session
        source = {"college": self.cid}
        from app.modules.importer.person_links import source_facts

        source["person_relations"] = source_facts(db, self.cid)
        # Current locking reads avoid an older REPEATABLE READ authentication snapshot.
        for model in (
            AdministrativeClass,
            Course,
            TeachingClass,
            CourseSchedule,
            Student,
            StudentEnrollment,
            CourseParticipation,
            TeachingClassAudience,
            VolunteerQualification,
            CollegeTimeVersion,
            Semester,
            PeriodDefinition,
            CalendarOverride,
        ):
            query = select(model).order_by(*model.__mapper__.primary_key)
            if hasattr(model, "college_id"):
                predicate = model.college_id == self.cid
                if model is Course:
                    from sqlalchemy import or_

                    predicate = or_(predicate, model.college_id.is_(None))
                query = query.where(predicate)
            source[model.__tablename__] = [
                [getattr(row, column.name) for column in model.__table__.columns]
                for row in db.scalars(
                    query.with_for_update(read=True).execution_options(populate_existing=True)
                )
            ]
        source["weeks"] = [
            list(row)
            for row in db.execute(
                select(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
                .where(
                    CourseScheduleWeek.schedule_id.in_(
                        select(CourseSchedule.id).where(CourseSchedule.college_id == self.cid)
                    )
                )
                .order_by(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
                .with_for_update(read=True)
            )
        ]
        return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()

    def get_template(self, actor, target):
        from app.modules.importer.permissions import TARGET_MANAGE_PERMISSION

        action = TARGET_MANAGE_PERMISSION.get(target)
        if action is None:
            return super().get_template(actor, target)
        with self.operation(action):
            return super().get_template(actor, target)

    def create_preview(self, actor, **kwargs):
        with self.operation("import.execute"):
            return super().create_preview(actor, **kwargs)

    def import_bulk_files(self, actor, **kwargs):
        # Each file retains the legacy explicit preview/confirm transaction. The
        # outer guard remains installed across those commits and is reauthorized
        # by every nested operation; a failed file cannot widen the next scope.
        with self.operation("import.execute"):
            return super().import_bulk_files(actor, **kwargs)

    def get_batch(self, actor, batch_id):
        with self.operation("import.execute"):
            return super().get_batch(actor, batch_id)

    def list_recent(self, actor, limit=10):
        from app.modules.importer.schemas import ImportBatchListItem

        with self.operation("import.execute"):
            rows = self._session.scalars(
                select(ImportBatch)
                .where(ImportBatch.college_id == self.cid)
                .order_by(ImportBatch.id.desc())
                .limit(limit)
                .execution_options(populate_existing=True)
            ).all()
            return [
                ImportBatchListItem(
                    id=row.id,
                    target=row.target,
                    status=row.status,
                    filename=row.filename,
                    semester_id=row.semester_id,
                    summary=row.summary_json or {},
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                )
                for row in rows
            ]

    def get_errors(self, actor, batch_id):
        with self.operation("import.execute"):
            return super().get_errors(actor, batch_id)

    def confirm(self, actor, batch_id, request_id):
        with self.operation("import.execute"):
            batch = self._repo.get_for_update(batch_id)
            if batch is None:
                raise NotFoundError("导入批次不属于当前学院")
            expected = (batch.payload_json or {}).get("workspace_source_revision")
            if expected is None or expected != self.source_revision():
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT, "正式来源在预览后已变化，请重新上传预览；整批未应用"
                )
            self._validate_official_times(batch)
            return super().confirm(actor, batch_id, request_id)

    def _validate_official_times(self, batch):
        from app.core.config import get_settings
        from app.modules.academic.time_service import TimeResolver

        if not get_settings().campus_scheduling_enabled:
            return
        key = {"timetable": "rows", "grid_timetable": "courses", "elective_course": "groups"}.get(
            batch.target
        )
        if key is None:
            return
        semester = self._session.get(Semester, batch.semester_id, populate_existing=True)
        if semester is None:
            raise NotFoundError("学期不存在")
        resolver = TimeResolver(self._session)
        resolver.prefetch(self.cid, semester.id, lock=True)
        days = []
        day = semester.start_date
        while day <= semester.end_date:
            teaching_day = resolver.teaching_day(self.cid, semester.id, day)
            if teaching_day:
                days.append((day, *teaching_day))
            day += timedelta(days=1)
        for row in (batch.payload_json or {}).get(key, []):
            start, end = row["start_period"], row["end_period"]
            if not 1 <= start <= end <= 60:
                raise AppError(ErrorCode.VALIDATION_ERROR, "导入节次范围无效，整批未应用", 422)
            weeks = set(row["weeks"])
            for day, week, weekday in days:
                if week in weeks and weekday == row["weekday"]:
                    resolver.interval(self.cid, semester.id, day, start, end)
