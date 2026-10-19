from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from app.modules.organization.schemas import StrictModel


class MemberCreate(StrictModel):
    student_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    effective_from: date
    effective_to: date
    enable_qualification: bool = False

    @model_validator(mode="after")
    def valid(self):
        if any(int(v) >= 2**63 for v in (self.student_id, self.semester_id)):
            raise ValueError("标识超出 BIGINT 范围")
        if self.effective_from >= self.effective_to:
            raise ValueError("有效期为左闭右开区间，结束须晚于开始")
        return self


class MemberRevoke(StrictModel):
    lock_version: int = Field(ge=1)
    confirm_future_assignments: bool = False


class MemberUpdate(MemberRevoke):
    effective_from: date
    effective_to: date
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_from >= self.effective_to:
            raise ValueError("结束日期必须晚于开始日期")
        return self
