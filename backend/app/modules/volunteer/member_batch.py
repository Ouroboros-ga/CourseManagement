"""Explicit student numbers, preview revision and one all-or-nothing transaction."""

from datetime import date

from pydantic import Field, model_validator
from sqlalchemy import select

from app.core.exceptions import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import Student, VolunteerQualification
from app.modules.academic.qualification_policy import enrollment_on
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport
from app.modules.volunteer.member_service import GroupMemberService


class MemberBatch(StrictModel):
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    effective_from: date
    effective_to: date
    student_nos: list[str] = Field(min_length=1, max_length=200)
    expected_names: dict[str, str] = Field(default_factory=dict, max_length=200)
    enable_qualification: bool = False
    skip_existing: bool = False

    @model_validator(mode="after")
    def valid(self):
        if int(self.semester_id) >= 2**63 or self.effective_from >= self.effective_to:
            raise ValueError("学期或日期范围无效")
        if any(
            not value or value != value.strip() or len(value) > 64 for value in self.student_nos
        ) or len(set(self.student_nos)) != len(self.student_nos):
            raise ValueError("学号应非空且不重复，每条最多64字符")
        if self.expected_names and (
            set(self.expected_names) != set(self.student_nos)
            or any(not n.strip() or len(n) > 128 for n in self.expected_names.values())
        ):
            raise ValueError("姓名必须与每个学号一一对应")
        self.student_nos = sorted(self.student_nos)
        return self


