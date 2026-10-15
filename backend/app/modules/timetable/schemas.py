"""私人字段可修改，正式来源标识不可通过修改接口伪造。"""

from datetime import date, time
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.academic.publication_schemas import PublishedSource
from app.modules.organization.schemas import StrictModel

Week = Annotated[int, Field(ge=1, le=60, strict=True)]


class EntryValues(StrictModel):
    course_name: str = Field(min_length=1, max_length=128)
    teacher: str | None = Field(default=None, max_length=128)
    classroom: str | None = Field(default=None, max_length=128)
    weekday: int = Field(ge=1, le=7, strict=True)
    week_nos: list[Week] = Field(min_length=1, max_length=60)
    start_time: time
    end_time: time
    note: str = Field(default="", max_length=1000)
    occurrence_dates: list[date] | None = Field(default=None, max_length=420)

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


class EntryUpdate(StrictModel):
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
    exceptions: list[OccurrenceException] = Field(default_factory=list)
    id: str
    source_schedule_id: str | None
    teaching_class_id: str | None
    college_id: str | None
    class_name: str | None
    start_period: int | None
    end_period: int | None


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
