from datetime import date, time
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from app.modules.academic import schemas as legacy
from app.modules.identity.role_scope import business_today
from app.modules.organization.schemas import StrictModel

PositiveId = Annotated[int, Field(gt=0, le=2**63 - 1)]


class QualificationUpsert(StrictModel):
    semester_id: PositiveId
    student_id: PositiveId
    student_lock_version: int = Field(ge=0)
    enabled: bool
    reason: str | None = Field(default=None, max_length=512)


class SemesterReset(legacy.SemesterResetDataRequest):
    model_config = StrictModel.model_config
    source_revision: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")


class StudentCreate(legacy.StudentCreateRequest):
    model_config = StrictModel.model_config
    administrative_class_id: PositiveId
    enrolled_since: date = Field(default_factory=business_today)


class TeachingCreate(legacy.TeachingClassCreateRequest):
    model_config = StrictModel.model_config
    semester_id: PositiveId
    course_id: PositiveId
    course_type_id: PositiveId | None = None


class ScheduleCreate(legacy.CourseScheduleCreateRequest):
    model_config = StrictModel.model_config
    teaching_class_id: PositiveId
    start_period: int = Field(ge=1, le=60)
    end_period: int = Field(ge=1, le=60)


class CourseCreate(legacy.CourseCreateRequest):
    model_config = StrictModel.model_config


class ElectiveItem(legacy.ElectiveTeachingClassItem):
    model_config = StrictModel.model_config
    start_period: int = Field(ge=1, le=60)
    end_period: int = Field(ge=1, le=60)
    student_nos: list[str] = Field(default_factory=list, max_length=5000)


class ElectiveBatch(StrictModel):
    semester_id: PositiveId
    course_name: str = Field(min_length=1, max_length=128)
    course_code: str | None = Field(default=None, max_length=64)
    teaching_classes: list[ElectiveItem] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=512)


class SelfStudyBatchCreate(StrictModel):
    semester_id: PositiveId
    study_type: str = Field(pattern=r"^(?:EARLY|LATE)$")
    course_type_id: PositiveId | None = None
    class_ids: list[PositiveId] = Field(min_length=1, max_length=200)
    weeks: list[int] = Field(min_length=1, max_length=60)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    start_time: time | None = None
    end_time: time | None = None
    # 旧调用兼容；新界面仅提交实际时刻，不能同时混用两种时间来源。
    start_period: int | None = Field(default=None, ge=1, le=60)
    end_period: int | None = Field(default=None, ge=1, le=60)
    classrooms: dict[str, str] = Field(default_factory=dict)
    default_classroom: str | None = Field(default=None, max_length=128)
    teacher_name: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def timing(self):
        clocks = self.start_time is not None or self.end_time is not None
        periods = self.start_period is not None or self.end_period is not None
        if clocks == periods:
            raise ValueError("请填写独立起止时间，不要混用教学节次")
        if clocks:
            if self.start_time is None or self.end_time is None or self.start_time >= self.end_time:
                raise ValueError("开始时间须早于结束时间，跨日时段须拆开")
            if any(t.tzinfo or t.second or t.microsecond for t in (self.start_time, self.end_time)):
                raise ValueError("自习时刻须为本地分钟精度")
        elif self.start_period is None or self.end_period is None:
            raise ValueError("教学节次范围无效")
        if any(not 1 <= d <= 7 for d in self.weekdays):
            raise ValueError("星期须为1至7")
        return self


CREATE_SCHEMAS = {
    "students": StudentCreate,
    "courses": CourseCreate,
    "teaching_classes": TeachingCreate,
    "schedules": ScheduleCreate,
}


class StudentUpdate(legacy.StudentUpdateRequest):
    model_config = StrictModel.model_config
    lock_version: int = Field(ge=0)


class CourseUpdate(legacy.CourseUpdateRequest):
    model_config = StrictModel.model_config
    ownership_version: int = Field(ge=1)


class TeachingUpdate(legacy.TeachingClassUpdateRequest):
    model_config = StrictModel.model_config
    ownership_version: int = Field(ge=1)


class ScheduleUpdate(legacy.CourseScheduleUpdateRequest):
    model_config = StrictModel.model_config
    ownership_version: int = Field(ge=1)
    start_period: int | None = Field(default=None, ge=1, le=60)
    end_period: int | None = Field(default=None, ge=1, le=60)


CreateBody = StudentCreate | CourseCreate | TeachingCreate | ScheduleCreate
UpdateBody = StudentUpdate | CourseUpdate | TeachingUpdate | ScheduleUpdate
UPDATE_SCHEMAS = {
    "students": StudentUpdate,
    "courses": CourseUpdate,
    "teaching_classes": TeachingUpdate,
    "schedules": ScheduleUpdate,
}


class DeleteMany(StrictModel):
    ids: list[PositiveId] = Field(min_length=1, max_length=500)
    versions: dict[str, Annotated[int, Field(ge=0, strict=True)]]
    reason: str | None = Field(default=None, max_length=512)

    @field_validator("versions")
    @classmethod
    def version_ids(cls, values):
        if any(
            not key.isascii()
            or not key.isdecimal()
            or str(int(key)) != key
            or not 0 < int(key) < 2**63
            for key in values
        ):
            raise ValueError("版本字典须使用规范正 BIGINT 字符串标识")
        return values
