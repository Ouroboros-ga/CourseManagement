"""确认整班课程来源。既有选修名单不猜测成公共课，历史任务不改写。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.modules.academic.enrollment_models import TeachingClassAudience
from app.modules.academic.models import AdministrativeClass, Semester, TeachingClass
from app.modules.audit.models import AuditLog
from app.modules.identity.authorization import require_resource_scope, resolve_scope


class AudienceService:
    def __init__(self, db: Session):
        self.db = db

    def set(
        self,
        actor_id: int,
        teaching_class_id: int,
        class_ids: list[int],
        expected_version: int,
        *,
        reason: str | None,
        request_id: str | None,
    ) -> dict:
        self.db.rollback()
        scope = resolve_scope(self.db, actor_id, "academic.manage")
        target = self.db.get(TeachingClass, teaching_class_id)
        if target is None:
            raise NotFoundError("教学班不存在")
        require_resource_scope(scope, target.college_id)
        semester = self.db.scalar(
            select(Semester).where(Semester.id == target.semester_id).with_for_update()
        )
        if semester is None or semester.status != "ACTIVE":
            raise ConflictError(message="学期不存在或已归档")
        self.db.refresh(target, with_for_update=True)
        if target.ownership_version != expected_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT)
        ids = sorted(set(class_ids))
        classes = list(
            self.db.scalars(
                select(AdministrativeClass)
                .where(AdministrativeClass.id.in_(ids))
                .order_by(AdministrativeClass.id)
                .with_for_update()
            )
        )
        if len(classes) != len(ids) or any(
            ac.status != "ACTIVE" or ac.college_id != target.college_id for ac in classes
        ):
            raise NotFoundError("名单来源包含外院、停用或不存在班级")
        old = list(
            self.db.scalars(
                select(TeachingClassAudience).where(
                    TeachingClassAudience.teaching_class_id == teaching_class_id
                )
            )
        )
        before = [str(row.administrative_class_id) for row in old]
        for row in old:
            self.db.delete(row)
        self.db.flush()
        self.db.add_all(
            [
                TeachingClassAudience(
                    teaching_class_id=teaching_class_id, administrative_class_id=cid
                )
                for cid in ids
            ]
        )
        target.ownership_version += 1
        after = {
            "teaching_class_id": str(target.id),
            "administrative_class_ids": [str(cid) for cid in ids],
            "ownership_version": target.ownership_version,
            "historical_task_policy": "KEEP_SNAPSHOTS",
        }
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="academic.audience.confirm",
                resource_type="teaching_class",
                resource_id=str(target.id),
                before_json={"administrative_class_ids": before},
                after_json=after,
                reason=reason,
                request_id=request_id,
            )
        )
        self.db.commit()
        return after
