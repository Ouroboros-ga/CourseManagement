from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool


class AdpConfiguration(BaseModel):
    """Deployment configuration only; never accepted from an assistant request."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    app_id: str = Field(pattern=r"^[1-9][0-9]{0,31}$")
    region: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    domain: int = Field(ge=1, le=2, strict=True)
    secret_id: SecretStr = Field(min_length=1, repr=False)
    secret_key: SecretStr = Field(min_length=1, repr=False)
    session_token: SecretStr | None = Field(default=None, repr=False)
    timeout_seconds: float = Field(default=10, gt=0, le=30)
    header_binding_verified: StrictBool = False


class ObjectionAdpConfiguration(AdpConfiguration):
    proof_delivery_verified: StrictBool = False


class AdpChatConfiguration(BaseModel):
    """Interactive application configuration; independent of background workflow credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    app_key: SecretStr = Field(min_length=1, max_length=512, repr=False)
    tool_app_key_id: str = Field(min_length=1, max_length=64)
    header_binding_verified: StrictBool = False
    timeout_seconds: float = Field(default=30, gt=0, le=60)


class AdpDispatchLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_active: int = Field(default=5, ge=1, le=10, strict=True)
    poll_interval: int = Field(default=2, ge=1, le=30, strict=True)
    wait_seconds: int = Field(default=300, ge=30, le=480, strict=True)
    max_polls: int = Field(default=100, ge=1, le=300, strict=True)


class AdpChatQueueLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_active: int = Field(default=1, ge=1, le=10, strict=True)
    max_queued: int = Field(default=100, ge=1, le=1000, strict=True)
    max_wait_seconds: int = Field(default=600, ge=30, le=3600, strict=True)
