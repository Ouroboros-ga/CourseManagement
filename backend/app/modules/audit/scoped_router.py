from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.audit.router import router as legacy_router
from app.modules.identity.path_scope import validate_college_id
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}",
    tags=["college-audit"],
    dependencies=[
        Depends(require_campus_enabled),
        Depends(require_business_scoped_enabled),
        Depends(validate_college_id),
    ],
)
for route in legacy_router.routes:
    if isinstance(route, APIRoute):
        router.add_api_route(
            route.path,
            route.endpoint,
            methods=sorted(route.methods or set()),
            name=f"college_{route.name}",
            operation_id=f"college_{route.unique_id}",
        )
