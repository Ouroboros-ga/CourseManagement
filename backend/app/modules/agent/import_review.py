"""Summarize existing deterministic previews without returning personal rows or saving data."""

from collections import Counter

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.agent.run_context import RunContext
from app.modules.agent.schemas import ImportReviewQuery
from app.modules.importer.confirmation_set import ImportConfirmationSet
from app.modules.importer.scoped_service import ScopedImporterService


def review_previews(db: Session, context: RunContext, query: ImportReviewQuery) -> dict:
    settings = get_settings()
    if (
        context.college_id is None
        or not settings.campus_configuration_enabled
        or not settings.campus_business_scoped_enabled
    ):
        raise PermissionDeniedError("学院资料导入尚未启用")
    service = ScopedImporterService(db, context.actor, context.college_id)
    ids = sorted(int(value) for value in query.batch_ids)
    with service.operation("import.execute"):
        for bid in ids:
            batch = service._repo.get_for_update(bid)
            # Tool scope is intentionally narrower than the shared administrator preview UI.
            if (
                batch is None
                or batch.created_by != context.actor.id
                or (batch.semester_id is not None and batch.semester_id != context.semester_id)
            ):
                raise NotFoundError("资料预览不在本次工作区")
            if batch.teaching_class_id is not None:
                teaching_class = service._academic.get_teaching_class(batch.teaching_class_id)
                if teaching_class is None or teaching_class.semester_id != context.semester_id:
                    raise NotFoundError("资料预览不在本次工作区")
        plan = ImportConfirmationSet(service).preview(ids)
    files = []
    for item in plan["files"]:
        counts = Counter(change["action"] for change in item["changes"])
        files.append(
            {
                "batch_id": item["id"],
                "target": item["target"],
                "changes": dict(counts),
                "error_count": sum(i.get("severity") == "error" for i in item["issues"]),
                "warning_count": sum(i.get("severity") == "warning" for i in item["issues"]),
            }
        )
    return {
        "kind": "IMPORT_PREVIEW_REVIEW",
        "college_id": str(context.college_id),
        "semester_id": str(context.semester_id) if context.semester_id is not None else None,
        "files": files,
        "can_confirm": plan["can_confirm"],
        "requires_human_confirmation": True,
        "business_data_applied": False,
        "message": "请在资料核对页面查看具体变化和冲突，人工确认后保存。",
    }
