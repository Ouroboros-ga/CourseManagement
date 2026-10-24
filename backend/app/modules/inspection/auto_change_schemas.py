from pydantic import Field, StrictBool, field_validator

from app.modules.organization.schemas import StrictModel


class AutoChangePolicyUpdate(StrictModel):
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    enabled: StrictBool
    current_version: int = Field(ge=0, le=2**31 - 1, strict=True)

    @field_validator("semester_id")
    @classmethod
    def bounded_id(cls, value):
        if int(value) >= 2**63:
            raise ValueError("学期标识超出范围")
        return value
