"""发布后不可改写的院级作息与校历；任务自行保存命中的时间快照。"""

from datetime import date

from sqlalchemy import JSON, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATE_COL, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class CollegeTimeVersion(TimestampMixin, Base):
    __tablename__ = "college_time_version"
    __table_args__ = (
        UniqueConstraint("college_id", "semester_id", "version", name="uq_college_time_version"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    configuration: Mapped[dict] = mapped_column(JSON)
    published_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
