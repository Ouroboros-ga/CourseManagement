"""基础数据模块的请求/响应模型（Pydantic 2.x）。

约定（技术方案 8.1、与 identity 模块一致）：
- 请求体字段沿用 snake_case（仅 requestId/lockVersion 等少数外壳字段用 camelCase）；
- 响应体绝不直接返回 ORM 实体：BIGINT 主键统一以字符串对外（IdStr 前置转换），
  日期/时刻由 Pydantic 序列化为 ISO 字符串；
- 只读响应模型可用 `from_attributes=True` 直接由 ORM 构建（标量字段），
  嵌套集合（节次、周次、名单）由服务显式装配。

写操作不引入 lock_version：基础数据为低频后台维护，服务在同一事务内对目标行
SELECT ... FOR UPDATE 串行化并发写（见 service），并追加审计，足够保证一致性。
"""

from __future__ import annotations

from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _id_to_str(value: object) -> str:
    return str(value)


# BIGINT 主键/外键对外以字符串暴露；构造时接受 int 或 str，统一转成 str。
IdStr = Annotated[str, BeforeValidator(_id_to_str)]
OptIdStr = Annotated[str | None, BeforeValidator(lambda v: None if v is None else str(v))]

# 通用启停状态（行政班/学生/课程/教学班/课表）取值集合。
_RECORD_STATUS = {"ACTIVE", "DISABLED"}


# --------------------------------------------------------------------------- #
# 学期 Semester
# --------------------------------------------------------------------------- #
class SemesterCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    start_date: date
    end_date: date
    first_monday: date
    total_weeks: int = Field(default=20, ge=1, le=60)
    reason: str | None = Field(default=None, max_length=512)


class SemesterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    first_monday: date | None = None
    total_weeks: int | None = Field(default=None, ge=1, le=60)
    status: str | None = Field(default=None, max_length=16)  # ACTIVE / ARCHIVED
    reason: str | None = Field(default=None, max_length=512)


class SemesterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    code: str
    name: str
    start_date: date
    end_date: date
    first_monday: date
    total_weeks: int
    status: str
    created_at: object
    updated_at: object


# --------------------------------------------------------------------------- #
# 节次定义 PeriodDefinition
# --------------------------------------------------------------------------- #
class PeriodDefinitionUpsertRequest(BaseModel):
    # 节次号由 URL 路径权威提供（路由以路径覆盖本字段），故请求体可省略。
    period_no: int | None = Field(default=None, ge=1, le=20)
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=512)


class PeriodDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    semester_id: IdStr
    period_no: int
    start_time: time | None
    end_time: time | None


# --------------------------------------------------------------------------- #
# 校历覆盖 CalendarOverride
# --------------------------------------------------------------------------- #
class CalendarOverrideCreateRequest(BaseModel):
    date: date
    override_type: str = Field(min_length=1, max_length=16)  # STOP / MAKEUP
    source_teaching_weekday: int | None = Field(default=None, ge=1, le=7)
    reason: str | None = Field(default=None, max_length=255)


class CalendarOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    semester_id: IdStr
    date: date
    override_type: str
    source_teaching_weekday: int | None
    reason: str | None


# --------------------------------------------------------------------------- #
# 行政班 AdministrativeClass
# --------------------------------------------------------------------------- #
class AdministrativeClassCreateRequest(BaseModel):
    class_code: str = Field(min_length=1, max_length=64)
    class_name: str = Field(min_length=1, max_length=128)
    grade_year: int | None = Field(default=None, ge=1900, le=2999)
    major_name: str | None = Field(default=None, max_length=128)
    college: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=512)


class AdministrativeClassUpdateRequest(BaseModel):
    class_name: str | None = Field(default=None, min_length=1, max_length=128)
    grade_year: int | None = Field(default=None, ge=1900, le=2999)
    major_name: str | None = Field(default=None, max_length=128)
    college: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=16)
    reason: str | None = Field(default=None, max_length=512)


class AdministrativeClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    class_code: str
    class_name: str
    grade_year: int | None
    major_name: str | None
    college: str | None
    status: str


# --------------------------------------------------------------------------- #
# 学生 Student
# --------------------------------------------------------------------------- #
class StudentCreateRequest(BaseModel):
    student_no: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    administrative_class_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=512)


class StudentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    administrative_class_id: int | None = Field(default=None, ge=1)
    # 传 null 显式清除归属；不传表示不变。用哨兵区分。
    status: str | None = Field(default=None, max_length=16)
    reason: str | None = Field(default=None, max_length=512)


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    student_no: str
    name: str
    administrative_class_id: OptIdStr
    status: str


# --------------------------------------------------------------------------- #
# 课程 Course
# --------------------------------------------------------------------------- #
class CourseCreateRequest(BaseModel):
    course_code: str = Field(min_length=1, max_length=64)
    course_name: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=512)


class CourseUpdateRequest(BaseModel):
    course_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, max_length=16)
    reason: str | None = Field(default=None, max_length=512)


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    course_code: str
    course_name: str
    status: str


# --------------------------------------------------------------------------- #
# 教学班 TeachingClass（结构；名单见 roster 端点）
# --------------------------------------------------------------------------- #
class TeachingClassCreateRequest(BaseModel):
    semester_id: int = Field(ge=1)
    course_id: int = Field(ge=1)
    class_code: str | None = Field(default=None, max_length=64)
    class_name: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=512)


class TeachingClassUpdateRequest(BaseModel):
    class_code: str | None = Field(default=None, max_length=64)
    class_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, max_length=16)
    reason: str | None = Field(default=None, max_length=512)


class TeachingClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    semester_id: IdStr
    course_id: IdStr
    class_code: str | None
    class_name: str
    status: str


# 名单：整体替换 / 增量增删。student_ids 为数值主键（请求内部用 int，响应转 str）。
class RosterReplaceRequest(BaseModel):
    student_ids: list[int] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=512)


class RosterStudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    student_no: str
    name: str


# --------------------------------------------------------------------------- #
# 课表 CourseSchedule
# --------------------------------------------------------------------------- #
class CourseScheduleCreateRequest(BaseModel):
    teaching_class_id: int = Field(ge=1)
    weekday: int = Field(ge=1, le=7)
    start_period: int = Field(ge=1, le=20)
    end_period: int = Field(ge=1, le=20)
    classroom: str | None = Field(default=None, max_length=128)
    weeks: list[int] = Field(default_factory=list, description="生效教学周次集合(1..total_weeks)")
    reason: str | None = Field(default=None, max_length=512)


class CourseScheduleUpdateRequest(BaseModel):
    weekday: int | None = Field(default=None, ge=1, le=7)
    start_period: int | None = Field(default=None, ge=1, le=20)
    end_period: int | None = Field(default=None, ge=1, le=20)
    classroom: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=16)
    weeks: list[int] | None = Field(default=None, description="提供则整体替换生效周次")
    reason: str | None = Field(default=None, max_length=512)


class CourseScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    semester_id: IdStr
    teaching_class_id: IdStr
    weekday: int
    start_period: int
    end_period: int
    classroom: str | None
    status: str
    weeks: list[int] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 志愿者学期资格 VolunteerQualification
# --------------------------------------------------------------------------- #
class VolunteerQualificationUpsertRequest(BaseModel):
    semester_id: int = Field(ge=1)
    student_id: int = Field(ge=1)
    enabled: bool = True
    reason: str | None = Field(default=None, max_length=512)


class VolunteerQualificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    semester_id: IdStr
    student_id: IdStr
    enabled: bool
    created_by: OptIdStr


# --------------------------------------------------------------------------- #
# 通用分页响应外壳
# --------------------------------------------------------------------------- #
class PageResponse(BaseModel):
    items: list[object]
    page: int
    page_size: int
    total: int


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
