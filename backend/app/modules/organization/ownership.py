"""存量业务归属预览与回填。仅超管，明确映射，父链传播，不支持迁院。"""

import hashlib
import json
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.academic.models import AdministrativeClass, CourseSchedule, TeachingClass
from app.modules.audit.models import AuditLog
from app.modules.importer.models import ImportBatch
from app.modules.inspection.models import InspectionTask
from app.modules.organization.models import College
from app.modules.organization.service import CampusService, atomic_write
from app.modules.report.models import Report

OwnedModel = (
    type[AdministrativeClass]
    | type[TeachingClass]
    | type[CourseSchedule]
    | type[InspectionTask]
    | type[ImportBatch]
    | type[Report]
)
OwnedRow = (
    AdministrativeClass | TeachingClass | CourseSchedule | InspectionTask | ImportBatch | Report
)
ROOTS: dict[str, OwnedModel] = {
    "administrative_class": AdministrativeClass,
    "teaching_class": TeachingClass,
    "course_schedule": CourseSchedule,
    "inspection_task": InspectionTask,
    "import_batch": ImportBatch,
    "report": Report,
}
EXPLICIT = {"administrative_class", "teaching_class", "import_batch", "report"}
PARENTS = {
    "course_schedule": (("teaching_class_id", "teaching_class"),),
    "inspection_task": (
        ("course_schedule_id", "course_schedule"),
        ("teaching_class_id", "teaching_class"),
        ("administrative_class_id", "administrative_class"),
    ),
    "import_batch": (("teaching_class_id", "teaching_class"),),
}


