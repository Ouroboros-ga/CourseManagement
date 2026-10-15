"""Snapshot contract used by the existing WeChat client."""

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.organization.schemas import StrictModel


class BackupItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    course_id: str = Field(min_length=1, max_length=128)
    scheme_id: str = Field(min_length=1, max_length=128)
    course_name: str = Field(min_length=1, max_length=128)
    course_code: str = Field(default="", max_length=128)
    color_index: int | None = Field(default=None, ge=0, le=255)
    is_custom: bool = False
    teacher_name: str = Field(default="", max_length=128)
    classroom: str = Field(default="", max_length=128)
    weekday: int = Field(ge=1, le=7, strict=True)
    start_period: int = Field(ge=1, le=30, strict=True)
    end_period: int = Field(ge=1, le=30, strict=True)
    weeks: list[Annotated[int, Field(ge=1, le=60, strict=True)]] = Field(
        min_length=1, max_length=60
    )
    note: str = Field(default="", max_length=1000)

    @field_validator("course_id", "scheme_id", mode="before")
    @classmethod
    def display_id(cls, value):
        if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**53:
            return str(value)
        return value

    @model_validator(mode="after")
    def ordered_periods(self):
        if self.start_period > self.end_period:
            raise ValueError("开始节次不能晚于结束节次")
        return self


class BackupWrite(StrictModel):
    semester_id: Annotated[int, Field(gt=0, le=2**63 - 1)]
    schedule_data: list[BackupItem] = Field(max_length=500)

    @model_validator(mode="before")
    @classmethod
    def bounded_snapshot(cls, value):
        if isinstance(value, dict):
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
                raise ValueError("备份内容不能超过1 MiB")
            items = value.get("schedule_data", [])
            if isinstance(items, list):
                keys = [
                    (str(x.get("course_id")), str(x.get("scheme_id")))
                    for x in items
                    if isinstance(x, dict)
                ]
                if len(keys) != len(set(keys)):
                    raise ValueError("备份包含重复课程方案")
        return value


class BackupResult(StrictModel):
    semester_id: str
    has_backup: bool
    backup_version: int | None
    updated_at: str | None
    semester: dict
    schedule_data: list[dict]


class BackupEnvelope(StrictModel):
    data: BackupResult
    requestId: str | None


class ClassTimetableResult(StrictModel):
    semester: dict
    class_name: str
    source_revision: str
    items: list[dict]


class ClassTimetableEnvelope(StrictModel):
    data: ClassTimetableResult
    requestId: str | None
