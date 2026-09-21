"""安全基础：密码哈希与会话令牌原语。

- 密码使用 Argon2id（固定参数），符合技术方案 7.1。
- 令牌编解码 / 会话校验的完整实现在阶段 1 补齐；此处提供可复用的底层原语，
  不含业务权限判断（业务资源归属留在各模块 permissions.py）。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.exceptions import AppError, ErrorCode

# 固定参数的 Argon2id 实现；上线前应完成密码校验成本压测。
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

_JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def generate_secure_token(nbytes: int = 32) -> str:
    """生成 URL-safe 随机令牌（用于刷新凭证、绑定码等）；仅保存其不可逆摘要。"""
    return secrets.token_urlsafe(nbytes)


def hash_token(value: str) -> str:
    """对不透明令牌（刷新凭证 / 绑定码）取 sha256 摘要后入库，绝不存明文。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_access_token(
    *,
    user_id: int,
    session_id: int,
    roles: list[str],
    permissions: list[str],
) -> str:
    """签发短期访问令牌（HS256）。

    令牌仅携带会话引用与身份声明；接口仍必须回查 auth_session 是否有效
    （未撤销、未过期），不能仅因签名有效就接受已封禁/已登出会话（技术方案 7.3）。
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "roles": roles,
        "perms": permissions,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, object]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:  # 过期、签名错误、格式非法等统一按未认证处理
        raise AppError(ErrorCode.UNAUTHENTICATED, "访问令牌无效或已过期", http_status=401) from exc


def assert_not_default_secret(secret: str) -> None:
    if secret == "change_me_to_a_long_random_string":
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "SECRET_KEY 未配置，生产环境必须提供强随机密钥",
            http_status=500,
        )