class OwnershipService:
    def __init__(self, db: Session, request_id: str | None = None):
        self.db = db
        self.campus = CampusService(db, request_id)
        self.request_id = request_id

    def unresolved(self, actor, kind: str, *, after_id: int = 0, limit: int = 100):
        self.campus._super(actor)
        if kind not in EXPLICIT or not 1 <= limit <= 200 or after_id < 0:
            raise AppError(ErrorCode.VALIDATION_ERROR, "未知资源类型或分页参数", 422)
        model = ROOTS[kind]
        rows = cast(
            list[OwnedRow],
            list(
                self.db.scalars(
                    select(model)
                    .where(model.college_id.is_(None), model.id > after_id)
                    .order_by(model.id)
                    .limit(limit + 1)
                )
            ),
        )
        return {
            "items": [
                {
                    "id": str(row.id),
                    "label": getattr(row, "class_name", f"{kind} #{row.id}"),
                    "legacy_college_text": getattr(row, "college", None),
                }
                for row in rows[:limit]
            ],
            "next_after_id": str(rows[limit - 1].id) if len(rows) > limit else None,
        }

    def _plan(self, actor, mappings, *, lock=False):
        self.campus._super(actor)
        if set(mappings) - EXPLICIT:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "只允许明确映射行政班、教学班、独立导入和报表", 422
            )
        stmt = select(College).order_by(College.id).execution_options(populate_existing=True)
        if lock:
            stmt = stmt.with_for_update()
        colleges = {row.id: row for row in self.db.scalars(stmt)}
        rows = {}
        snapshot = []
        for kind, model in ROOTS.items():
            stmt = (
                select(model)
                .order_by(model.id)
                .limit(50001)
                .execution_options(populate_existing=True)
            )
            if lock:
                stmt = stmt.with_for_update()
            items = list(self.db.scalars(stmt))
            if len(items) > 50000:
                raise ConflictError(message="存量超过单批上限，请先安排分批迁移工具")
            rows[kind] = {row.id: row for row in items}
            for row in items:
                snapshot.append(
                    [
                        kind,
                        str(row.id),
                        row.college_id,
                        row.ownership_version,
                        str(row.updated_at),
                        [(field, getattr(row, field)) for field, _ in PARENTS.get(kind, ())],
                    ]
                )
        owners = {
            (kind, rid): row.college_id
            for kind, items in rows.items()
            for rid, row in items.items()
        }
        conflicts = []
        for kind, entries in mappings.items():
            for rid_text, cid_text in entries.items():
                try:
                    rid, cid = int(rid_text), int(cid_text)
                    if (
                        str(rid) != rid_text
                        or str(cid) != cid_text
                        or not (0 < rid < 2**63 and 0 < cid < 2**63)
                    ):
                        raise ValueError()
                except (ValueError, TypeError) as exc:
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR, "标识必须为标准 BIGINT 字符串", 422
                    ) from exc
                if rid not in rows[kind] or cid not in colleges:
                    raise NotFoundError()
                if colleges[cid].status != "ACTIVE":
                    raise ConflictError(message="目标学院已停用")
                previous = owners[kind, rid]
                if previous is not None and previous != cid:
                    conflicts.append(
                        {"kind": kind, "id": rid_text, "reason": "KNOWN_OWNER_IMMUTABLE"}
                    )
                else:
                    owners[kind, rid] = cid
        for kind, parents in PARENTS.items():
            for rid, row in rows[kind].items():
                links = [
                    (target, getattr(row, field))
                    for field, target in parents
                    if getattr(row, field) is not None
                ]
                if not links:
                    continue
                parent_owners = [owners.get((target, pid)) for target, pid in links]
                known = {owner for owner in parent_owners if owner is not None}
                current = owners[kind, rid]
                if len(known) > 1 or (current is not None and known and current not in known):
                    conflicts.append(
                        {"kind": kind, "id": str(rid), "reason": "PARENT_OWNER_CONFLICT"}
                    )
                elif None in parent_owners:
                    # 一个目标已确定、另一个未知，不把部分证据当作完整归属。
                    if current is not None:
                        conflicts.append(
                            {"kind": kind, "id": str(rid), "reason": "PARENT_OWNER_UNRESOLVED"}
                        )
                elif known:
                    owners[kind, rid] = next(iter(known))
        changes = [
            {
                "kind": kind,
                "id": str(rid),
                "college_id": str(cid),
                "ownership_version": rows[kind][rid].ownership_version,
            }
            for (kind, rid), cid in owners.items()
            if cid is not None and rows[kind][rid].college_id is None
        ]
        revision = hashlib.sha256(
            json.dumps(
                {
                    "rows": snapshot,
                    "mappings": mappings,
                    "colleges": [(c.id, c.status, c.lock_version) for c in colleges.values()],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        public = {
            "revision": revision,
            "changes": changes,
            "conflicts": conflicts,
            "unresolved": {
                kind: sum(owners[kind, rid] is None for rid in items)
                for kind, items in rows.items()
            },
            "business_ready": False,
        }
        return public, rows

    def preview(self, actor, mappings):
        result, _ = self._plan(actor, mappings)
        return result

    @atomic_write
    def apply(self, actor, mappings, revision):
        result, rows = self._plan(actor, mappings, lock=True)
        if result["revision"] != revision:
            raise ConflictError(ErrorCode.SELECTION_STALE, "存量数据或映射已变化，请重新预览")
        if result["conflicts"]:
            raise ConflictError(message="归属冲突尚未处理，整批未写入")
        for change in result["changes"]:
            row = rows[change["kind"]][int(change["id"])]
            row.college_id = int(change["college_id"])
            row.ownership_version += 1
            if change["kind"] == "administrative_class":
                from app.modules.academic.enrollment_models import StudentEnrollment
                from app.modules.academic.models import VolunteerQualification

                baselines = list(
                    self.db.scalars(
                        select(StudentEnrollment).where(
                            StudentEnrollment.administrative_class_id == row.id,
                            StudentEnrollment.revision == 0,
                            StudentEnrollment.historical_confirmed.is_(False),
                            StudentEnrollment.superseded.is_(False),
                            StudentEnrollment.college_id.is_(None),
                        )
                    )
                )
                for baseline in baselines:
                    baseline.college_id = row.college_id
                    owner = self.db.get(College, row.college_id)
                    baseline.snapshot = {
                        **baseline.snapshot,
                        "college_id": str(row.college_id),
                        "college_name": owner.name if owner else row.college,
                        "ownership_confirmation": revision,
                    }
                    for qualification in self.db.scalars(
                        select(VolunteerQualification).where(
                            VolunteerQualification.student_id == baseline.student_id,
                            VolunteerQualification.college_id.is_(None),
                        )
                    ):
                        qualification.college_id = row.college_id
        self.db.add(
            AuditLog(
                actor_user_id=actor.id,
                action="campus.ownership.backfill",
                resource_type="CampusOwnership",
                resource_id=revision,
                after_json={"changes": result["changes"], "unresolved": result["unresolved"]},
                request_id=self.request_id,
            )
        )
        self.db.commit()
        return {
            "updated": len(result["changes"]),
            "unresolved": result["unresolved"],
            "business_ready": False,
        }
