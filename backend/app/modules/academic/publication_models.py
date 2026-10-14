"""不可变正式发布来源；不是个人可编辑课表，也不保存消息已读状态。"""

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, CreateTimeMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AcademicPublication(CreateTimeMixin, Base):
    __tablename__ = "academic_publication"
    __table_args__ = (
        UniqueConstraint(
            "college_id", "semester_id", "version", name="uq_academic_publication_version"
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSON)
    published_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))


class PublishedSchedule(Base):
    __tablename__ = "published_schedule"
    __table_args__ = (
        UniqueConstraint(
            "publication_id",
            "source_schedule_id",
            "segment_no",
            name="uq_published_schedule_source",
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("academic_publication.id", ondelete="RESTRICT"), index=True
    )
    # 来源是快照标识，无 FK：源课程删除不能级联删除正式发布历史。
    source_schedule_id: Mapped[str] = mapped_column(String(20))
    segment_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    snapshot: Mapped[dict] = mapped_column(JSON)


class PublishedScheduleStudent(Base):
    __tablename__ = "published_schedule_student"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    published_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("published_schedule.id", ondelete="RESTRICT"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    occurrence_dates: Mapped[list[str]] = mapped_column(JSON)


class PublicationAudience(Base):
    """每次发布的本人内容指纹；变化时展示通知，名单删除也保留旧受众。"""

    __tablename__ = "publication_audience"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("academic_publication.id", ondelete="RESTRICT"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    changed: Mapped[bool] = mapped_column(default=True)
