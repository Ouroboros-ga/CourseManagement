from datetime import timedelta
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.modules.academic.models import AdministrativeClass, Semester, Student
from app.modules.academic.qualification_policy import enrollment_on
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.models import UserAccount
from app.modules.identity.role_scope import business_today
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.organization.service import CampusService, atomic_write, validated
from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport
from app.modules.volunteer.member_schemas import MemberCreate, MemberUpdate
from app.modules.volunteer.models import VolunteerGroup


class GroupMemberService:
    def __init__(self, db: Session, actor, cid: int, gid: int):
        self.db, self.actor, self.cid, self.gid = db, actor, cid, gid
        self.campus = CampusService(db)

    def _scope(self, action, *, write=False):
        from app.modules.identity.resource_scope import resolve_scope
        scope = resolve_scope(self.db, self.actor, self.cid, action, write=write)
        if not scope.permits_group(self.gid):
            raise NotFoundError("组不在授权范围")
        return self.campus.repo.college(self.cid, lock=write)

    def _group(self, action, *, write=False, semester_id=None):
        college = self._scope(action, write=write)
        if write and semester_id is not None:
            self.db.scalar(select(Semester).where(Semester.id == semester_id).with_for_update())
        stmt = select(VolunteerGroup).where(
            VolunteerGroup.id == self.gid, VolunteerGroup.college_id == self.cid
        )
        if write:
            stmt = stmt.with_for_update()
        group = self.db.scalar(stmt.execution_options(populate_existing=True))
        if group is None or group.deleted_at is not None:
            raise NotFoundError("组不在本学院")
        return college, group

    def members(self, semester_id: int):
        self._group("volunteer.group.read")
        return self._rows_dto(
            self.db.scalars(
                select(VolunteerGroupMember)
                .where(
                    VolunteerGroupMember.college_id == self.cid,
                    VolunteerGroupMember.group_id == self.gid,
                    VolunteerGroupMember.semester_id == semester_id,
                )
                .order_by(VolunteerGroupMember.id)
            )
        )

    def supports(self, semester_id: int):
        self._group("volunteer.group.read")
        return self._rows_dto(
            self.db.scalars(
                select(VolunteerGroupSupport)
                .where(
                    VolunteerGroupSupport.college_id == self.cid,
                    VolunteerGroupSupport.group_id == self.gid,
                    VolunteerGroupSupport.semester_id == semester_id,
                )
                .order_by(VolunteerGroupSupport.id)
            )
        )

    def _rows_dto(self, rows):
        rows = list(rows)
        # Names are authorized through the already-scoped membership/support rows.
        students = {
            s.id: s
            for s in self.db.scalars(
                select(Student).where(Student.id.in_({row.student_id for row in rows}))
            )
        }
        return [
            {
                **self.campus._dto(row),
                "name": students[row.student_id].name if row.student_id in students else None,
                "student_no": students[row.student_id].student_no
                if row.student_id in students
                else None,
            }
            for row in rows
        ]

    def candidates(self, semester_id, effective_from, effective_to, keyword="", *, school=False):
        from app.modules.academic.enrollment_models import StudentEnrollment

        self._group("volunteer.member.manage")
        if school:
            self.campus._super(self.actor)
        if effective_from >= effective_to:
            raise ConflictError(message="候选成员有效期不正确")
        timeline_ids = select(StudentEnrollment.student_id)
        dated = select(StudentEnrollment.student_id).where(
            StudentEnrollment.superseded.is_(False),
            StudentEnrollment.effective_from <= effective_from,
            (
                StudentEnrollment.effective_to.is_(None)
                | (StudentEnrollment.effective_to > effective_from)
            ),
            StudentEnrollment.status == "ENROLLED",
        )
        fallback = (
            Student.id.not_in(timeline_ids)
            & (Student.status == "ACTIVE")
            & Student.administrative_class_id.in_(
                select(AdministrativeClass.id).where(AdministrativeClass.college_id.is_not(None))
            )
        )
        eligible = Student.id.in_(dated) | fallback
        if not school:
            dated_home = dated.where(StudentEnrollment.college_id == self.cid)
            fallback_home = fallback & Student.administrative_class_id.in_(
                select(AdministrativeClass.id).where(AdministrativeClass.college_id == self.cid)
            )
            supported = select(VolunteerGroupSupport.student_id).where(
                VolunteerGroupSupport.college_id == self.cid,
                VolunteerGroupSupport.group_id == self.gid,
                VolunteerGroupSupport.semester_id == semester_id,
                VolunteerGroupSupport.status == "ACTIVE",
                VolunteerGroupSupport.effective_from <= effective_from,
                VolunteerGroupSupport.effective_to >= effective_to,
            )
            eligible &= Student.id.in_(dated_home) | fallback_home | Student.id.in_(supported)
        stmt = select(Student).where(eligible)
        if keyword:
            stmt = stmt.where(
                Student.student_no.contains(keyword, autoescape=True)
                | Student.name.contains(keyword, autoescape=True)
            )
        return [
            {"id": str(row.id), "student_no": row.student_no, "name": row.name}
            for row in self.db.scalars(stmt.order_by(Student.student_no, Student.id).limit(100))
        ]

    def _future(self, row, *, lock=False):
        stmt = (
            select(InspectionTask.id)
            .join(InspectionAssignment, InspectionAssignment.task_id == InspectionTask.id)
            .join(UserAccount, UserAccount.id == InspectionAssignment.volunteer_user_id)
            .where(
                InspectionTask.college_id == self.cid,
                InspectionTask.group_id == self.gid,
                InspectionTask.semester_id == row.semester_id,
                InspectionTask.inspection_date >= business_today(),
                InspectionTask.canceled_at.is_(None),
                InspectionAssignment.revoked_at.is_(None),
                UserAccount.student_id == row.student_id,
            )
            .order_by(InspectionTask.id)
        )
        if lock:
            stmt = stmt.with_for_update()
        return [str(tid) for tid in self.db.scalars(stmt)]

    def _existing(self, rid, support=False, *, lock=False):
        model = VolunteerGroupSupport if support else VolunteerGroupMember
        stmt = select(model).where(
            model.id == rid, model.college_id == self.cid, model.group_id == self.gid
        )
        if lock:
            stmt = stmt.with_for_update()
        row = self.db.scalar(stmt.execution_options(populate_existing=True))
        if row is None:
            raise NotFoundError()
        return row

    def impact(self, rid, *, support=False):
        self._group("volunteer.group.read")
        row = self._existing(rid, support)
        return {
            "lock_version": row.lock_version,
            "retained_future_task_ids": self._future(row),
            "existing_assignments_preserved": True,
        }

    @atomic_write
    def update(self, rid, data, *, support=False):
        body = validated(MemberUpdate, data)
        if support:
            self.campus._super(self.actor)
        self._scope("volunteer.member.manage", write=True)
        original = self._existing(rid, support)
        college, group = self._group(
            "volunteer.member.manage", write=True, semester_id=original.semester_id
        )
        row = self._existing(rid, support, lock=True)
        if row.lock_version != body.lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "成员资料已变化")
        if row.effective_from < business_today() and body.effective_from != row.effective_from:
            raise ConflictError(message="已经生效的历史开始日期不能修改，请另建后续有效期")
        if body.effective_to < business_today() and body.effective_to != row.effective_to:
            raise ConflictError(message="不能追溯缩短历史成员有效期")
        prepared = {
            "student_id": str(row.student_id),
            "semester_id": str(row.semester_id),
            "effective_from": body.effective_from,
            "effective_to": body.effective_to,
        }
        _, student, origin = self._input(prepared)
        if body.status == "ACTIVE":
            if group.status == "INACTIVE":
                raise ConflictError(message="组已停用")
            model = type(row)
            overlap = self.db.scalar(
                select(model.id)
                .where(
                    model.id != row.id,
                    model.group_id == self.gid,
                    model.student_id == student.id,
                    model.semester_id == row.semester_id,
                    (model.effective_from == body.effective_from)
                    | (
                        (model.status == "ACTIVE")
                        & (model.effective_from < body.effective_to)
                        & (model.effective_to > body.effective_from)
                    ),
                )
                .limit(1)
                .with_for_update()
            )
            if overlap:
                raise ConflictError(message="同组已有重叠有效期或相同开始日期记录")
            if origin != self.cid and not support:
                approved = self.db.scalar(
                    select(VolunteerGroupSupport.id)
                    .where(
                        VolunteerGroupSupport.college_id == self.cid,
                        VolunteerGroupSupport.group_id == self.gid,
                        VolunteerGroupSupport.student_id == row.student_id,
                        VolunteerGroupSupport.semester_id == row.semester_id,
                        VolunteerGroupSupport.status == "ACTIVE",
                        VolunteerGroupSupport.effective_from <= body.effective_from,
                        VolunteerGroupSupport.effective_to >= body.effective_to,
                    )
                    .limit(1)
                    .with_for_update()
                )
                if approved is None:
                    raise ConflictError(message="跨院支援未覆盖成员有效期")
        affected = self._future(row, lock=True)
        if affected and not body.confirm_future_assignments:
            raise ConflictError(message="存在未来受派任务，须确认保留并安排改派")
        row.effective_from, row.effective_to, row.status = (
            body.effective_from,
            body.effective_to,
            body.status,
        )
        row.lock_version += 1
        from app.modules.organization.impact_service import capture_impacts
        capture_impacts(self.db, self.cid, "support" if support else "member", row.id, row.lock_version,
                        task_ids=[int(value) for value in affected], after=self.campus._dto(row))
        result = self._save(
            row,
            college,
            group,
            "volunteer.support.update" if support else "volunteer.member.update",
        )
        return {**result, "retained_future_task_ids": affected}

    def _input(self, data):
        body = validated(MemberCreate, data)
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == int(body.semester_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if semester is None:
            raise NotFoundError("学期不存在")
        if semester.status != "ACTIVE":
            raise ConflictError(message="学期已停用")
        if not (
            semester.start_date
            <= body.effective_from
            < body.effective_to
            <= semester.end_date + timedelta(days=1)
        ):
            raise ConflictError(message="成员有效期须在学期内")
        student = self.db.scalar(
            select(Student)
            .where(Student.id == int(body.student_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if student is None:
            raise NotFoundError("学生不存在")
        enrollment = enrollment_on(self.db, student.id, body.effective_from)
        if enrollment:
            if enrollment.status != "ENROLLED":
                raise ConflictError(message="成员生效日期不属于在读学籍")
            cid = enrollment.college_id
        else:
            from app.modules.academic.enrollment_models import StudentEnrollment

            if self.db.scalar(
                select(StudentEnrollment.id)
                .where(StudentEnrollment.student_id == student.id)
                .limit(1)
            ):
                raise ConflictError(message="成员生效日学籍未知，不能使用当前班级推断")
            admin_class = (
                self.db.get(AdministrativeClass, student.administrative_class_id)
                if student.administrative_class_id
                else None
            )
            cid = admin_class.college_id if admin_class and student.status == "ACTIVE" else None
        if cid is None:
            raise ConflictError(message="成员学院归属未确认")
        return body, student, cid

    def _save(self, row, college, group, action, *, commit=True):
        group.lock_version += 1
        college.configuration_revision += 1
        self.db.add(row)
        self.db.flush()
        result = self.campus._dto(row)
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action=action,
                resource_type=row.__tablename__,
                resource_id=str(row.id),
                after_json=scoped_snapshot(result, self.cid),
            )
        )
        if commit:
            self.db.commit()
        return result

    def _prepare_create(self, data):
        requested = validated(MemberCreate, data)
        college, group = self._group(
            "volunteer.member.manage", write=True, semester_id=int(requested.semester_id)
        )
        if group.status == "INACTIVE":
            raise ConflictError(message="组已停用")
        body, student, origin = self._input(data)
        if origin != self.cid:
            supported = self.db.scalar(
                select(VolunteerGroupSupport.id)
                .where(
                    VolunteerGroupSupport.college_id == self.cid,
                    VolunteerGroupSupport.group_id == self.gid,
                    VolunteerGroupSupport.student_id == student.id,
                    VolunteerGroupSupport.semester_id == int(body.semester_id),
                    VolunteerGroupSupport.status == "ACTIVE",
                    VolunteerGroupSupport.effective_from <= body.effective_from,
                    VolunteerGroupSupport.effective_to >= body.effective_to,
                )
                .limit(1)
                .with_for_update()
            )
            if not supported:
                raise ConflictError(message="跨院成员须先由超管授权支援，且覆盖整个成员有效期")
        overlap = self.db.scalar(
            select(VolunteerGroupMember.id)
            .where(
                VolunteerGroupMember.group_id == self.gid,
                VolunteerGroupMember.student_id == student.id,
                VolunteerGroupMember.semester_id == int(body.semester_id),
                or_(
                    VolunteerGroupMember.effective_from == body.effective_from,
                    (VolunteerGroupMember.status == "ACTIVE")
                    & (VolunteerGroupMember.effective_from < body.effective_to)
                    & (VolunteerGroupMember.effective_to > body.effective_from),
                ),
            )
            .limit(1)
            .with_for_update()
        )
        if overlap:
            raise ConflictError(message="同组、同学期有效期重叠或已有相同生效日的历史成员记录")
        row = VolunteerGroupMember(
            college_id=self.cid,
            group_id=self.gid,
            student_id=student.id,
            semester_id=int(body.semester_id),
            effective_from=body.effective_from,
            effective_to=body.effective_to,
        )
        return row, college, group

    @atomic_write
    def create(self, data):
        row, college, group = self._prepare_create(data)
        return self._save(row, college, group, "volunteer.member.create")

    @atomic_write
    def authorize_support(self, data):
        self.campus._super(self.actor)
        requested = validated(MemberCreate, data)
        college, group = self._group(
            "volunteer.member.manage", write=True, semester_id=int(requested.semester_id)
        )
        body, student, origin = self._input(data)
        if origin == self.cid:
            raise ConflictError(message="本院成员不需要跨院支援授权")
        overlap = self.db.scalar(
            select(VolunteerGroupSupport.id)
            .where(
                VolunteerGroupSupport.college_id == self.cid,
                VolunteerGroupSupport.group_id == self.gid,
                VolunteerGroupSupport.student_id == student.id,
                VolunteerGroupSupport.semester_id == int(body.semester_id),
                VolunteerGroupSupport.status == "ACTIVE",
                VolunteerGroupSupport.effective_from < body.effective_to,
                VolunteerGroupSupport.effective_to > body.effective_from,
            )
            .limit(1)
            .with_for_update()
        )
        if overlap:
            raise ConflictError(message="同组、同学期已有重叠的有效支援授权")
        from app.modules.volunteer.preparation_models import semester_group_config
        version = semester_group_config(self.db, group, int(body.semester_id))
        config = version.configuration if version else {}
        row = VolunteerGroupSupport(
            college_id=self.cid,
            group_id=self.gid,
            student_id=student.id,
            semester_id=int(body.semester_id),
            effective_from=body.effective_from,
            effective_to=body.effective_to,
            authorized_by=self.actor.id,
            scope_snapshot={
                "group_config_version_id": str(version.id) if version else None,
                "course_type_ids": list(config.get("course_type_ids", [])),
                "class_mode": config.get("class_mode", "SPECIFIC"),
                "class_ids": list(config.get("class_ids", [])),
            },
        )
        return self._save(row, college, group, "volunteer.support.authorize")

    @atomic_write
    def revoke(
        self, member_id: int, version: int, *, support=False, confirm_future_assignments=False
    ):
        if support:
            self.campus._super(self.actor)
        model = VolunteerGroupSupport if support else VolunteerGroupMember
        self._scope("volunteer.member.manage", write=True)
        original = cast(
            VolunteerGroupSupport | VolunteerGroupMember | None,
            self.db.scalar(
                select(model).where(
                    model.id == member_id, model.college_id == self.cid, model.group_id == self.gid
                )
            ),
        )
        if original is None:
            raise NotFoundError()
        college, group = self._group(
            "volunteer.member.manage", write=True, semester_id=original.semester_id
        )
        row = cast(
            VolunteerGroupSupport | VolunteerGroupMember | None,
            self.db.scalar(
                select(model)
                .where(
                    model.id == member_id, model.college_id == self.cid, model.group_id == self.gid
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            raise NotFoundError()
        if row.lock_version != version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "成员或支援授权已变化")
        affected = list(
            self.db.scalars(
                select(InspectionTask.id)
                .join(InspectionAssignment, InspectionAssignment.task_id == InspectionTask.id)
                .join(UserAccount, UserAccount.id == InspectionAssignment.volunteer_user_id)
                .where(
                    InspectionTask.college_id == self.cid,
                    InspectionTask.group_id == self.gid,
                    InspectionTask.semester_id == row.semester_id,
                    InspectionTask.inspection_date >= max(row.effective_from, business_today()),
                    InspectionTask.inspection_date < row.effective_to,
                    InspectionTask.canceled_at.is_(None),
                    InspectionAssignment.revoked_at.is_(None),
                    UserAccount.student_id == row.student_id,
                )
                .order_by(InspectionTask.id)
                .with_for_update()
            )
        )
        if row.status == "ACTIVE" and affected and not confirm_future_assignments:
            raise ConflictError(
                message="存在未来受派任务，请确认影响并安排改派；不会自动删除受派事实"
            )
        row.status = "INACTIVE"
        row.lock_version += 1
        from app.modules.organization.impact_service import capture_impacts
        capture_impacts(self.db, self.cid, "support" if support else "member", row.id, row.lock_version,
                        task_ids=affected, after=self.campus._dto(row))
        result = self._save(
            row,
            college,
            group,
            "volunteer.support.revoke" if support else "volunteer.member.revoke",
        )
        return {**result, "retained_future_task_ids": [str(tid) for tid in affected]}
