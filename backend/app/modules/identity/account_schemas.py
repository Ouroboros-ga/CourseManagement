"""教师账号管理契约；口令仅入参，不进入响应或审计。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccountCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@\u4e00-\u9fa5-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    initial_password: str = Field(min_length=6, max_length=128)


class TeacherAccountCreate(AccountCreate):
    college_id: int = Field(ge=1)


class TeacherAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    lock_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=512)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)
    lock_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=512)


class AdministratorAccountCreate(AccountCreate):
    model_config = ConfigDict(extra="forbid")
    can_manage_administrators: bool = False


class AdministratorAccountUpdate(TeacherAccountUpdate):
    model_config = ConfigDict(extra="forbid")
    can_manage_administrators: bool | None = None


class PasswordChange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str | None = Field(default=None, max_length=128)
    old_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)

    @model_validator(mode="after")
    def resolve_current_password(self) -> PasswordChange:
        if not self.current_password and self.old_password:
            self.current_password = self.old_password
        if not self.current_password:
            raise ValueError("当前旧密码不能为空")
        return self
