from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EnrollmentChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["TRANSFER", "SUSPEND", "RETURN", "GRADUATE", "WITHDRAW"] = "TRANSFER"
    effective_date: date
    target_class_id: int | None = Field(default=None, ge=1)
    lock_version: int = Field(ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=512)
    leave_teaching_class_ids: list[int] = Field(default_factory=list, max_length=500)
    correct_existing: bool = False

    @model_validator(mode="after")
    def validate_target(self):
        if not 1000 <= self.effective_date.year <= 9989:
            raise ValueError("生效日期超出历史保留支持范围")
        if self.kind in {"TRANSFER", "RETURN"} and self.target_class_id is None:
            raise ValueError("转班或复学必须指定目标行政班")
        if self.kind not in {"TRANSFER", "RETURN"} and self.target_class_id is not None:
            raise ValueError("休学或离校不指定新班级")
        return self


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lock_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=512)


class TaskHandoffReview(VersionRequest):
    confirm_roster: bool = False
    confirm_expected_count: bool = False


class CollegeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)


class TeacherCollegeRequest(VersionRequest):
    college_id: int = Field(ge=1)


class ManagerFunctionsRequest(VersionRequest):
    allowed_actions: list[str] = Field(max_length=50)


class AudienceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    administrative_class_ids: list[int] = Field(max_length=500)
    ownership_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)
