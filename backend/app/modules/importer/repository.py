"""导入批次仓储：仅 flush 不 commit（与 identity/academic 仓储约定一致）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.importer.models import ImportBatch


class ImporterRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, batch: ImportBatch) -> ImportBatch:
        self._session.add(batch)
        self._session.flush()
        return batch

    def get(self, batch_id: int) -> ImportBatch | None:
        return self._session.get(ImportBatch, batch_id)

    def get_for_update(self, batch_id: int) -> ImportBatch | None:
        return self._session.execute(
            select(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
