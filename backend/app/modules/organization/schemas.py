"""新配置严格契约：拒绝客户端所有权字段与未知动作，不接受可执行表达式。"""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.modules.identity.authorization import CAMPUS_ACTIONS
from app.modules.volunteer.policy import Effect


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def account_ids_in_range(self):
        for key in ("user_id", "owner_user_id"):
            value = getattr(self, key, None)
            if value is not None and not 0 < int(value) < 2**63:
                raise ValueError("账号标识超出有效 BIGINT 范围")
        return self


class OwnershipMapping(StrictModel):
    mappings: dict[
        Literal["administrative_class", "teaching_class", "import_batch", "report"], dict[str, str]
    ] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_mapping(self):
        if sum(len(entries) for entries in self.mappings.values()) > 2000:
            raise ValueError("单次映射最多 2000 个根资源")
        for entries in self.mappings.values():
            for key, value in entries.items():
                if not (
                    key.isascii() and key.isdecimal() and value.isascii() and value.isdecimal()
                ):
                    raise ValueError("映射标识必须为字符串整数")
                if len(key) > 19 or len(value) > 19:
                    raise ValueError("映射标识过长")
        return self


class OwnershipApply(OwnershipMapping):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class Named(StrictModel):
    name: str = Field(min_length=1, max_length=128)


class SchoolCreate(Named):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class CollegeCreate(SchoolCreate):
    pass


class Versioned(StrictModel):
    lock_version: int = Field(ge=1)

    @model_validator(mode="after")
    def reject_null_values(self):
        for key in self.model_fields_set - {"starts_on", "ends_on"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} 不能为 null")
        return self


class DeletionConfirm(Versioned):
    deletion_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class DeletedRestore(Versioned):
    name: str | None = Field(default=None, min_length=1, max_length=128)


class CollegeUpdate(Versioned):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class TypeCreate(Named):
    description: str = Field(default="", max_length=512)
    display_color: str = Field(default="#409EFF", pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int = Field(default=0, ge=0, le=100000)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class TypeUpdate(Versioned):
    future_impact_revision: str = Field(default="", max_length=64, pattern=r"^(?:|[0-9a-f]{64})$")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    display_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class GrantResourceScope(StrictModel):
    kind: Literal["COLLEGE", "GROUPS", "COURSE_TYPES", "TEACHING_CLASSES"] = "COLLEGE"
    ids: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def valid(self):
        if (self.kind == "COLLEGE") == bool(self.ids) or len(set(self.ids)) != len(self.ids):
            raise ValueError("全院范围不携带资源ID，受限范围必须明确非空集合")
        if any(not value.isascii() or not value.isdecimal() or str(int(value)) != value
               or not 0 < int(value) < 2**63 for value in self.ids):
            raise ValueError("资源标识无效")
        return self


class GrantCreate(StrictModel):
    preview_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    user_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    actions: list[str] = Field(min_length=1, max_length=len(CAMPUS_ACTIONS))
    resource_scope: GrantResourceScope = Field(default_factory=GrantResourceScope)
    starts_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("actions")
    @classmethod
    def actions_known(cls, actions):
        if not set(actions) <= CAMPUS_ACTIONS or len(set(actions)) != len(actions):
            raise ValueError("动作未知或重复")
        return sorted(actions)

    @field_validator("starts_at", "expires_at")
    @classmethod
    def normalize_utc(cls, value, info: ValidationInfo):
        if value and value.tzinfo is None and not (info.context or {}).get("internal"):
            raise ValueError("授权时间必须包含时区")
        # 内部服务兼容项目的 UTC naive，HTTP 入口只接受带时区的契约。
        return value.astimezone(UTC).replace(tzinfo=None) if value and value.tzinfo else value

    @model_validator(mode="after")
    def valid_range(self):
        if self.starts_at and self.expires_at and self.starts_at >= self.expires_at:
            raise ValueError("授权结束必须晚于开始")
        from app.modules.identity.grant_scope import GROUP_ACTIONS, LIMITED_ACTIONS
        if self.resource_scope.kind != "COLLEGE":
            if not set(self.actions) <= LIMITED_ACTIONS:
                raise ValueError("此动作暂不支持资源受限授权，请使用明确院级授权")
            if self.resource_scope.kind != "GROUPS" and set(self.actions) & GROUP_ACTIONS:
                raise ValueError("组织管理动作必须选择指定组范围")
        return self


class GroupCreate(Named):
    owner_user_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    starts_on: date | None = None
    ends_on: date | None = None


class GroupUpdate(Versioned):
    future_impact_revision: str = Field(default="", max_length=64, pattern=r"^(?:|[0-9a-f]{64})$")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    owner_user_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")
    starts_on: date | None = None
    ends_on: date | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class GroupPublish(Versioned):
    future_impact_revision: str = Field(default="", max_length=64, pattern=r"^(?:|[0-9a-f]{64})$")
    class_mode: Literal["ALL_AUTHORIZED", "SPECIFIC"] = "ALL_AUTHORIZED"
    class_ids: list[str] = Field(default_factory=list, max_length=500)
    course_type_ids: list[str] = Field(default_factory=list, max_length=100)
    default_effect: Effect = "BLOCK"
    type_overrides: dict[str, Effect] = Field(default_factory=dict)
    teaching_class_overrides: dict[str, Effect] = Field(default_factory=dict)
    task_conflict_effect: Literal["BLOCK"] = "BLOCK"
    own_class_effect: Effect = "BLOCK"
    daily_limit: int = Field(default=3, ge=1, le=100)
    weekly_limit: int = Field(default=10, ge=1, le=700)
    count_scope: Literal["GROUP", "ALL_GROUPS"] = "ALL_GROUPS"
    buffer_minutes: int = Field(default=0, ge=0, le=120)

    @model_validator(mode="after")
    def default_course_conflicts_only(self):
        if self.type_overrides or self.teaching_class_overrides:
            raise ValueError("仅支持默认课程冲突处理，请清除课程类型及教学班例外后重试")
        return self

    @field_validator("course_type_ids", "class_ids")
    @classmethod
    def valid_ids(cls, values):
        if len(set(values)) != len(values) or any(
            not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63
            for value in values
        ):
            raise ValueError("课程类型标识无效或重复")
        return values

    @model_validator(mode="after")
    def class_scope(self):
        if (self.class_mode == "SPECIFIC") != bool(self.class_ids):
            raise ValueError("指定班级范围须非空；全院模式不携带班级列表")
        for key in self.teaching_class_overrides:
            if not key.isascii() or not key.isdigit() or not 0 < int(key) < 2**63:
                raise ValueError("具体教学班例外标识无效")
        return self
