"""扩展阶段允许未知归属；未知并非全校范围，强制隔离前须清零或隔离处理。"""

from sqlalchemy import ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column


class CollegeOwned:
    college_id: Mapped[int | None] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    ownership_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
