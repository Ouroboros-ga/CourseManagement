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

    # ---- 文件上传、访问与保留（P5，技术方案 16）----
    # 下列均为"上线部署参数"而非写死的学院制度（DEVELOPMENT_PLAN §6 冻结纪律）：
    # 大小 / 张数 / 扩展名 / 像素上限 / 签名链接有效期 / 各类材料保留天数均可经环境覆盖，
    # 技术方案标注"示例 / 待业务确认"者取文档化默认值，不作为制度固化。
    file_storage_backend: Literal["local", "object"] = Field(
        default="local", alias="FILE_STORAGE_BACKEND"
    )
    # 本地存储根目录（dev/test 无对象存储时的可插拔后端；生产可切 object 适配器）。
    file_local_storage_dir: str = Field(
        default=".local_files", alias="FILE_LOCAL_STORAGE_DIR"
    )
    file_max_bytes: int = Field(default=10 * 1024 * 1024, alias="FILE_MAX_BYTES")
    file_max_files_per_submission: int = Field(
        default=5, alias="FILE_MAX_FILES_PER_SUBMISSION"
    )
    file_allowed_extensions: str = Field(
        default="jpg,jpeg,png,webp", alias="FILE_ALLOWED_EXTENSIONS"
    )
    file_signed_url_ttl_seconds: int = Field(
        default=300, alias="FILE_SIGNED_URL_TTL_SECONDS"
    )
    # 图像像素上限（防解码炸弹）：以纯解析器读头得宽高乘积判定，V1.0 不引入重型解码库。
    file_max_image_pixels: int = Field(default=40_000_000, alias="FILE_MAX_IMAGE_PIXELS")
    # 按材料类别分别设保留天数（起算为上传成功时刻），落库固化为 expires_at。
    file_retention_submission_photo_days: int = Field(
        default=180, alias="FILE_RETENTION_SUBMISSION_PHOTO_DAYS"
    )
    file_retention_objection_proof_days: int = Field(
        default=180, alias="FILE_RETENTION_OBJECTION_PROOF_DAYS"
    )
    file_retention_report_file_days: int = Field(
        default=365, alias="FILE_RETENTION_REPORT_FILE_DAYS"
    )
    file_retention_temp_days: int = Field(
        default=1, alias="FILE_RETENTION_TEMP_DAYS"
    )
    file_retention_import_file_days: int = Field(
        default=30, alias="FILE_RETENTION_IMPORT_FILE_DAYS"
    )
    # 保留策略版本：随任一保留期配置调整而人工递增，固化进 file_object 以便审计追溯。
    file_retention_policy_version: int = Field(
        default=1, alias="FILE_RETENTION_POLICY_VERSION"
    )

    # ---- 异议（P6，技术方案 14、PERMISSIONS.md 8）----
    # 均为"上线部署参数"而非写死的学院制度（DEVELOPMENT_PLAN §6 冻结纪律）：
    # 异议窗口天数、单次异议证明材料上限可经环境覆盖，取文档化默认值，不作为制度固化。
    # 窗口以考勤记录生成（审核通过）时刻起算，超窗学生不得再对本人该条考勤提异议；
    # 0 表示不限窗口（部署未确定异议期时保守放开，业务上线前按学院制度设正值）。
    objection_window_days: int = Field(default=7, alias="OBJECTION_WINDOW_DAYS")
    # 单次异议可关联的证明材料数上限，0 表示不限（示例默认与提交照片同量级）。
    objection_max_files: int = Field(default=5, alias="OBJECTION_MAX_FILES")

    # ---- 日志 ----
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def csrf_allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.csrf_allowed_origins.split(",") if o.strip()]

    @property
    def allowed_extension_set(self) -> frozenset[str]:
        """允许的下载扩展名集合（小写、去点），供文件模块校验。"""
        return frozenset(
            e.strip().lstrip(".").lower()
            for e in self.file_allowed_extensions.split(",")
            if e.strip()
        )

    def file_retention_days_by_category(self) -> dict[str, int]:
        """材料类别 → 保留天数（上传成功起算）。单一真相源，供落库固化 expires_at。"""
        return {
            "SUBMISSION_PHOTO": self.file_retention_submission_photo_days,
            "OBJECTION_PROOF": self.file_retention_objection_proof_days,
            "REPORT_FILE": self.file_retention_report_file_days,
            "TEMP": self.file_retention_temp_days,
            "IMPORT_FILE": self.file_retention_import_file_days,
        }

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
