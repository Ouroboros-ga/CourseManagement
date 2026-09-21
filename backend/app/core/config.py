"""应用配置：基于 pydantic-settings，从环境变量与 .env 读取。

拒绝客户端写入服务端所有权字段的职责由各模块 Schema 承担；此处仅集中环境配置。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用 ----
    app_env: str = Field(default="dev", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")

    # ---- 数据库 ----
    database_url: str = Field(
        default="mysql+pymysql://root:change_me@127.0.0.1:3306/course_management?charset=utf8mb4",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")

    # ---- 安全 / 令牌 ----
    secret_key: str = Field(default="change_me_to_a_long_random_string", alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=30, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    session_expire_days: int = Field(default=30, alias="SESSION_EXPIRE_DAYS")
    login_max_failed: int = Field(default=5, alias="LOGIN_MAX_FAILED")
    login_lock_minutes: int = Field(default=15, alias="LOGIN_LOCK_MINUTES")

    # ---- Web 刷新令牌 Cookie 与 CSRF（技术方案 7.1）----
    # Web 端 refresh 经 HttpOnly Cookie 下发；Secure 生产必须为 True，
    # 本地 http://localhost 调试可在 .env 覆盖为 False，否则浏览器会丢弃该 Cookie。
    refresh_cookie_name: str = Field(default="refresh_token", alias="REFRESH_COOKIE_NAME")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax", alias="COOKIE_SAMESITE"
    )
    cookie_domain: str | None = Field(default=None, alias="COOKIE_DOMAIN")
    # Cookie 承载的写接口（/auth/refresh）CSRF 防护允许的来源（逗号分隔）。
    csrf_allowed_origins: str = Field(default="", alias="CSRF_ALLOWED_ORIGINS")

    # ---- CORS ----
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    # ---- 微信登录（P2）----
    # appid/secret 只能经环境注入，绝不写入仓库、响应、审计或日志。
    wechat_login_enabled: bool = Field(default=False, alias="WECHAT_LOGIN_ENABLED")
    wechat_appid: str = Field(default="", alias="WECHAT_APPID")
    wechat_secret: str = Field(default="", alias="WECHAT_SECRET")
    wechat_code2session_url: str = Field(
        default="https://api.weixin.qq.com/sns/jscode2session",
        alias="WECHAT_CODE2SESSION_URL",
    )
    # 出站调用超时（秒），避免微信接口抖动拖垮同步线程池。
    wechat_timeout_seconds: float = Field(default=5.0, alias="WECHAT_TIMEOUT_SECONDS")
    # 一次性绑定码有效期（分钟）与失败次数上限（PERMISSIONS.md 9.2）。
    binding_token_valid_minutes: int = Field(default=60, alias="BINDING_TOKEN_VALID_MINUTES")
    binding_token_max_failed: int = Field(default=5, alias="BINDING_TOKEN_MAX_FAILED")

    # ---- 导入（预览→确认两步、整批原子）----
    import_preview_ttl_minutes: int = Field(
        default=30, alias="IMPORT_PREVIEW_TTL_MINUTES"
    )
    import_max_rows: int = Field(default=5000, alias="IMPORT_MAX_ROWS")

    # ---- 日志 ----
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def csrf_allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.csrf_allowed_origins.split(",") if o.strip()]

    @property
    def refresh_cookie_max_age(self) -> int:
        """刷新 Cookie 生命周期（秒），与刷新凭证有效期对齐。"""
        return self.refresh_token_expire_days * 24 * 3600

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "prod"


@lru_cache
def get_settings() -> Settings:
    """单例配置读取，避免重复解析 .env。"""
    return Settings()
