"""查课任务与排班模块 ORM 模型（技术方案 9.2、11、13、15、13.3）。

覆盖"任务与排班"域的九张表（技术方案 9.2 表清单）：

- inspection_task            查课任务：task_key 唯一、目标引用、课程/班级/教室快照、
                             名单版本指针、应到人数（初始快照 + 当前值）、取消信息与乐观锁；
- task_roster_version        名单版本：每次执行前修订生成新版本，保留初始及历史快照；
- task_roster_member         名单成员：随版本冻结学生学号/姓名/班级/年级快照；
- submission_deadline_day    某日截止时间当前值：首次为该日建任务时按默认时刻生成，带版本指针；
- submission_deadline_version 截止时间历史版本：改期追加版本、记录人与原因，不改写历史事实；
- inspection_assignment      当前受派关系：一任务一受派人（task_id 唯一），记录分配方式与乐观锁；
- task_deadline_assessment   截止时考核快照（技术方案 13.3）：截止时点回看的既成事实，非当前状态；
- assignment_change_request  调班申请：志愿者本人发起、管理人员处理；
- volunteer_day_lock         志愿者某日锁锚点（技术方案 15）：为并发排班提供稳定可锁记录。

约定（技术方案 8.1、9、identity/academic 模块一致）：
- 枚举以稳定字符串值存储并加 CHECK，不映射 MySQL 原生 ENUM；
- 学期内查课日期用 DATE（本地日历日期），截止时刻统一转 UTC 存 DATETIME(3)；
- 可修改记录带 created_at/updated_at（TimestampMixin）；版本/快照/锁表按需精简；
- 任务、名单、受派、考核随任务级联；对账号/学期/学生等主数据用 RESTRICT 保留历史完整。
"""

from __future__ import annotations

import enum
from datetime import date as date_
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
    DATETIME_3,
    Base,
    CreateTimeMixin,
    TimestampMixin,
    pk_column,
)
from app.core.db import MYSQL_TABLE_ARGS


# --------------------------------------------------------------------------- #
# 枚举（字符串值存储）
# --------------------------------------------------------------------------- #
class InspectionType(enum.StrEnum):
    COURSE = "COURSE"  # 课程查课：须有教学班与课程来源（course_schedule 派生）
    MORNING_STUDY = "MORNING_STUDY"  # 早自习：须有目标行政班与时间定义
    EVENING_STUDY = "EVENING_STUDY"  # 晚自习：须有目标行政班与时间定义


class AssignMethod(enum.StrEnum):
    AUTO = "AUTO"  # 自动排班
    MANUAL = "MANUAL"  # 人工改派


class ChangeRequestStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeadlineAssessmentResult(enum.StrEnum):
    """截止时考核快照结果（技术方案 13.3）。非当前状态，一旦结算不被后续业务改写。"""

    VALID_SUBMISSION = "VALID_SUBMISSION"  # 截止时存在按时有效提交
    OVERDUE_UNEXECUTED = "OVERDUE_UNEXECUTED"  # 截止时无有效提交且未取消 → 逾期未执行
    CANCELED = "CANCELED"  # 截止时任务已取消 → 不纳入未完成


class SubmissionResult(enum.StrEnum):
    """志愿者提交结论（技术方案 12）。NORMAL 时异常项必须为零，ABNORMAL 时至少一项。"""

    NORMAL = "NORMAL"  # 全部正常：无异常明细
    ABNORMAL = "ABNORMAL"  # 有异常：至少一条 LEAVE/LATE/ABSENT 明细


class ReviewStatus(enum.StrEnum):
    """提交审核状态（技术方案 12、9.3）。被驳回不覆盖，重新提交生成下一 attempt。"""

    PENDING = "PENDING"  # 待审核
    APPROVED = "APPROVED"  # 审核通过：据以生成考勤
    REJECTED = "REJECTED"  # 审核驳回：保留原事实与照片


# 异常明细仅限三种异常类型（技术方案 12：LEAVE/LATE/ABSENT，NORMAL 不落明细）。
_ABNORMAL_TYPES = "('LEAVE','LATE','ABSENT')"

