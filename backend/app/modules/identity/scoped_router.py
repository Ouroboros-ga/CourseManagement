"""绑定管理显式学院入口，微信本人绑定与登录保持原契约。"""

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.path_scope import validate_college_id
from app.modules.identity.router import router as legacy
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}",
    tags=["college-binding"],
    dependencies=[
        Depends(require_campus_enabled),
        Depends(require_business_scoped_enabled),
        Depends(validate_college_id),
    ],
)
for route in legacy.routes:
    if not isinstance(route, APIRoute) or not (
        route.path.startswith(("/students/", "/binding-tokens/"))
        or route.path in {"/role-assignment-targets", "/optional-permission-targets"}
        or route.path.endswith("/student-binding-reset")
    ):
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
