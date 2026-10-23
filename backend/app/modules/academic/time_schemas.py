from datetime import date, time
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.modules.organization.schemas import StrictModel


class PeriodTime(StrictModel):
    slot_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(default="", max_length=128)
    period_no: int = Field(ge=1, le=60)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def ordered(self):
        if any(
            t.tzinfo is not None or t.second or t.microsecond
            for t in (self.start_time, self.end_time)
        ):
            raise ValueError("作息使用本地分钟精度，不接受时区或秒")
        if self.start_time >= self.end_time:
            raise ValueError("开始须早于结束，跨午夜课程须拆开")
        if self.slot_id is None:
            self.slot_id = f"period-{self.period_no}"
        return self


class TimeCalendarOverride(StrictModel):
    date: date
    override_type: Literal["STOP", "MAKEUP"]
    source_teaching_week: int | None = Field(default=None, ge=1, le=60)
    source_teaching_weekday: int | None = Field(default=None, ge=1, le=7)

    @model_validator(mode="after")
    def complete(self):
        if self.override_type == "MAKEUP" and self.source_teaching_weekday is None:
            raise ValueError("补课必须指定来源星期")
        if self.override_type == "STOP" and (
            self.source_teaching_week or self.source_teaching_weekday
        ):
            raise ValueError("停课不能携带补课来源")
        return self


class TimeConfiguration(StrictModel):
    effective_from: date
    time_basis: Literal["PERIODS", "CLOCK"] = "PERIODS"
    periods: list[PeriodTime] = Field(min_length=1, max_length=60)
    calendar: list[TimeCalendarOverride] = Field(default_factory=list, max_length=420)
    grid_slot_mapping: dict[str, int] = Field(default_factory=dict, max_length=60)
    confirm_existing_tasks: bool = False

    @model_validator(mode="after")
    def grid_mapping_valid(self):
        if self.time_basis == "CLOCK" and (
            len(self.periods) != 1 or self.periods[0].period_no != 1 or self.grid_slot_mapping
        ):
            raise ValueError("独立时段仅使用一个内部时间槽，不接受教学节次映射")
        periods = {period.period_no for period in self.periods}
        for raw, target in self.grid_slot_mapping.items():
            if (
                not raw.isascii()
                or not raw.isdecimal()
                or str(int(raw)) != raw
                or not 1 <= int(raw) <= 60
                or target not in periods
            ):
                raise ValueError("教务小节映射须为 1..60 的标准整数键，目标须为已配置节次")
        mapped = [
            target
            for _, target in sorted(self.grid_slot_mapping.items(), key=lambda pair: int(pair[0]))
        ]
        if mapped != sorted(mapped):
            raise ValueError("教务小节映射须保持时间顺序")
        return self

    @field_validator("periods")
    @classmethod
    def periods_ordered(cls, values):
        values = sorted(values, key=lambda v: v.period_no)
        if len({v.slot_id for v in values}) != len(values):
            raise ValueError("时段稳定标识重复")
        if len({v.period_no for v in values}) != len(values):
            raise ValueError("节次号重复")
        if any(a.end_time > b.start_time for a, b in zip(values, values[1:], strict=False)):
            raise ValueError("节次时间须按编号递增且不重叠")
        return values

    @field_validator("calendar")
    @classmethod
    def unique_dates(cls, values):
        if len({v.date for v in values}) != len(values):
            raise ValueError("同日只能有一个学院校历覆盖")
        return sorted(values, key=lambda v: v.date)


class TimePublish(TimeConfiguration):
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")
