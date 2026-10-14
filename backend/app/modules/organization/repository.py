"""新配置查询均需显式学院条件，写锚点锁定父学院。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.organization.models import College, ScopedGrant


class CampusRepository:
    def __init__(self, session: Session):
        self.session = session

    def college(self, college_id: int, *, lock: bool = False) -> College | None:
        stmt = select(College).where(College.id == college_id).execution_options(populate_existing=True)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(stmt)

    def grants(
        self, user_id: int, *, college_id: int | None = None, lock=False
    ) -> list[ScopedGrant]:
        stmt = select(ScopedGrant).where(ScopedGrant.user_id == user_id)
        if college_id is not None:
            stmt = stmt.where(ScopedGrant.college_id == college_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return list(self.session.scalars(stmt.execution_options(populate_existing=True)))

    def rows(self, model, college_id: int):
        return list(
            self.session.scalars(
                select(model).where(model.college_id == college_id).order_by(model.id),
            )
        )

    def resource(self, model, college_id: int, resource_id: int):
        return self.session.scalar(
            select(model)
            .where(model.college_id == college_id, model.id == resource_id)
            .execution_options(populate_existing=True),
        )
