"""基础数据模块 ORM 模型（技术方案 9.1、9.2）。

学期 / 节次定义 / 行政班 / 学生 / 课程 / 教学班 / 名单 / 课表 / 校历覆盖 /
志愿者资格。行政班与学生两表在身份阶段（初始迁移）已建最小字段，本模块在
其现有列基础上扩展（学院等），不重复定义；新增表在此声明。

约定（技术方案 8.1、9.1）：
- 枚举以稳定字符串值存储，必要处加 CHECK 约束，不映射 MySQL 原生 ENUM；
- 学期起止、首周一、校历日期用 DATE（本地日历日期）；节次起止用 TIME；
- 可修改记录带 created_at/updated_at（TimestampMixin）；关联表仅联合主键；
- 年级由行政班派生、历史年级由任务名单快照保存，学生表不冗余维护年级。
"""

from __future__ import annotations

import enum
from datetime import date as date_
from datetime import time as time_

from sqlalchemy import (
    TIME,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import (
    DATE_COL,
    Base,
    TimestampMixin,
    pk_column,
)
from app.core.db import MYSQL_TABLE_ARGS


# --------------------------------------------------------------------------- #
# 枚举（字符串值存储）
# --------------------------------------------------------------------------- #
class SemesterStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class OverrideType(enum.StrEnum):
    STOP = "STOP"  # 停课日：不生成课程任务
    MAKEUP = "MAKEUP"  # 调休/补课日：按来源教学日课表执行


# --------------------------------------------------------------------------- #
# 学期与节次
# --------------------------------------------------------------------------- #
class Semester(TimestampMixin, Base):
    """学期。code 唯一；first_monday 用于周次到日期的换算基准。"""

    __tablename__ = "semester"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_semester_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date_] = mapped_column(DATE_COL, nullable=False)
    end_date: Mapped[date_] = mapped_column(DATE_COL, nullable=False)
    first_monday: Mapped[date_] = mapped_column(DATE_COL, nullable=False)
    total_weeks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default=text("20")
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SemesterStatus.ACTIVE.value,
        server_default=text("'ACTIVE'"),
    )

    period_definitions: Mapped[list[PeriodDefinition]] = relationship(
        back_populates="semester", cascade="all, delete-orphan", lazy="selectin"
    )


class PeriodDefinition(TimestampMixin, Base):
    """学期节次定义：第几节及起止时刻。同一学期内节次号唯一。"""

    __tablename__ = "period_definition"
    __table_args__ = (
        UniqueConstraint("semester_id", "period_no", name="uq_period_definition_semester_no"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time_ | None] = mapped_column(TIME)
    end_time: Mapped[time_ | None] = mapped_column(TIME)

    semester: Mapped[Semester] = relationship(back_populates="period_definitions")


# --------------------------------------------------------------------------- #
# 校历覆盖（技术方案 9.1：处理停课、调休与补课）
# --------------------------------------------------------------------------- #
class CalendarOverride(TimestampMixin, Base):
    """校历覆盖：把某个日历日期标注为停课或调休补课，可指向被替代的教学日星期。"""

    __tablename__ = "calendar_override"
    __table_args__ = (
        CheckConstraint(
            "override_type IN ('STOP','MAKEUP')",
            name="ck_calendar_override_type",
        ),
        UniqueConstraint("semester_id", "date", name="uq_calendar_override_sem_date"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    date: Mapped[date_] = mapped_column(DATE_COL, nullable=False)
    override_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_teaching_weekday: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(255))


# --------------------------------------------------------------------------- #
# 行政班与学生（在初始迁移的最小字段上扩展）
# --------------------------------------------------------------------------- #
class AdministrativeClass(TimestampMixin, Base):
    """行政班。年级由 grade_year 承载，学生年级随班级派生避免漂移。"""

    __tablename__ = "administrative_class"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    class_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    class_name: Mapped[str] = mapped_column(String(128), nullable=False)
    grade_year: Mapped[int | None] = mapped_column(Integer)
    major_name: Mapped[str | None] = mapped_column(String(128))
    college: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )

    students: Mapped[list[Student]] = relationship(back_populates="administrative_class")


class Student(TimestampMixin, Base):
    """学生基础记录。student_no 唯一、绑定核验依赖此表。"""

    __tablename__ = "student"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    student_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    administrative_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("administrative_class.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )

    administrative_class: Mapped[AdministrativeClass | None] = relationship(
        back_populates="students"
    )


# --------------------------------------------------------------------------- #
# 课程与教学班
# --------------------------------------------------------------------------- #
class Course(TimestampMixin, Base):
    """课程目录。course_code 唯一，供教学班引用。"""

    __tablename__ = "course"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    course_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    course_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )


class TeachingClass(TimestampMixin, Base):
    """教学班：某学期某课程的一个开课班，可面向行政班或选课名单。"""

    __tablename__ = "teaching_class"
    __table_args__ = (
        UniqueConstraint("semester_id", "course_id", "class_code", name="uq_teaching_class_key"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("course.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    class_code: Mapped[str | None] = mapped_column(String(64))
    class_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )

    students: Mapped[list[Student]] = relationship(
        secondary="teaching_class_student", lazy="selectin"
    )


class TeachingClassStudent(Base):
    """教学班—学生名单关联，联合主键。"""

    __tablename__ = "teaching_class_student"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    teaching_class_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), primary_key=True
    )


# --------------------------------------------------------------------------- #
# 课表
# --------------------------------------------------------------------------- #
class CourseSchedule(TimestampMixin, Base):
    """课表条目：教学班在一周中的固定上课时段（星期 + 起止大节 + 地点）。"""

    __tablename__ = "course_schedule"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 1 AND 7", name="ck_course_schedule_weekday"),
        CheckConstraint("end_period >= start_period", name="ck_course_schedule_period_range"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    teaching_class_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_period: Mapped[int] = mapped_column(Integer, nullable=False)
    end_period: Mapped[int] = mapped_column(Integer, nullable=False)
    classroom: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )

    weeks: Mapped[list[CourseScheduleWeek]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan", lazy="selectin"
    )


class CourseScheduleWeek(Base):
    """课表生效周次展开：把周集合（含单双周）物化为逐周记录，供任务生成查询。"""

    __tablename__ = "course_schedule_week"
    __table_args__ = (
        UniqueConstraint("schedule_id", "week_no", name="uq_schedule_week"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("course_schedule.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)

    schedule: Mapped[CourseSchedule] = relationship(back_populates="weeks")


# --------------------------------------------------------------------------- #
# 志愿者学期资格
# --------------------------------------------------------------------------- #
class VolunteerQualification(TimestampMixin, Base):
    """志愿者学期资格：按 (学期, 学生) 唯一，enabled 启停（PERMISSIONS.md 1.5）。

    未绑定账号的学生也可导入资格；首次获得有效资格时由服务在同一事务内自动
    维护 VOLUNTEER 角色身份（不手工授予）。停用立即禁止提交但保留历史读取。
    """

    __tablename__ = "volunteer_qualification"
    __table_args__ = (
        UniqueConstraint("semester_id", "student_id", name="uq_volunteer_qualification_sem_stu"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("1"), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
