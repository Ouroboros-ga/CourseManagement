"""教职工只读卡片、明细、统计与导出查询服务。

核心原则：
- SQL 先授权再分页，同一个范围谓词复用于卡片列表、详情、学生考勤、统计与导出；
- 责任视图仅按任务快照班级过滤学生，不使用当前学籍，绝不泄露同任务非管辖学生；
- 跨院独立任务不合并判定，未形成考勤 counts 为 null。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, false, func, not_, or_, select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester, TeachingClass
from app.modules.academic.staff_models import FacultyStaff
from app.modules.attendance.models import AttendanceRecord
from app.modules.attendance.repository import AttendanceRepository
from app.modules.identity.role_scope import business_today
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_deps import active_profile
from app.modules.identity.staff_scope import (
    responsible_class_condition,
    teaching_class_condition,
)
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    TaskRosterMember,
    TaskRosterMemberClass,
    TaskScheduleSource,
)
from app.modules.inspection.roster_provenance import source_class_ids
from app.modules.inspection.staff_record_schemas import (
    AttendanceCounts,
    CollegeBrief,
    StaffCardScope,
    StaffCollegeSummary,
    StaffInspectionRecordCard,
    StaffInspectionSummaryResponse,
    StaffStudentAttendanceItem,
    ViewLiteral,
)
from app.modules.organization.models import College
from app.modules.report.staff_export import build_staff_export_excel

# 授课归属不清时的提示：只限制本人写入，不封掉整条任务，也不假装知道是谁的学生。
REASON_UNVERIFIED = (
    "该生在本次名单里没有教学班归属记录，授课归属待核对；请由教学班管理员核实名单来源后再更正"
)
REASON_PART_OVERLAP = "该生同时属于本任务的其他教学班，需由负责该生的教师或管理员核对后更正"


def covered_source_classes(session, task, user_id, as_of) -> tuple[list[int], set[int]]:
    """任务引用的教学班，以及其中被本人当前有效授课关系覆盖的那些。"""
    sources = source_class_ids(session, task.id, task.teaching_class_id)
    if not sources:
        return [], set()
    covered = set(
        session.scalars(
            select(TeachingClass.id).where(
                TeachingClass.id.in_(sources),
                teaching_class_condition(
                    user_id, occurrence_on=task.inspection_date, as_of=as_of
                ),
            )
        ).all()
    )
    return sources, covered


def _membership_exists(*extra_conditions):
    stmt = select(TaskRosterMemberClass.id).where(
        TaskRosterMemberClass.task_id == TaskRosterMember.task_id,
        TaskRosterMemberClass.roster_version == TaskRosterMember.roster_version,
        TaskRosterMemberClass.student_id == TaskRosterMember.student_id,
        *extra_conditions,
    )
    return stmt.correlate(TaskRosterMember).exists()


def teaching_membership_conditions(user_id: int, covered: set[int]):
    """明细查询用的 (可读, 可更正) SQL 谓词，逐学生判定，先过滤再分页。

    单班任务由调用方整体放行（名单本就来自那一个教学班）；合班任务按冻结的教学班归属：
    全部命中本人 → 可读可更正；部分命中 → 可读不可更正；完全不命中 → 不可读；
    没有归属记录（本迁移之前的历史名单版本）→ 可读不可更正，不按当前选课猜历史。
    """
    if covered:
        any_covered = _membership_exists(TaskRosterMemberClass.teaching_class_id.in_(covered))
        any_foreign = _membership_exists(
            TaskRosterMemberClass.teaching_class_id.notin_(covered)
        )
    else:
        any_covered = _membership_exists(false())
        any_foreign = _membership_exists()
    any_record = _membership_exists()
    visible = or_(any_covered, not_(any_record))
    correctable = and_(any_covered, not_(any_foreign))
    return visible, correctable


class TeachingScope:
    """跨任务批量判定授课归属：统计与导出用，避免逐任务重复查询。"""

    def __init__(self, session, tasks, user_id: int, as_of: date) -> None:
        self.whole: set[int] = set()
        self.covered: dict[int, set[int]] = {}
        self.prov: dict[tuple[int, int], set[int]] = {}
        self._load(session, tasks, user_id, as_of)

    def _load(self, session, tasks, user_id: int, as_of: date) -> None:
        task_ids = [t.id for t in tasks]
        if not task_ids:
            return
        sources: dict[int, set[int]] = {t.id: set() for t in tasks}
        for task_id, class_id in session.execute(
            select(TaskScheduleSource.task_id, TaskScheduleSource.teaching_class_id).where(
                TaskScheduleSource.task_id.in_(task_ids)
            )
        ):
            sources.setdefault(task_id, set()).add(class_id)
        for task in tasks:
            if task.teaching_class_id:
                sources.setdefault(task.id, set()).add(task.teaching_class_id)
        # 一次查询按各任务自己的课次日核对关系：LOCAL 不扩散，SHARED 只认已确认映射。
        for task_id, class_id in session.execute(
            select(TaskScheduleSource.task_id, TaskScheduleSource.teaching_class_id)
            .join(InspectionTask, InspectionTask.id == TaskScheduleSource.task_id)
            .where(
                TaskScheduleSource.task_id.in_(task_ids),
                teaching_class_condition(
                    user_id, occurrence_on=InspectionTask.inspection_date, as_of=as_of
                ),
            )
        ):
            self.covered.setdefault(task_id, set()).add(class_id)
        for task in tasks:
            if not task.teaching_class_id:
                continue
            hit = session.scalar(
                select(TeachingClass.id).where(
                    TeachingClass.id == task.teaching_class_id,
                    teaching_class_condition(
                        user_id, occurrence_on=task.inspection_date, as_of=as_of
                    ),
                )
            )
            if hit is not None:
                self.covered.setdefault(task.id, set()).add(hit)
        for task_id, student_id, class_id in session.execute(
            select(
                TaskRosterMemberClass.task_id,
                TaskRosterMemberClass.student_id,
                TaskRosterMemberClass.teaching_class_id,
            ).where(TaskRosterMemberClass.task_id.in_(task_ids))
        ):
            self.prov.setdefault((task_id, student_id), set()).add(class_id)
        for task_id, classes in sources.items():
            if len(classes) == 1 and classes <= self.covered.get(task_id, set()):
                self.whole.add(task_id)

    def visible(self, task_id: int, student_id: int) -> bool:
        if task_id in self.whole:
            return True
        classes = self.prov.get((task_id, student_id))
        return not classes or bool(classes & self.covered.get(task_id, set()))

    def correctable(self, task_id: int, student_id: int) -> bool:
        if task_id in self.whole:
            return True
        classes = self.prov.get((task_id, student_id))
        if not classes:
            return False
        return classes <= self.covered.get(task_id, set())


def teaching_membership_for_record(
    session, task, user_id, as_of, student_id: int
) -> tuple[bool, bool, str | None]:
    """单条记录的 (可读, 可更正, 限制原因)；写入入口与明细共用同一判定。"""
    sources, covered = covered_source_classes(session, task, user_id, as_of)
    if not covered:
        return False, False, None
    if len(sources) == 1 and sources[0] in covered:
        return True, True, None
    classes = set(
        session.scalars(
            select(TaskRosterMemberClass.teaching_class_id).where(
                TaskRosterMemberClass.task_id == task.id,
                TaskRosterMemberClass.roster_version == task.roster_version,
                TaskRosterMemberClass.student_id == student_id,
            )
        ).all()
    )
    if not classes:
        return True, False, REASON_UNVERIFIED
    if classes <= covered:
        return True, True, None
    if classes & covered:
        return True, False, REASON_PART_OVERLAP
    return False, False, None


class StaffRecordQueryService:
    def __init__(self, session: Session, actor: CurrentUser) -> None:
        self.session = session
        self.actor = actor

    def _assert_staff(self) -> FacultyStaff:
        """回查本人有效档案；教工入口不要求已绑定学生。

        纯教工（无 student_id、无角色）在既有学生语义下就是 pre_binding 受限会话，
        绑定教职工档案后应能读取本人卡片；学生本人接口的守卫不由此处放宽。
        账号/档案/学院的有效性判定统一复用 T01 的 active_profile，不再各写一套。
        """
        staff = active_profile(self.session, self.actor.id)
        if staff is None:
            raise PermissionDeniedError("无可用教职工身份")
        return staff

    def get_base_task_condition(self, view: ViewLiteral, as_of: date):
        """获取任务基础权限谓词。"""
        if view == "teaching":
            return (
                select(TeachingClass.id)
                .where(
                    or_(
                        TeachingClass.id == InspectionTask.teaching_class_id,
                        select(TaskScheduleSource.task_id)
                        .where(
                            TaskScheduleSource.task_id == InspectionTask.id,
                            TaskScheduleSource.teaching_class_id == TeachingClass.id,
                        )
                        .exists(),
                    ),
                    teaching_class_condition(
                        self.actor.id,
                        occurrence_on=InspectionTask.inspection_date,
                        as_of=as_of,
                    ),
                )
                .correlate(InspectionTask)
                .exists()
            )
        elif view == "responsible":
            return (
                select(TaskRosterMember.id)
                .where(
                    TaskRosterMember.task_id == InspectionTask.id,
                    TaskRosterMember.roster_version == InspectionTask.roster_version,
                    TaskRosterMember.administrative_class_id_snapshot.is_not(None),
                    responsible_class_condition(
                        self.actor.id,
                        administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                        as_of=as_of,
                    ),
                )
                .correlate(InspectionTask)
                .exists()
            )
        else:
            raise PermissionDeniedError("不支持的工作视图")

    def _build_task_query(
        self,
        view: ViewLiteral,
        as_of: date,
        *,
        semester_id: int | None = None,
        inspection_date: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        teaching_class_id: int | None = None,
        administrative_class_id: int | None = None,
        responsible_college_id: int | None = None,
        course_name: str | None = None,
    ):
        stmt = select(InspectionTask).where(self.get_base_task_condition(view, as_of))
        if semester_id is not None:
            stmt = stmt.where(InspectionTask.semester_id == semester_id)
        if inspection_date is not None:
            stmt = stmt.where(InspectionTask.inspection_date == inspection_date)
        if date_from is not None:
            stmt = stmt.where(InspectionTask.inspection_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(InspectionTask.inspection_date <= date_to)
        if teaching_class_id is not None:
            stmt = stmt.where(
                or_(
                    InspectionTask.teaching_class_id == teaching_class_id,
                    select(TaskScheduleSource.task_id)
                    .where(
                        TaskScheduleSource.task_id == InspectionTask.id,
                        TaskScheduleSource.teaching_class_id == teaching_class_id,
                    )
                    .exists(),
                )
            )
        if administrative_class_id is not None:
            if view == "responsible":
                stmt = stmt.where(
                    select(TaskRosterMember.id)
                    .where(
                        TaskRosterMember.task_id == InspectionTask.id,
                        TaskRosterMember.roster_version == InspectionTask.roster_version,
                        (
                            TaskRosterMember.administrative_class_id_snapshot
                            == administrative_class_id
                        ),
                    )
                    .exists()
                )
            else:
                stmt = stmt.where(InspectionTask.administrative_class_id == administrative_class_id)
        if responsible_college_id is not None:
            stmt = stmt.where(InspectionTask.college_id == responsible_college_id)
        if course_name:
            stmt = stmt.where(InspectionTask.course_name_snapshot.ilike(f"%{course_name}%"))
        return stmt

    def _calculate_task_counts(
        self, task: InspectionTask, view: ViewLiteral, as_of: date
    ) -> tuple[str, AttendanceCounts | None]:
        if task.canceled_at is not None:
            return "CANCELED", None

        has_attendance = self.session.scalar(
            select(AttendanceRecord.id).where(AttendanceRecord.task_id == task.id).limit(1)
        )
        if has_attendance is None:
            has_pending = self.session.scalar(
                select(InspectionSubmission.id)
                .where(
                    InspectionSubmission.task_id == task.id,
                    InspectionSubmission.review_status == "PENDING",
                )
                .limit(1)
            )
            state = "PENDING_REVIEW" if has_pending is not None else "PENDING_SUBMISSION"
            return state, None

        state = "RECORDED"
        stmt = (
            select(AttendanceRecord.effective_type, func.count())
            .where(AttendanceRecord.task_id == task.id)
        )
        if view == "responsible":
            stmt = stmt.join(
                TaskRosterMember,
                and_(
                    TaskRosterMember.task_id == AttendanceRecord.task_id,
                    TaskRosterMember.student_id == AttendanceRecord.student_id,
                    TaskRosterMember.roster_version == task.roster_version,
                ),
            ).where(
                responsible_class_condition(
                    self.actor.id,
                    administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                    as_of=as_of,
                )
            )
        else:
            # 授课视图的人数与明细/写入同一口径：合班任务不把别人班的学生算进本人应到。
            sources, covered = covered_source_classes(self.session, task, self.actor.id, as_of)
            if not (len(sources) == 1 and sources[0] in covered):
                visible, _ = teaching_membership_conditions(self.actor.id, covered)
                stmt = stmt.join(
                    TaskRosterMember,
                    and_(
                        TaskRosterMember.task_id == AttendanceRecord.task_id,
                        TaskRosterMember.student_id == AttendanceRecord.student_id,
                        TaskRosterMember.roster_version == task.roster_version,
                    ),
                ).where(visible)
        stmt = stmt.group_by(AttendanceRecord.effective_type)
        rows = self.session.execute(stmt).all()
        by_type = {t: c for t, c in rows}
        counts = AttendanceCounts(
            total=sum(by_type.values()),
            NORMAL=by_type.get("NORMAL", 0),
            LEAVE=by_type.get("LEAVE", 0),
            LATE=by_type.get("LATE", 0),
            ABSENT=by_type.get("ABSENT", 0),
        )
        return state, counts

    def _build_card(
        self, task: InspectionTask, view: ViewLiteral, as_of: date, colleges: dict[int, College]
    ) -> StaffInspectionRecordCard:
        state, counts = self._calculate_task_counts(task, view, as_of)
        col = colleges.get(task.college_id) if task.college_id is not None else None
        college_brief = CollegeBrief(
            id=str(task.college_id or 0), name=col.name if col else "未知学院"
        )
        occurrence_key = (
            task.occurrence_keys_snapshot[0]
            if (task.occurrence_keys_snapshot and len(task.occurrence_keys_snapshot) > 0)
            else task.task_key
        )
        location_revision = (
            f"loc-{task.classroom_snapshot}" if task.classroom_snapshot else None
        )
        count_basis = (
            "AUTHORIZED_STUDENT_SET" if view == "responsible" else "TEACHING_CLASS_STUDENTS"
        )

        return StaffInspectionRecordCard(
            task_id=str(task.id),
            teaching_class_id=str(task.teaching_class_id) if task.teaching_class_id else None,
            occurrence_key=occurrence_key,
            course_name=task.course_name_snapshot or "",
            responsible_college=college_brief,
            inspection_date=task.inspection_date.isoformat(),
            starts_at=task.activity_start_at.isoformat() if task.activity_start_at else None,
            ends_at=task.activity_end_at.isoformat() if task.activity_end_at else None,
            classroom=task.classroom_snapshot,
            location_revision=location_revision,
            attendance_state=state,
            scope=StaffCardScope(view=view, count_basis=count_basis),
            counts=counts,
            allowed_actions=["view_detail"],
        )

    def list_cards(
        self,
        view: ViewLiteral,
        params: PageParams,
        **filters: Any,
    ) -> tuple[list[StaffInspectionRecordCard], int]:
        self._assert_staff()
        as_of = business_today()
        stmt = self._build_task_query(view, as_of, **filters)
        count_subq = stmt.order_by(None).subquery()
        total = self.session.execute(select(func.count()).select_from(count_subq)).scalar_one()

        tasks = list(
            self.session.scalars(
                stmt.order_by(InspectionTask.inspection_date.desc(), InspectionTask.id.desc())
                .limit(params.limit)
                .offset(params.offset)
            ).all()
        )
        if not tasks:
            return [], int(total)

        col_ids = {t.college_id for t in tasks}
        col_rows = self.session.scalars(select(College).where(College.id.in_(col_ids))).all()
        colleges = {c.id: c for c in col_rows}

        cards = [self._build_card(t, view, as_of, colleges) for t in tasks]
        return cards, int(total)

    def get_card(self, task_id: int, view: ViewLiteral) -> StaffInspectionRecordCard:
        self._assert_staff()
        as_of = business_today()
        stmt = select(InspectionTask).where(
            InspectionTask.id == task_id,
            self.get_base_task_condition(view, as_of),
        )
        task = self.session.scalar(stmt)
        if task is None:
            raise NotFoundError("查课记录不存在或无权访问")

        col = self.session.get(College, task.college_id)
        colleges = {col.id: col} if col else {}
        return self._build_card(task, view, as_of, colleges)

    def list_attendance(
        self,
        task_id: int,
        view: ViewLiteral,
        effective_type: str | None,
        params: PageParams,
    ) -> tuple[list[StaffStudentAttendanceItem], int]:
        self._assert_staff()
        as_of = business_today()
        task = self.session.scalar(
            select(InspectionTask).where(
                InspectionTask.id == task_id,
                self.get_base_task_condition(view, as_of),
            )
        )
        if task is None:
            raise NotFoundError("查课记录不存在或无权访问")

        stmt = (
            select(AttendanceRecord, TaskRosterMember)
            .join(
                TaskRosterMember,
                and_(
                    TaskRosterMember.task_id == AttendanceRecord.task_id,
                    TaskRosterMember.student_id == AttendanceRecord.student_id,
                    TaskRosterMember.roster_version == task.roster_version,
                ),
            )
            .where(AttendanceRecord.task_id == task_id)
        )
        sources, covered = covered_source_classes(self.session, task, self.actor.id, as_of)
        whole_class = len(sources) == 1 and sources[0] in covered
        if view == "responsible":
            stmt = stmt.where(
                responsible_class_condition(
                    self.actor.id,
                    administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                    as_of=as_of,
                )
            )
        elif not whole_class:
            # 合班任务只返回属于本人授课班级的学生；来源不明的保留但不可更正。
            visible, _correctable = teaching_membership_conditions(self.actor.id, covered)
            stmt = stmt.where(visible)
        if effective_type is not None:
            stmt = stmt.where(AttendanceRecord.effective_type == effective_type)

        count_subq = stmt.order_by(None).subquery()
        total = self.session.execute(select(func.count()).select_from(count_subq)).scalar_one()

        rows = self.session.execute(
            stmt.order_by(TaskRosterMember.student_no.asc(), AttendanceRecord.id.asc())
            .limit(params.limit)
            .offset(params.offset)
        ).all()

        if not rows:
            return [], int(total)

        record_ids = [rec.id for rec, _ in rows]
        photo_map = AttendanceRepository(self.session).map_photo_file_ids(record_ids)

        base_actions = ["view_history"]
        # correctable_ids 为 None 表示单班任务整班都是本人授课，不按逐学生归属收窄。
        correctable_ids: set[int] | None = None if whole_class else set()
        restriction: dict[int, str] = {}
        if correctable_ids is not None:
            # 逐学生核对冻结的教学班归属，能更正的才给 correct 动作。
            prov: dict[int, set[int]] = {}
            for member_class in self.session.execute(
                select(
                    TaskRosterMemberClass.student_id, TaskRosterMemberClass.teaching_class_id
                ).where(
                    TaskRosterMemberClass.task_id == task.id,
                    TaskRosterMemberClass.roster_version == task.roster_version,
                    TaskRosterMemberClass.student_id.in_([mem.student_id for _, mem in rows]),
                )
            ):
                prov.setdefault(member_class.student_id, set()).add(member_class.teaching_class_id)
            overlap: set[int] = set()
            for sid, classes in prov.items():
                if classes and classes <= covered:
                    correctable_ids.add(sid)
                elif classes & covered:
                    overlap.add(sid)
            unverified = {mem.student_id for _, mem in rows if mem.student_id not in prov}
            for sid in unverified:
                restriction[sid] = REASON_UNVERIFIED
            for sid in overlap:
                restriction[sid] = REASON_PART_OVERLAP

        items = []
        for rec, mem in rows:
            scoped = view == "teaching"
            can_correct = scoped and (correctable_ids is None or mem.student_id in correctable_ids)
            items.append(
                StaffStudentAttendanceItem(
                    attendance_record_id=str(rec.id),
                    task_id=str(rec.task_id),
                    student_id=str(rec.student_id),
                    student_no=mem.student_no,
                    name=mem.name,
                    administrative_class_name_snapshot=mem.class_name_snapshot,
                    effective_type=rec.effective_type,
                    current_version=rec.current_version,
                    photo_file_ids=photo_map.get(rec.id, []),
                    allowed_actions=[*base_actions, *(["correct"] if can_correct else [])],
                    restriction_reason=(
                        None
                        if not scoped or correctable_ids is None
                        else restriction.get(mem.student_id)
                    ),
                )
            )
        return items, int(total)

    def get_summary(
        self, view: ViewLiteral, **filters: Any
    ) -> StaffInspectionSummaryResponse:
        self._assert_staff()
        as_of = business_today()
        task_stmt = self._build_task_query(view, as_of, **filters)
        tasks = list(self.session.scalars(task_stmt).all())
        task_count = len(tasks)
        if task_count == 0:
            scope_desc = "本人授课记录" if view == "teaching" else "仅统计负责班级"
            return StaffInspectionSummaryResponse(
                view=view,
                scope_description=scope_desc,
                task_count=0,
                recorded_task_count=0,
                unrecorded_task_count=0,
                student_counts=AttendanceCounts(),
                college_summaries=[],
            )

        task_ids = [t.id for t in tasks]
        col_ids = {t.college_id for t in tasks}
        col_rows = self.session.scalars(select(College).where(College.id.in_(col_ids))).all()
        col_name_map = {c.id: c.name for c in col_rows}

        # 统计有考勤任务与无考勤任务
        recorded_task_ids = set(
            self.session.scalars(
                select(AttendanceRecord.task_id)
                .where(AttendanceRecord.task_id.in_(task_ids))
                .distinct()
            ).all()
        )
        recorded_task_count = len(recorded_task_ids)
        unrecorded_task_count = task_count - recorded_task_count

        # 统计学生考勤。责任视图按名单快照班级在 SQL 内收窄；授课视图逐学生判定归属，
        # 与明细、导出、写入同一口径（合班任务不把别人班的学生算进本人）。
        overall_types: dict[str, int] = {}
        college_types: dict[int, dict[str, int]] = {}
        if view == "responsible":
            base_att_stmt = (
                select(
                    InspectionTask.college_id,
                    AttendanceRecord.effective_type,
                    func.count(),
                )
                .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                .join(
                    TaskRosterMember,
                    and_(
                        TaskRosterMember.task_id == AttendanceRecord.task_id,
                        TaskRosterMember.student_id == AttendanceRecord.student_id,
                        TaskRosterMember.roster_version == InspectionTask.roster_version,
                    ),
                )
                .where(
                    AttendanceRecord.task_id.in_(task_ids),
                    responsible_class_condition(
                        self.actor.id,
                        administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                        as_of=as_of,
                    ),
                )
                .group_by(InspectionTask.college_id, AttendanceRecord.effective_type)
            )
            for cid, etype, count in self.session.execute(base_att_stmt).all():
                overall_types[etype] = overall_types.get(etype, 0) + count
                bucket = college_types.setdefault(cid, {})
                bucket[etype] = bucket.get(etype, 0) + count
        else:
            scope = TeachingScope(self.session, tasks, self.actor.id, as_of)
            detail_rows = self.session.execute(
                select(
                    InspectionTask.college_id,
                    AttendanceRecord.effective_type,
                    AttendanceRecord.task_id,
                    AttendanceRecord.student_id,
                )
                .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                .where(AttendanceRecord.task_id.in_(task_ids))
            ).all()
            for cid, etype, task_id, student_id in detail_rows:
                if not scope.visible(task_id, student_id):
                    continue
                overall_types[etype] = overall_types.get(etype, 0) + 1
                bucket = college_types.setdefault(cid, {})
                bucket[etype] = bucket.get(etype, 0) + 1

        overall_counts = AttendanceCounts(
            total=sum(overall_types.values()),
            NORMAL=overall_types.get("NORMAL", 0),
            LEAVE=overall_types.get("LEAVE", 0),
            LATE=overall_types.get("LATE", 0),
            ABSENT=overall_types.get("ABSENT", 0),
        )

        # 统计各学院任务数
        task_count_by_col: dict[int, int] = {}
        for t in tasks:
            task_count_by_col[t.college_id] = task_count_by_col.get(t.college_id, 0) + 1

        college_summaries: list[StaffCollegeSummary] = []
        for cid, c_task_count in task_count_by_col.items():
            c_by_type = college_types.get(cid, {})
            c_counts = AttendanceCounts(
                total=sum(c_by_type.values()),
                NORMAL=c_by_type.get("NORMAL", 0),
                LEAVE=c_by_type.get("LEAVE", 0),
                LATE=c_by_type.get("LATE", 0),
                ABSENT=c_by_type.get("ABSENT", 0),
            )
            college_summaries.append(
                StaffCollegeSummary(
                    college_id=str(cid),
                    college_name=col_name_map.get(cid, "未知学院"),
                    task_count=c_task_count,
                    student_counts=c_counts,
                )
            )

        scope_desc = "本人授课记录" if view == "teaching" else "仅统计负责班级"
        return StaffInspectionSummaryResponse(
            view=view,
            scope_description=scope_desc,
            task_count=task_count,
            recorded_task_count=recorded_task_count,
            unrecorded_task_count=unrecorded_task_count,
            student_counts=overall_counts,
            college_summaries=college_summaries,
        )

    def export_excel(self, view: ViewLiteral, **filters: Any) -> tuple[bytes, str]:
        self._assert_staff()
        as_of = business_today()
        task_stmt = self._build_task_query(view, as_of, **filters)
        tasks = list(
            self.session.scalars(
                task_stmt.order_by(InspectionTask.inspection_date.asc(), InspectionTask.id.asc())
            ).all()
        )
        task_map = {t.id: t for t in tasks}

        if not tasks:
            export_bytes = build_staff_export_excel([])
            return export_bytes, f"查课记录_{view}_{as_of.isoformat()}.xlsx"

        task_ids = list(task_map.keys())
        col_ids = {t.college_id for t in tasks}
        sem_ids = {t.semester_id for t in tasks}
        colleges = {
            c.id: c.name
            for c in self.session.scalars(select(College).where(College.id.in_(col_ids))).all()
        }
        semesters = {
            s.id: s.name
            for s in self.session.scalars(select(Semester).where(Semester.id.in_(sem_ids))).all()
        }

        att_stmt = (
            select(AttendanceRecord, TaskRosterMember)
            .join(
                TaskRosterMember,
                and_(
                    TaskRosterMember.task_id == AttendanceRecord.task_id,
                    TaskRosterMember.student_id == AttendanceRecord.student_id,
                ),
            )
            .where(AttendanceRecord.task_id.in_(task_ids))
        )
        if view == "responsible":
            att_stmt = att_stmt.where(
                responsible_class_condition(
                    self.actor.id,
                    administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                    as_of=as_of,
                )
            )
        att_rows = self.session.execute(
            att_stmt.order_by(AttendanceRecord.task_id.asc(), TaskRosterMember.student_no.asc())
        ).all()

        # 导出行与页面明细、人数、写入同一口径：合班任务不把非本人授课的学生写进老师的表。
        export_scope = (
            TeachingScope(self.session, tasks, self.actor.id, as_of)
            if view == "teaching"
            else None
        )

        export_time_str = as_of.isoformat()
        view_label = "本人授课" if view == "teaching" else "责任班级"

        rows_data = []
        for rec, mem in att_rows:
            t = task_map.get(rec.task_id)
            if t is None or mem.roster_version != t.roster_version:
                continue
            if export_scope is not None and not export_scope.visible(rec.task_id, rec.student_id):
                continue
            period_desc = f"第{t.start_period}-{t.end_period}节"
            class_name = (
                t.class_name_snapshot or mem.class_name_snapshot or ""
                if view == "responsible"
                else t.class_name_snapshot or ""
            )
            rows_data.append(
                {
                    "semester_name": semesters.get(t.semester_id, ""),
                    "view_label": view_label,
                    "class_name": class_name,
                    "college_name": colleges.get(t.college_id, ""),
                    "inspection_date": t.inspection_date.isoformat(),
                    "course_name": t.course_name_snapshot or "",
                    "period_desc": period_desc,
                    "classroom": t.classroom_snapshot or "",
                    "student_no": mem.student_no,
                    "student_name": mem.name,
                    "class_snapshot": mem.class_name_snapshot or "",
                    "effective_type": rec.effective_type,
                    "current_version": rec.current_version,
                    "export_time": export_time_str,
                }
            )

        export_bytes = build_staff_export_excel(rows_data)
        filename = f"查课记录_{view}_{as_of.isoformat()}.xlsx"
        return export_bytes, filename


__all__ = ["StaffRecordQueryService"]
