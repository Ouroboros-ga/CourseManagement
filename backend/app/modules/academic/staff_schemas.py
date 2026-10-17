"""教职工档案与任职管理的请求契约。

标识一律字符串以保护 BIGINT；学院/学校由工作区路径决定，请求体不携带所有权字段。
姓名只做展示，任何接口都不按姓名匹配档案或账号。
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.modules.organization.schemas import StrictModel

BIGINT = r"^[1-9][0-9]{0,18}$"
StaffId = Annotated[str, Field(pattern=BIGINT)]
OfferingId = Annotated[str, Field(min_length=1, max_length=32)]


class StaffCreate(StrictModel):
    staff_no: str = Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z_-]{1,64}$")
    name: str = Field(min_length=1, max_length=128)
    phone: str | None = Field(default=None, min_length=1, max_length=32)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    reason: str | None = Field(default=None, max_length=512)


class StaffUpdate(StrictModel):
    lock_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def at_least_one_change(self):
        changed = self.model_fields_set - {"lock_version", "reason"}
        if not changed:
            raise ValueError("至少修改一个档案字段")
        if "name" in changed and self.name is None:
            raise ValueError("姓名不能为空")
        if "status" in changed and self.status is None:
            raise ValueError("状态不能为空")
        return self


class AccountLink(StrictModel):
    """明确把档案关联到已存在的登录账号；不读取姓名做匹配。"""

    user_id: StaffId
    lock_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)


class AccountUnlink(StrictModel):
    lock_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)


class Interval(StrictModel):
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("结束日必须晚于开始日（半开区间不含结束日）")
        return self


class TeachingAssignmentCreate(Interval):
    staff_id: StaffId
    semester_id: StaffId
    anchor_type: Literal["LOCAL", "SHARED"]
    teaching_class_id: Annotated[str | None, Field(pattern=BIGINT)] = None
    academic_offering_id: Annotated[str | None, Field(min_length=1, max_length=32)] = None
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def one_anchor(self):
        if self.anchor_type == "LOCAL":
            if self.teaching_class_id is None or self.academic_offering_id is not None:
                raise ValueError("本地任命只允许指定一个本院教学班")
        elif self.academic_offering_id is None or self.teaching_class_id is not None:
            raise ValueError("共享任命只允许指定一个已确认共享身份")
        return self


class ResponsibilityCreate(Interval):
    staff_id: StaffId
    administrative_class_id: StaffId
    duty: Literal["HEAD_TEACHER", "COUNSELOR"]
    reason: str | None = Field(default=None, max_length=512)


class RelationEnd(StrictModel):
    effective_to: date
    lock_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)


class ResponsibilityHandover(StrictModel):
    """同事务结束旧关系并建立新关系；交接日即新关系开始日。"""

    successor_staff_id: StaffId
    effective_on: date
    lock_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)


class BindingTokenReason(StrictModel):
    reason: str | None = Field(default=None, max_length=512)

    @field_validator("reason")
    @classmethod
    def blank_is_none(cls, value):
        return value or None
