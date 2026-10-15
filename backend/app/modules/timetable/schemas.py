"""私人字段可修改，正式来源标识不可通过修改接口伪造。"""

from datetime import date, time
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from app.modules.academic.publication_schemas import PublishedSource
from app.modules.organization.schemas import StrictModel

Week = Annotated[int, Field(ge=1, le=60, strict=True)]
SERVER_ENTRY_FIELDS = frozenset({
    "id", "source_schedule_id", "teaching_class_id", "college_id", "class_name", "exceptions",
})


def reject_server_fields(value):
    if isinstance(value, dict) and SERVER_ENTRY_FIELDS.intersection(value):
        raise ValueError("个人课程不能修改条目标识、正式来源或单次修改列表")
    return value


class EntryValues(StrictModel):
    model_config = ConfigDict(extra="allow", strict=False)

    course_name: str = Field(min_length=1, max_length=128)
    teacher: str | None = Field(default=None, max_length=128)
    classroom: str | None = Field(default=None, max_length=128)
    weekday: int = Field(ge=1, le=7, strict=True)
    week_nos: list[Week] = Field(min_length=1, max_length=60)
    start_time: time
    end_time: time
    note: str = Field(default="", max_length=1000)
    occurrence_dates: list[date] | None = Field(default=None, max_length=420)
    start_period: int | None = Field(default=None, ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)
    color: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def valid_occurrences(self):
        if self.start_time.tzinfo or self.end_time.tzinfo or self.start_time >= self.end_time:
            raise ValueError("请提供同一天有效的本地起止时刻")
        self.week_nos = sorted(set(self.week_nos))
        if self.occurrence_dates is not None:
            self.occurrence_dates = sorted(set(self.occurrence_dates))
        return self


class EntryCreate(EntryValues):
    current_version: int = Field(ge=1, strict=True)
    _server_fields = model_validator(mode="before")(reject_server_fields)


class EntryUpdate(StrictModel):
    model_config = ConfigDict(extra="allow", strict=False)
    _server_fields = model_validator(mode="before")(reject_server_fields)

    current_version: int = Field(ge=1, strict=True)
    course_name: str | None = Field(default=None, min_length=1, max_length=128)
    teacher: str | None = Field(default=None, max_length=128)
    classroom: str | None = Field(default=None, max_length=128)
    weekday: int | None = Field(default=None, ge=1, le=7, strict=True)
    week_nos: list[Week] | None = Field(default=None, min_length=1, max_length=60)
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = Field(default=None, max_length=1000)
    occurrence_dates: list[date] | None = Field(default=None, max_length=420)
    start_period: int | None = Field(default=None, ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)
    color: str | None = Field(default=None, max_length=64)


class EntryDelete(StrictModel):
    current_version: int = Field(ge=1, strict=True)


class OccurrenceEdit(EntryDelete):
    cancelled: bool = False
    target_date: date | None = None
    course_name: str | None = Field(default=None, min_length=1, max_length=128)
    teacher: str | None = Field(default=None, max_length=128)
    classroom: str | None = Field(default=None, max_length=128)
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = Field(default=None, max_length=1000)


class OccurrenceException(StrictModel):
    date: date
    target_date: date
    cancelled: bool
    values: EntryValues


class PersonalEntry(EntryValues):
    model_config = ConfigDict(extra="allow", strict=False)

    exceptions: list[OccurrenceException] = Field(default_factory=list)
    id: str
    source_schedule_id: str | None
    teaching_class_id: str | None
    college_id: str | None
    class_name: str | None
    start_period: int | None = None
    end_period: int | None = None
    color: str | None = None


class PersonalTimetableResult(StrictModel):
    semester_id: str
    status: Literal["INITIALIZED", "NOT_INITIALIZED", "NOT_PUBLISHED"]
    source_revision: str | None
    sources: list[PublishedSource]
    entries: list[PersonalEntry]
    current_version: int | None


class TimetableEnvelope(StrictModel):
    data: PersonalTimetableResult
    requestId: str | None


class PersonalSemester(StrictModel):
    id: str
    name: str
    status: str
    initialized: bool
    current_version: int | None


class PersonalSemestersEnvelope(StrictModel):
    data: list[PersonalSemester]
    requestId: str | None
