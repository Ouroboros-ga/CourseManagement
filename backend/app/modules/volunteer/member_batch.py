"""Explicit student numbers, preview revision and one all-or-nothing transaction."""
from datetime import date

from pydantic import Field, model_validator
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Student
from app.modules.academic.qualification_policy import enrollment_on
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.member_service import GroupMemberService


class MemberBatch(StrictModel):
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    effective_from: date
    effective_to: date
    student_nos: list[str] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid(self):
        if int(self.semester_id) >= 2**63 or self.effective_from >= self.effective_to:
            raise ValueError("学期或日期范围无效")
        if any(not value or value != value.strip() or len(value) > 64 for value in self.student_nos) or len(set(self.student_nos)) != len(self.student_nos):
            raise ValueError("学号应非空且不重复，每条最多64字符")
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
        college, group = self.members._group("volunteer.member.manage", write=True, semester_id=int(body.semester_id))
        students = list(self.db.scalars(select(Student).where(Student.student_no.in_(body.student_nos)).order_by(Student.id).with_for_update().execution_options(populate_existing=True)))
        if {row.student_no for row in students} != set(body.student_nos):
            raise NotFoundError("部分学号不存在或不能纳入，请核对后整批重试")
        prepared, snapshots, items = [], [], []
        for student in students:
            request = {"student_id": str(student.id), "semester_id": body.semester_id,
                       "effective_from": body.effective_from, "effective_to": body.effective_to}
            row, _, _ = self.members._prepare_create(request)
            enrollment = enrollment_on(self.db, student.id, body.effective_from)
            snapshots.append({"student": {c.name: getattr(student, c.name) for c in student.__table__.columns},
                              "enrollment": {c.name: getattr(enrollment, c.name) for c in enrollment.__table__.columns} if enrollment else None})
            prepared.append(row)
            items.append({"student_id": str(student.id), "student_no": student.student_no, "name": student.name})
        revision = fingerprint({"body": body.model_dump(mode="json"), "college_revision": college.configuration_revision,
            "authorization_revision": college.authorization_revision, "group": [group.id, group.lock_version], "students": snapshots})
        return college, group, prepared, {"revision": revision, "count": len(items), "items": items,
            "effective_from": body.effective_from, "effective_to": body.effective_to}

    def preview(self, data):
        return self._preview(data)[3]

    @atomic_write
    def commit(self, data, revision):
        college, group, prepared, preview = self._preview(data)
        if revision != preview["revision"]:
            raise ConflictError(message="成员、学籍、支援或组配置已变化，请重新预览")
        result = [self.members._save(row, college, group, "volunteer.member.batch_create", commit=False) for row in prepared]
        self.db.commit()
        return {"created": len(result), "items": result}
