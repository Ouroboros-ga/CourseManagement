"""身份管理目标的显式 SQL 范围；不依赖 Session 隐式过滤。"""

from sqlalchemy import or_, select

from app.modules.identity.models import UserAccount


def management_users(db, actor_id, action, *, college_id=None):
    from app.modules.identity.query_scope import predicates
    from app.modules.identity.role_scope import business_today, resolve_scope

    statement = select(UserAccount)
    if college_id is not None:
        from app.modules.identity.resource_scope import resolve_scope as resource_scope
        from app.modules.identity.service import CurrentUser

        resource_scope(db, CurrentUser(actor_id, None, "", "ACTIVE", [], []), college_id, action)
        colleges = {college_id}
    else:
        scope = resolve_scope(db, actor_id, action)
        if scope.kind == "SCHOOL":
            return statement
        colleges = set(scope.authorized_college_ids)
        if scope.college_id is not None:
            colleges.add(scope.college_id)
    return (
        statement.where(
            or_(*(predicates(cid, business_today())[UserAccount] for cid in sorted(colleges)))
        )
        if colleges
        else statement.where(False)
    )
