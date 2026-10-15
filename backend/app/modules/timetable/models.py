"""按学生和学期独立的云端个人副本，初始化状态与空内容分离。"""

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class PersonalTimetable(TimestampMixin, Base):
    __tablename__ = "personal_timetable"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "semester_id", name="uq_personal_timetable_student_semester"
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    source_revision: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSON)
    entries: Mapped[list] = mapped_column(JSON)
    deleted_entries: Mapped[list] = mapped_column(JSON, default=list, server_default=text("('[]')"))
    occurrence_exceptions: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("('{}')"))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