_INSPECTION_TYPES = "('COURSE','MORNING_STUDY','EVENING_STUDY')"
_ASSIGN_METHODS = "('AUTO','MANUAL')"
_CHANGE_STATUSES = "('PENDING','APPROVED','REJECTED')"
_ASSESSMENT_RESULTS = "('VALID_SUBMISSION','OVERDUE_UNEXECUTED','CANCELED')"
_SUBMISSION_RESULTS = "('NORMAL','ABNORMAL')"
_REVIEW_STATUSES = "('PENDING','APPROVED','REJECTED')"


# --------------------------------------------------------------------------- #
# 查课任务
# --------------------------------------------------------------------------- #
class InspectionTask(TimestampMixin, Base):
    """查课任务。

    task_key = 学期 + 实际日期 + 类型 + 完整节次范围 + 目标标识 的稳定串，唯一约束实现
    幂等生成（技术方案 11.1、15）：重复生成命中既有 task_key 返回既有/跳过而非报错。

    课程 / 班级 / 教室与应到人数在生成时冻结为快照（技术方案 10）：历史统计按快照分组，
    不随当前学生转班、课表调整漂移。roster_version 指向当前生效名单版本号；expected_count
    保留初始快照与可人工调整的当前值（人数调整不隐式增删名单，见 §14 约束在 service 校验）。
    """

    __tablename__ = "inspection_task"
    __table_args__ = (
        CheckConstraint(
            f"inspection_type IN {_INSPECTION_TYPES}",
            name="ck_inspection_task_type",
        ),
        CheckConstraint(
            "end_period >= start_period",
            name="ck_inspection_task_period_range",
        ),
        CheckConstraint(
            "expected_count_current >= 0",
            name="ck_inspection_task_expected_current",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_key: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    inspection_date: Mapped[date_] = mapped_column(DATE_COL, nullable=False, index=True)
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)
    inspection_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # 起止节次（大节）。真实起止时刻由节次定义派生，冲突判断在 service 用快照时间区间。
    start_period: Mapped[int] = mapped_column(Integer, nullable=False)
    end_period: Mapped[int] = mapped_column(Integer, nullable=False)

    # 目标引用：课程任务用 course_schedule_id/teaching_class_id；
    # 早晚自习用 administrative_class_id。
    course_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_schedule.id", ondelete="RESTRICT")
    )
    teaching_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="RESTRICT")
    )
    administrative_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("administrative_class.id", ondelete="RESTRICT")
    )

    # 生成时冻结的课程 / 班级 / 教室快照（技术方案 10：历史不随主数据漂移）。
    course_name_snapshot: Mapped[str | None] = mapped_column(String(128))
    class_name_snapshot: Mapped[str | None] = mapped_column(String(128))
    classroom_snapshot: Mapped[str | None] = mapped_column(String(128))
    require_photo_snapshot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    # 应到人数：初始快照 + 可人工调整的当前值（技术方案 14）。
    expected_count_snapshot: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    expected_count_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    roster_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    # 取消信息（技术方案 9.2：canceled_at/by/reason）。有取消标记 → 状态已取消。
    canceled_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    canceled_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(512))

    # 乐观锁：改派 / 取消 / 提交 / 结算共用（技术方案 15、13.3）。
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    roster_versions: Mapped[list[TaskRosterVersion]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )


