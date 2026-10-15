"""组范围先筛选再按班级精确抽查；缺额或搜索上限均不跨范围补数。"""

import hashlib
import json
import random
from datetime import date
from typing import Annotated

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import AdministrativeClass, Semester, TeachingClass
from app.modules.academic.time_models import CollegeTimeVersion
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.course_occurrences import build_scope
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import (
    AutoAssignRequest,
    CourseOccurrenceScope,
    InspectionGenerateRequest,
)
from app.modules.inspection.service import InspectionService
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.models import VolunteerGroup


def choose_exact(candidates: list[tuple[str, frozenset[int]]], counts: dict[int, int], seed: str):
    if (
        not counts
        or any(type(n) is not int or not 1 <= n <= 50 for n in counts.values())
        or sum(counts.values()) > 500
    ):
        raise ConflictError(message="抽查配额须为每班1至50，合计不超过500")
    if len({key for key, _ in candidates}) != len(candidates):
        raise ConflictError(message="候选课次标识重复")
    rows = [(key, classes) for key, classes in candidates if classes and classes <= counts.keys()]
    for cid, count in counts.items():
        if sum(cid in classes for _, classes in rows) < count:
            raise ConflictError(message=f"班级 {cid} 在组范围内课次不足，整批未生成")
    random.Random(seed).shuffle(rows)
    remaining, selected, used = dict(counts), [], set()
    budget, limited = 10000, False

    def solve():
        nonlocal budget, limited
        if not any(remaining.values()):
            return True
        budget -= 1
        if budget < 0:
            limited = True
            return False
        available = [
            (key, classes)
            for key, classes in rows
            if key not in used and all(remaining[c] > 0 for c in classes)
        ]
        needed = [c for c, n in remaining.items() if n]
        options = {cid: [r for r in available if cid in r[1]] for cid in needed}
        if any(len(options[c]) < remaining[c] for c in needed):
            return False
        cid = min(needed, key=lambda c: (len(options[c]), c))
        for key, classes in options[cid]:
            used.add(key)
            selected.append(key)
            for c in classes:
                remaining[c] -= 1
            if solve():
                return True
            for c in classes:
                remaining[c] += 1
            used.remove(key)
            selected.pop()
            if limited:
                return False
        return False

    if not solve():
        raise ConflictError(
            message="抽查组合搜索达到上限，请缩小范围"
            if limited
            else "合班课次不能同时满足各班精确配额，整批未生成"
        )
    return sorted(selected)


class GroupSampleRequest(StrictModel):
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    date_from: date
    date_to: date
    counts: dict[str, Annotated[int, Field(ge=1, le=50, strict=True)]] = Field(
        min_length=1, max_length=100
    )
    draw_id: str = Field(min_length=1, max_length=64)
    require_photo: bool = True

    @model_validator(mode="after")
    def scope(self):
        if not 0 <= (self.date_to - self.date_from).days < 31:
            raise ValueError("抽查范围须为1至31天")
        if int(self.semester_id) >= 2**63 or any(
            not k.isascii() or not k.isdigit() or not 0 < int(k) < 2**63 or str(int(k)) != k
            for k in self.counts
        ):
            raise ValueError("学期或班级标识无效")
        if sum(self.counts.values()) > 500:
            raise ValueError("抽查配额合计不超过500")
        return self


class GroupSampleConfirm(GroupSampleRequest):
    selection_revision: str = Field(min_length=64, max_length=64)


class GroupAssignRequest(StrictModel):
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    task_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def valid_ids(self):
        if len(set(self.task_ids)) != len(self.task_ids) or any(
            not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63
            for value in [self.semester_id, *self.task_ids]
        ):
            raise ValueError("排班任务集合标识无效或重复")
        return self


