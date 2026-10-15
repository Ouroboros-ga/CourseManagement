"""Confirmed shared identity is separate from each college's teaching-class view."""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AcademicOffering(TimestampMixin, Base):
    __tablename__ = "academic_offering"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    course_name: Mapped[str] = mapped_column(String(128))
    offering_college_id: Mapped[int | None] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT")
    )
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class ImportSourceAssertion(TimestampMixin, Base):
    __tablename__ = "import_source_assertion"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    id: Mapped[int] = pk_column()
    offering_id: Mapped[str] = mapped_column(
        ForeignKey("academic_offering.id", ondelete="RESTRICT")
    )
    teaching_class_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="RESTRICT"), index=True
    )
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    assertion: Mapped[dict] = mapped_column(JSON)
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
