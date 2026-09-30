"""教师账号管理契约；口令仅入参，不进入响应或审计。"""

from typing import Literal

from pydantic import BaseModel, Field


class TeacherAccountCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    initial_password: str = Field(min_length=8, max_length=128)


class TeacherAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    lock_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=512)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)
    lock_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=512)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
