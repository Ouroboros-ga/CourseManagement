"""A persistent organization can select independent immutable rules per semester."""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class GroupSemesterPreparation(TimestampMixin, Base):
    __tablename__ = "group_semester_preparation"
    __table_args__ = (
        UniqueConstraint("group_id", "semester_id", name="uq_group_semester_preparation"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    group_id: Mapped[int] = mapped_column(ForeignKey("volunteer_group.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    source_semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    config_id: Mapped[int] = mapped_column(
        ForeignKey("group_config_version.id", ondelete="RESTRICT")
    )
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


def semester_group_config(db, group, sid):
    from sqlalchemy import select

    from app.modules.volunteer.models import GroupConfigVersion

    prepared = db.scalar(
        select(GroupSemesterPreparation).where(
            GroupSemesterPreparation.college_id == group.college_id,
            GroupSemesterPreparation.group_id == group.id,
            GroupSemesterPreparation.semester_id == sid,
        )
    )
    if prepared:
        return db.get(GroupConfigVersion, prepared.config_id)
    return db.scalar(
        select(GroupConfigVersion).where(
            GroupConfigVersion.group_id == group.id,
            GroupConfigVersion.college_id == group.college_id,
            GroupConfigVersion.version == group.config_version,
        )
    )
