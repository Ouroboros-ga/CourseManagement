"""学籍交接待复核的显式学院入口。"""

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.modules.academic.enrollment_router import router as original
from app.modules.academic.scoped_router import require_scoped_academic_enabled
from app.modules.identity.path_scope import validate_college_id
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}/academic",
    tags=["college-enrollment"],
    dependencies=[
        Depends(require_campus_enabled),
        Depends(require_scoped_academic_enabled),
        Depends(validate_college_id),
    ],
)
for route in original.routes:
    if not isinstance(route, APIRoute) or not route.path.startswith("/enrollment-handoff/tasks"):
        continue
    router.add_api_route(
        route.path,
        route.endpoint,
        methods=sorted(route.methods or set()),
        dependencies=route.dependencies,
        response_model=route.response_model,
        status_code=route.status_code,
        responses=route.responses,
        name=f"college_{route.name}",
        operation_id=f"college_{route.unique_id}",
    )