# --------------------------------------------------------------------------- #
# 名单版本与成员快照
# --------------------------------------------------------------------------- #
class TaskRosterVersion(TimestampMixin, Base):
    """任务名单版本。初始为版本 1；执行前更正生成新版本（技术方案 10）。"""

    __tablename__ = "task_roster_version"
    __table_args__ = (
        UniqueConstraint("task_id", "version_no", name="uq_task_roster_version_task_no"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )

    task: Mapped[InspectionTask] = relationship(back_populates="roster_versions")


class TaskRosterMember(Base):
    """名单成员随版本冻结的学生快照（技术方案 9.2、10）。"""

    __tablename__ = "task_roster_member"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "roster_version", "student_id", name="uq_task_roster_member_task_ver_stu"
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    roster_version: Mapped[int] = mapped_column(Integer, nullable=False)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 冻结快照：学号 / 姓名 / 行政班 / 年级（技术方案 10：历史统计按快照分组）。
    student_no: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    class_name_snapshot: Mapped[str | None] = mapped_column(String(128))
    grade_year_snapshot: Mapped[int | None] = mapped_column(Integer)


# --------------------------------------------------------------------------- #
# 提交截止时间：某日当前值 + 历史版本（技术方案 13.1）
# --------------------------------------------------------------------------- #
class SubmissionDeadlineDay(TimestampMixin, Base):
    """某学期某查课日的提交截止时间当前值。

    首次为该日建任务时按当时默认时刻生成一条日记录（技术方案 13.1：不能只在统计时读取
    一个会变动的全局默认值）。deadline_at 为确定的 UTC 时刻；version 指向当前生效版本号，
    每次改期递增并追加 SubmissionDeadlineVersion 历史。
    """

    __tablename__ = "submission_deadline_day"
    __table_args__ = (
        UniqueConstraint(
            "semester_id", "inspection_date", name="uq_submission_deadline_day_sem_date"
        ),
        CheckConstraint("version >= 1", name="ck_submission_deadline_day_version"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    inspection_date: Mapped[date_] = mapped_column(DATE_COL, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(String(512))


class SubmissionDeadlineVersion(CreateTimeMixin, Base):
    """截止时间历史版本。改期追加版本、记录人与原因，不改写既有逾期事实（技术方案 13.1）。"""

    __tablename__ = "submission_deadline_version"
    __table_args__ = (
        UniqueConstraint(
            "deadline_day_id", "version_no", name="uq_submission_deadline_version_day_no"
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    deadline_day_id: Mapped[int] = mapped_column(
        ForeignKey("submission_deadline_day.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(String(512))


# --------------------------------------------------------------------------- #
# 当前受派关系
# --------------------------------------------------------------------------- #
class InspectionAssignment(TimestampMixin, Base):
    """任务当前受派关系。V1.0 一任务一受派人，故 task_id 唯一（技术方案 9.2）。"""

    __tablename__ = "inspection_assignment"
    __table_args__ = (
        CheckConstraint(
            f"assign_method IN {_ASSIGN_METHODS}",
            name="ck_inspection_assignment_method",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    volunteer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assign_method: Mapped[str] = mapped_column(String(16), nullable=False)
    assign_reason: Mapped[str | None] = mapped_column(String(512))
    assigned_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


# --------------------------------------------------------------------------- #
# 截止时考核快照（技术方案 13.3）
# --------------------------------------------------------------------------- #
class TaskDeadlineAssessment(CreateTimeMixin, Base):
    """截止时点回看的既成事实快照，**不是**当前状态。

    - 一任务一条（task_id 唯一）：首次到期结算或补交 / 审核 / 改派 / 取消 / 改期前，
      在任务锁内按**旧**截止版本与历史事件幂等结算（技术方案 13.3、15）；
    - 记录适用截止版本 id、截止时刻快照、截止时受派人快照与结果、结算时间；
    - 普通业务更新不得覆盖；补交进入待审核 / 审核通过进入已完成，均不清除 OVERDUE_UNEXECUTED；
    - 未到期不存在本行（页面/API/周报的 deadlineAssessment 为 null）。
    """

    __tablename__ = "task_deadline_assessment"
    __table_args__ = (
        CheckConstraint(
            f"result IN {_ASSESSMENT_RESULTS}",
            name="ck_task_deadline_assessment_result",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    deadline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("submission_deadline_version.id", ondelete="RESTRICT")
    )
    deadline_at_snapshot: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    assignee_user_id_snapshot: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)


# --------------------------------------------------------------------------- #
# 调班申请
# --------------------------------------------------------------------------- #
class AssignmentChangeRequest(TimestampMixin, Base):
    """志愿者对本人当前受派任务发起的调班申请；管理人员读取与处理（技术方案 9.2）。"""

    __tablename__ = "assignment_change_request"
    __table_args__ = (
        CheckConstraint(
            f"status IN {_CHANGE_STATUSES}",
            name="ck_assignment_change_request_status",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_assignment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ChangeRequestStatus.PENDING.value,
        server_default=text("'PENDING'"),
    )
    processed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    comment: Mapped[str | None] = mapped_column(String(512))


# --------------------------------------------------------------------------- #
# 志愿者某日锁锚点（技术方案 15）
# --------------------------------------------------------------------------- #
class VolunteerDayLock(Base):
    """并发排班的稳定锁锚点。

    仅查 assignment 表重叠记录并加锁不够：无记录时可能没有稳定锁对象。故先安全地
    INSERT IGNORE 建立 (volunteer, date) 记录，再 SELECT ... FOR UPDATE 锁定并检查区间
    冲突，最后更新分配。转移任务时同时锁原、新志愿者日期锚点（按固定顺序防死锁）。
    """

    __tablename__ = "volunteer_day_lock"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    volunteer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
    )
    inspection_date: Mapped[date_] = mapped_column(DATE_COL, primary_key=True)


# --------------------------------------------------------------------------- #
# 查课提交（技术方案 9.3、12、13.3、15）
# --------------------------------------------------------------------------- #
class InspectionSubmission(TimestampMixin, Base):
    """志愿者对本人当前受派任务的查课提交。

    - (task_id, attempt_no) 联合唯一：被驳回提交不覆盖，重新提交生成下一 attempt
      （技术方案 12）；同一任务"只能有一个待审核或一个审核通过提交"由任务行锁 +
      状态检查在 service 保证，attempt 唯一约束不足以保证（技术方案 9.3）。
    - result=NORMAL 时异常明细必须为零，ABNORMAL 时至少一项（service 校验）。
    - roster_version 冻结提交所用名单版本；异常学生必须属于该版本、不可重复。
    - submitted_at 在任务锁内以服务端 UTC 记录（技术方案 13.3：等于截止仍按时）；
      deadline_version_id 记录适用截止版本，late_at_submission 标记迟交，均不被后续
      改期重写；补交不清除既有 OVERDUE_UNEXECUTED 考核快照。
    - 审核通过据以生成考勤；驳回保留原事实与照片。
    """

    __tablename__ = "inspection_submission"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_inspection_submission_task_attempt"),
        CheckConstraint(
            f"result IN {_SUBMISSION_RESULTS}",
            name="ck_inspection_submission_result",
        ),
        CheckConstraint(
            f"review_status IN {_REVIEW_STATUSES}",
            name="ck_inspection_submission_review_status",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    volunteer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    roster_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReviewStatus.PENDING.value,
        server_default=text("'PENDING'"),
        index=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    # 适用截止版本与迟交标记：截止后改期不重写既有事实（技术方案 13.3）。
    deadline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("submission_deadline_version.id", ondelete="RESTRICT")
    )
    late_at_submission: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    note: Mapped[str | None] = mapped_column(String(512))

    # 审核信息（技术方案 9.3：reviewed_by/at/comment）。
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    review_comment: Mapped[str | None] = mapped_column(String(512))

    abnormal_items: Mapped[list[SubmissionAbnormalItem]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin"
    )
    files: Mapped[list[SubmissionFile]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin"
    )


class SubmissionAbnormalItem(Base):
    """提交异常明细：仅记 LEAVE/LATE/ABSENT 三类异常学生（技术方案 12）。

    (submission_id, student_id) 联合唯一保证同一提交内学生不重复录入；NORMAL 不落明细，
    "全部正常"由 result=NORMAL 且无明细表达，与"未提交"清晰区分（技术方案 9.3）。
    学生外键 RESTRICT 保留历史认定完整。
    """

    __tablename__ = "submission_abnormal_item"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "student_id", name="uq_submission_abnormal_item_sub_stu"
        ),
        CheckConstraint(
            f"attendance_type IN {_ABNORMAL_TYPES}",
            name="ck_submission_abnormal_item_type",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_submission.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attendance_type: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(512))

    submission: Mapped[InspectionSubmission] = relationship(back_populates="abnormal_items")


class SubmissionFile(Base):
    """提交与照片文件的关联（技术方案 9.3：submission_id + file_id 联合主键）。

    仅 READY 且上传者、类别、归属相符的文件可关联（校验在 service，见文件模块）。
    文件行 RESTRICT：被业务引用的材料在清理前不得物理消失，清理走状态机而非级联删除。
    """

    __tablename__ = "submission_file"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    submission_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_submission.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("file_object.id", ondelete="RESTRICT"), primary_key=True
    )

    submission: Mapped[InspectionSubmission] = relationship(back_populates="files")


__all__ = [
    "InspectionType",
    "AssignMethod",
    "ChangeRequestStatus",
    "DeadlineAssessmentResult",
    "SubmissionResult",
    "ReviewStatus",
    "InspectionTask",
    "TaskRosterVersion",
    "TaskRosterMember",
    "SubmissionDeadlineDay",
    "SubmissionDeadlineVersion",
    "InspectionAssignment",
    "TaskDeadlineAssessment",
    "AssignmentChangeRequest",
    "VolunteerDayLock",
    "InspectionSubmission",
    "SubmissionAbnormalItem",
    "SubmissionFile",
]
