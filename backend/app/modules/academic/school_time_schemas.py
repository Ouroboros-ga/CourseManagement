from datetime import date
from typing import Literal

from pydantic import Field, field_validator

from app.modules.academic.time_schemas import PeriodTime, TimeConfiguration
from app.modules.organization.schemas import StrictModel, Versioned


class TemplateContent(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    periods: list[PeriodTime] = Field(min_length=1, max_length=60)

    @field_validator("periods")
    @classmethod
    def ordered(cls, values):
        if any(not period.name.strip() for period in values):
            raise ValueError("模板中的每个节次必须填写名称")
        return TimeConfiguration.periods_ordered(values)


class TemplateRevision(TemplateContent):
    lock_version: int = Field(ge=1)


class TemplateStatus(Versioned):
    status: Literal["ACTIVE", "INACTIVE"]


class TemplateImport(StrictModel):
    template_version_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    name: str = Field(min_length=1, max_length=128)
    effective_from: date

    @field_validator("template_version_id")
    @classmethod
    def id_range(cls, value):
        if int(value) >= 2**63:
            raise ValueError("模板版本标识超出范围")
        return value
