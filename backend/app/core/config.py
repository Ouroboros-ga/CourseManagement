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

    # ---- 查课任务与排班（P4）----
    # 以下均为"上线部署参数"而非写死的学校制度（技术方案 1.2 / DEVELOPMENT_PLAN 冻结纪律）：
    # 默认每日截止时间示例 22:00，实际由管理端配置覆盖；这里仅提供首次为某天建任务时
    # 生成该日截止记录所用的种子默认值。
    default_submission_deadline_time: str = Field(
        default="22:00", alias="DEFAULT_SUBMISSION_DEADLINE_TIME"
    )
    # 截止时刻以本地墙上时钟配置，落库统一转 naive-UTC（与 utcnow() 同域可比）。
    # 中国校区单时区，偏移仅作基础设施换算，可按部署环境覆盖，不是业务制度数值。
    app_utc_offset_hours: float = Field(default=8.0, alias="APP_UTC_OFFSET_HOURS")
    # 有界同步生成：单次生成计划的任务数超此上限时在写入前拒绝，提示缩小选择范围。
    inspection_generate_max_tasks: int = Field(
        default=2000, alias="INSPECTION_GENERATE_MAX_TASKS"
    )
    # 排班软约束：单个志愿者单个查课日的最大受派任务数，0 表示不限（默认）。
    # 属可配置运行参数而非学校制度，硬约束（时间冲突/本班回避/资格）始终强制。
    assignment_max_tasks_per_day: int = Field(
        default=0, alias="ASSIGNMENT_MAX_TASKS_PER_DAY"
    )

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
