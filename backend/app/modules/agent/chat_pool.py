"""Short admission locks only; the lock connection is released before any model request."""

import hashlib
import logging
import threading
import weakref
from _thread import LockType
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.core.exceptions import AppError, ErrorCode

logger = logging.getLogger(__name__)
_registry: weakref.WeakKeyDictionary[Engine, dict[str, LockType]] = weakref.WeakKeyDictionary()
_registry_lock = threading.Lock()


@dataclass(frozen=True)
class PoolGuard:
    connection: Connection | None = field(default=None, repr=False)

    def count(self, session, statement):
        value = (
            self.connection.scalar(statement)
            if self.connection is not None
            else session.scalar(statement)
        )
        return int(value or 0)


@contextmanager
def capacity_guard(session, environment, app_key_id):
    bind = session.get_bind()
    engine = getattr(bind, "engine", bind)
    scope = f"{engine.url.database or ''}:{environment}:{app_key_id}"
    name = "course_chat_" + hashlib.sha256(scope.encode()).hexdigest()[:48]
    if engine.dialect.name == "sqlite":
        # Development/test fallback only. Cross-process coordination uses MySQL below.
        with _registry_lock:
            locks = _registry.setdefault(engine, {})
            lock = locks.setdefault(name, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield PoolGuard() if acquired else None
        finally:
            if acquired:
                lock.release()
        return
    if engine.dialect.name != "mysql":
        raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE, "当前数据库不支持对话池协调", 503)
    with engine.connect() as connection:
        try:
            acquired = connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name})
        except Exception:
            connection.invalidate()
            raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE, "对话池暂不可用", 503) from None
        try:
            yield PoolGuard(connection) if acquired == 1 else None
        finally:
            if acquired == 1:
                try:
                    released = connection.scalar(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
                    if released != 1:
                        connection.invalidate()
                except Exception:
                    # Never return a connection with an unconfirmed session lock to the pool.
                    connection.invalidate()
                    logger.error("chat_pool_lock_release_failed")