class GroupSamplingService:
    def __init__(self, db: Session, actor, cid: int, gid: int):
        self.db, self.actor, self.cid, self.gid = db, actor, cid, gid

    @atomic_write
    def assign(self, data, request_id=None):
        body = validated(GroupAssignRequest, data)
        scope = resolve_scope(self.db, self.actor, self.cid, "assignment.manage", write=True)
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == int(body.semester_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if semester is None or semester.status != "ACTIVE":
            raise NotFoundError("学期不存在或已停用")
        tasks = set(
            self.db.scalars(
                select(InspectionTask.id).where(
                    InspectionTask.id.in_([int(tid) for tid in body.task_ids]),
                    InspectionTask.college_id == self.cid,
                    InspectionTask.group_id == self.gid,
                    InspectionTask.semester_id == semester.id,
                    scope.task_condition(),
                )
            )
        )
        if tasks != {int(tid) for tid in body.task_ids}:
            raise NotFoundError("任务集合包含外院、其他组或其他学期资源，整批未排班")
        from app.modules.inspection.scoped_service import ScopedInspectionService

        return ScopedInspectionService(self.db, self.actor, self.cid).auto_assign(
            self.actor,
            AutoAssignRequest(semester_id=semester.id, task_ids=sorted(tasks), reason=body.reason),
            request_id,
        )

    def _build(self, data, *, write=False):
        body = validated(GroupSampleRequest, data)
        scope = resolve_scope(self.db, self.actor, self.cid, "inspection.generate", write=write)
        semester_query = select(Semester).where(Semester.id == int(body.semester_id))
        if write:
            semester_query = semester_query.with_for_update().execution_options(
                populate_existing=True
            )
        semester = self.db.scalar(semester_query)
        if semester is None or semester.status != "ACTIVE":
            raise NotFoundError("学期不存在或已停用")
        group_query = select(VolunteerGroup).where(
            VolunteerGroup.id == self.gid, VolunteerGroup.college_id == self.cid
        )
        if write:
            group_query = group_query.with_for_update().execution_options(populate_existing=True)
        group = self.db.scalar(group_query)
        from app.modules.volunteer.preparation_models import semester_group_config
        version = semester_group_config(self.db, group, semester.id) if group else None
        if group is None or group.status != "ACTIVE" or version is None:
            raise ConflictError(message="组尚未启用或未发布查课范围")
        requested = {int(k): n for k, n in body.counts.items()}
        classes = list(
            self.db.scalars(
                select(AdministrativeClass).where(
                    AdministrativeClass.college_id == self.cid,
                    AdministrativeClass.id.in_(requested),
                    AdministrativeClass.status == "ACTIVE",
                )
            )
        )
        if len(classes) != len(requested):
            raise NotFoundError("抽查班级不在本院或已停用")
        config = version.configuration
        if config["class_mode"] == "SPECIFIC" and not requested.keys() <= {
            int(v) for v in config["class_ids"]
        }:
            raise NotFoundError("抽查班级不在组查课范围")
        teaching = list(
            self.db.scalars(
                select(TeachingClass)
                .join(CourseType, CourseType.id == TeachingClass.course_type_id)
                .where(
                    TeachingClass.college_id == self.cid,
                    TeachingClass.semester_id == semester.id,
                    TeachingClass.status == "ACTIVE",
                    CourseType.college_id == self.cid,
                    CourseType.status == "ACTIVE",
                    CourseType.id.in_([int(v) for v in config["course_type_ids"]]),
                )
                .order_by(TeachingClass.id)
            )
        )
        inspection = InspectionService(self.db)
        inspection._repo.college_ids = frozenset({self.cid})
        inspection._generation_group = group, version
        inspection._generation_scope = scope
        inspection._target_class_filter = frozenset(requested)
        occurrence_scope = CourseOccurrenceScope(
            date_from=body.date_from,
            date_to=body.date_to,
            teaching_class_ids=[t.id for t in teaching],
            require_photo=body.require_photo,
        )
        plans, source_revision = (
            build_scope(inspection, semester, occurrence_scope) if teaching else ([], "EMPTY_SCOPE")
        )
        candidates = []
        scoped_plans = []
        for plan in plans:
            from dataclasses import replace
            from app.modules.inspection.responsibility import normalize_plan
            roster = [m for m in plan.roster if m.administrative_class_id_snapshot in requested]
            if not roster:
                continue
            plan = normalize_plan(inspection, replace(plan, roster=roster, student_ids=[m.student_id for m in roster]))
            scoped_plans.append(plan)
            if (group.starts_on and plan.inspection_date < group.starts_on) or (
                group.ends_on and plan.inspection_date > group.ends_on
            ):
                continue
            roster_classes = frozenset(
                m.administrative_class_id_snapshot
                for m in plan.roster
                if m.administrative_class_id_snapshot and m.college_id_snapshot == self.cid
            )
            if len(
                [
                    m
                    for m in plan.roster
                    if m.college_id_snapshot != self.cid or not m.administrative_class_id_snapshot
                ]
            ):
                continue
            if roster_classes and roster_classes <= requested.keys():
                candidates.append((plan.task_key, roster_classes))
        time_ids = list(
            self.db.scalars(
                select(CollegeTimeVersion.id)
                .where(
                    CollegeTimeVersion.college_id == self.cid,
                    CollegeTimeVersion.semester_id == semester.id,
                )
                .order_by(CollegeTimeVersion.id)
            )
        )
        payload = {
            "body": body.model_dump(mode="json"),
            "group": [group.id, group.lock_version, version.id],
            "authorization": scope.authorization_revision,
            "source": source_revision,
            "time_versions": time_ids,
            "teaching": [[t.id, t.course_type_id, t.classification_revision] for t in teaching],
            "candidates": [[k, sorted(c)] for k, c in candidates],
        }
        revision = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        selected_keys = choose_exact(candidates, requested, revision)
        selected = [p for p in scoped_plans if p.task_key in set(selected_keys)]
        # A group owns an occurrence; it must not create another occurrence identity.
        if selected:
            existing = self.db.scalars(select(InspectionTask).where(
                InspectionTask.task_key.in_([p.task_key for p in selected])
            ))
            if any(task.group_id != self.gid for task in existing):
                raise ConflictError(message="所选课次已有其他执行组任务，请先明确处理换组，不能重复生成")
        inspection._generation_group = (group, version)
        return (
            body,
            inspection,
            semester,
            selected,
            {
                "selection_revision": revision,
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "counts": body.counts,
                "items": [
                    inspection._to_planned_brief(p).model_dump(mode="json") for p in selected
                ],
            },
        )

    def preview(self, data):
        return self._build(data)[4]

    @atomic_write
    def generate(self, data, revision: str, request_id=None):
        body, inspection, semester, selected, preview = self._build(data, write=True)
        if revision != preview["selection_revision"]:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "课次、组配置或授权已变化，请重新预览")
        request = InspectionGenerateRequest(
            semester_id=semester.id,
            inspection_type="COURSE",
            date_from=body.date_from,
            date_to=body.date_to,
            teaching_class_ids=sorted({p.teaching_class_id for p in selected}),
            require_photo=body.require_photo,
        )
        return inspection._materialize(semester, request, selected, self.actor.id, request_id)
