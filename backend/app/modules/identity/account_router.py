"""教师账号与本人改密入口。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.modules.identity.account_schemas import (
    PasswordChange,
    PasswordReset,
    TeacherAccountCreate,
    TeacherAccountUpdate,
)
from app.modules.identity.account_service import AccountService
from app.modules.identity.deps import CurrentUserDep

router = APIRouter(tags=["accounts"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> AccountService:
    return AccountService(db)


ServiceDep = Annotated[AccountService, Depends(get_service)]


@router.get("/teacher-accounts")
def list_teachers(
    actor: CurrentUserDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    query: Annotated[str | None, Query(max_length=128)] = None,
    status: Literal["ACTIVE", "DISABLED", "BANNED"] | None = None,
) -> dict:
    return success(
        service.list_accounts(actor, params, query, status),
        getattr(request.state, "request_id", None),
    )


@router.post("/teacher-accounts", status_code=201)
def create_teacher(
    actor: CurrentUserDep, service: ServiceDep, request: Request, body: TeacherAccountCreate
) -> dict:
    rid = getattr(request.state, "request_id", None)
    return success(service.create(actor, body, rid), rid)


@router.patch("/teacher-accounts/{user_id}")
def update_teacher(
    user_id: int,
    actor: CurrentUserDep,
    service: ServiceDep,
    request: Request,
    body: TeacherAccountUpdate,
) -> dict:
    rid = getattr(request.state, "request_id", None)
    return success(service.update(actor, user_id, body, rid), rid)


@router.post("/accounts/{user_id}/password-reset", status_code=204)
@router.post("/teacher-accounts/{user_id}/password-reset", status_code=204)
def reset_password(
    user_id: int, actor: CurrentUserDep, service: ServiceDep, request: Request, body: PasswordReset
) -> Response:
    service.reset_password(actor, user_id, body, getattr(request.state, "request_id", None))
    return Response(status_code=204)


@router.post("/me/password-change", status_code=204)
def change_password(
    actor: CurrentUserDep, service: ServiceDep, request: Request, body: PasswordChange
) -> Response:
    service.change_password(actor, body, getattr(request.state, "request_id", None))
    return Response(status_code=204)