class MemberBatchCommit(MemberBatch):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class GroupMemberBatchService:
    def __init__(self, db, actor, cid, gid):
        self.db, self.actor, self.cid, self.gid = db, actor, cid, gid
        self.members = GroupMemberService(db, actor, cid, gid)

    def _preview(self, data):
        body = validated(MemberBatch, data)
        college, group = self.members._group(
            "volunteer.member.manage", write=True, semester_id=int(body.semester_id)
        )
        if body.enable_qualification:
            self.members.campus._authorize(self.actor, self.cid, "volunteer.manage", write=True)
        students = {
            s.student_no: s
            for s in self.db.scalars(
                select(Student)
                .where(Student.student_no.in_(body.student_nos))
                .order_by(Student.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        }
        if not body.expected_names and set(students) != set(body.student_nos):
            raise NotFoundError("部分学号不存在或不能纳入，请核对后整批重试")
        prepared, snapshots, items, issues, qualifications = [], [], [], [], []
        for no in body.student_nos:
            student = students.get(no)
            item = {"student_no": no, "name": body.expected_names.get(no, ""), "status": "BLOCKED"}
            try:
                if student is None:
                    raise NotFoundError("学号不存在，请先在学生与班级中建立学籍")
                request = {
                    "student_id": str(student.id),
                    "semester_id": body.semester_id,
                    "effective_from": body.effective_from,
                    "effective_to": body.effective_to,
                }
                _, _, origin = self.members._input(request)
                existing = (
                    self.db.scalar(
                        select(VolunteerGroupMember)
                        .where(
                            VolunteerGroupMember.group_id == self.gid,
                            VolunteerGroupMember.student_id == student.id,
                            VolunteerGroupMember.semester_id == int(body.semester_id),
                            VolunteerGroupMember.status == "ACTIVE",
                            VolunteerGroupMember.effective_from == body.effective_from,
                            VolunteerGroupMember.effective_to == body.effective_to,
                        )
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if body.skip_existing
                    else None
                )
                if existing is None:
                    row, _, _ = self.members._prepare_create(request)
                else:
                    row = None
                    if origin != self.cid and not self.db.scalar(
                        select(VolunteerGroupSupport.id)
                        .where(
                            VolunteerGroupSupport.group_id == self.gid,
                            VolunteerGroupSupport.college_id == self.cid,
                            VolunteerGroupSupport.student_id == student.id,
                            VolunteerGroupSupport.semester_id == int(body.semester_id),
                            VolunteerGroupSupport.status == "ACTIVE",
                            VolunteerGroupSupport.effective_from <= body.effective_from,
                            VolunteerGroupSupport.effective_to >= body.effective_to,
                        )
                        .with_for_update()
                    ):
                        raise ConflictError(message="跨院成员须有覆盖整个成员有效期的支援授权")
                if body.expected_names and student.name.strip() != body.expected_names[no].strip():
                    raise ConflictError(
                        message="姓名与该学号的已有档案不一致，请核对，不会自动改名"
                    )
                qualification = self.db.scalar(
                    select(VolunteerQualification)
                    .where(
                        VolunteerQualification.student_id == student.id,
                        VolunteerQualification.semester_id == int(body.semester_id),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                # _input has checked the latest enrollment at the membership date;
                # do not re-read it through an older MySQL RR snapshot here.
                needs_qualification = body.enable_qualification and not (
                    qualification is not None
                    and qualification.enabled
                    and qualification.college_id == origin
                )
                if needs_qualification:
                    if origin != self.cid:
                        raise ConflictError(
                            message="跨院学生须先由学籍所属学院开通有效资格，再按支援授权加入本组"
                        )
                    from app.modules.academic.scoped_writes import ScopedAcademicWriteService
                    from app.modules.identity.role_scope import business_today

                    current = enrollment_on(self.db, student.id, business_today(), lock=True)
                    if current and (current.status != "ENROLLED" or current.college_id != self.cid):
                        raise ConflictError(message="仅本学院当前在读学生可以开通资格")

                    academic = ScopedAcademicWriteService(self.db, self.actor, self.cid)
                    owned = academic._repo("volunteer.manage", write=True).get(
                        "students", student.id, lock=True
                    )
                    if academic._dto(owned)["status"] != "ACTIVE":
                        raise ConflictError(message="仅当前在读学生可以开通本学期志愿者资格")
                    if qualification is not None and qualification.college_id != self.cid:
                        raise ConflictError(message="原资格归属不同，请先完成学籍与资格交接")
                    qualifications.append(student)
                enrollment = enrollment_on(self.db, student.id, body.effective_from, lock=True)
                snapshots.append(
                    {
                        "student": {
                            c.name: getattr(student, c.name) for c in student.__table__.columns
                        },
                        "enrollment": dict(enrollment._mapping) if enrollment else None,
                        "qualification": self.members.campus._dto(qualification)
                        if qualification
                        else None,
                        "member": self.members.campus._dto(existing) if existing else None,
                    }
                )
                if row is not None:
                    prepared.append(row)
                item.update(
                    student_id=str(student.id),
                    name=student.name,
                    status="UNCHANGED" if existing else "ADD",
                    qualification_action="ENABLE" if needs_qualification else "KEEP",
                )
            except PermissionDeniedError:
                raise
            except AppError as exc:
                if not body.expected_names:
                    raise
                item["message"] = exc.message
                issues.append({"student_no": no, "message": exc.message})
            items.append(item)
        revision = fingerprint(
            {
                "body": body.model_dump(mode="json"),
                "college_revision": college.configuration_revision,
                "authorization_revision": college.authorization_revision,
                "group": [group.id, group.lock_version],
                "students": snapshots,
                "issues": issues,
            }
        )
        return (
            college,
            group,
            prepared,
            qualifications,
            {
                "revision": revision,
                "count": len(items),
                "items": items,
                "can_commit": not issues,
                "issues": issues,
                "qualifications_to_enable": len(qualifications),
                "unchanged": sum(i["status"] == "UNCHANGED" for i in items),
                "effective_from": body.effective_from,
                "effective_to": body.effective_to,
            },
            body,
        )

    def preview(self, data):
        return self._preview(data)[4]

    def _apply(self, college, group, prepared, qualifications, preview, body):
        if not preview["can_commit"]:
            raise ConflictError(message="仍有学号、姓名、学籍或成员冲突，请处理后整批重试")
        from app.modules.academic.scoped_writes import ScopedAcademicWriteService

        academic = ScopedAcademicWriteService(self.db, self.actor, self.cid)
        for student in qualifications:
            academic.upsert_qualification(
                {
                    "student_id": student.id,
                    "semester_id": int(body.semester_id),
                    "student_lock_version": student.lock_version,
                    "enabled": True,
                    "reason": "加入志愿者组时开通资格",
                },
                commit=False,
            )
        result = [
            self.members._save(row, college, group, "volunteer.member.batch_create", commit=False)
            for row in prepared
        ]
        self.db.commit()
        return {
            "created": len(result),
            "items": result,
            "qualifications_enabled": len(qualifications),
            "unchanged": preview["unchanged"],
        }

    @atomic_write
    def commit(self, data, revision):
        context = self._preview(data)
        if revision != context[4]["revision"]:
            raise ConflictError(message="成员、学籍、支援或组配置已变化，请重新预览")
        return self._apply(*context)

    @atomic_write
    def enroll_one(self, data):
        from app.modules.volunteer.member_schemas import MemberCreate

        requested = validated(MemberCreate, data)
        self.members._group(
            "volunteer.member.manage", write=True, semester_id=int(requested.semester_id)
        )
        _, student, _ = self.members._input(data)
        context = self._preview(
            {
                "semester_id": requested.semester_id,
                "student_nos": [student.student_no],
                "effective_from": requested.effective_from,
                "effective_to": requested.effective_to,
                "enable_qualification": True,
            }
        )
        return self._apply(*context)["items"][0]
