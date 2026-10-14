"""Explicit college import URLs reuse the existing multipart contracts."""

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.path_scope import validate_college_id
from app.modules.importer.router import router as legacy_router
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}",
    tags=["college-import"],
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
            dependencies=route.dependencies,
            response_model=route.response_model,
            status_code=route.status_code,
            responses=route.responses,
            name=f"college_{route.name}",
            operation_id=f"college_{route.unique_id}",
        )
