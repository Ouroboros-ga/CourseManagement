"""通用校验工具（跨业务）。

字符串安全、日期/时区转换等通用逻辑集中于此；与具体资源相关的校验留在各模块
schemas.py / validators，避免把所有业务判断塞进 common。完整规则在功能开发时补齐。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

_CN_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai，无夏令时


def to_utc_datetime(dt: datetime) -> datetime:
    """将带/不带时区的 datetime 归一化为 UTC。

    数据库统一存 UTC DATETIME(3)，界面按 Asia/Shanghai 展示。
    naive 输入按东八区（校园本地时区）解释。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CN_TZ)
    return dt.astimezone(UTC)


def is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def ensure_date(value: date) -> date:
    """占位：日期本地日历语义校验（技术方案 8.3）。"""
    return value
