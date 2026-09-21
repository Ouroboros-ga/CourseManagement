"""数据库连接与 Session 工厂。

- 采用同步 SQLAlchemy 2.x + PyMySQL（V1.0 基线）。
- Engine / sessionmaker 由应用配置统一创建，惰性初始化：进程启动不强制连库，
  便于在未配置数据库时也能拉起服务与健康检查。
- 每个 API 业务单元 / 清理脚本执行单元独立创建 Session，禁止跨请求或并发线程共享。
  Service 顶层使用 Session 的 begin() 上下文统一管理事务，见各模块约定。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import INTEGER, BigInteger, DateTime, MetaData, create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedColumn,
    Session,
    mapped_column,
    sessionmaker,
)

from app.core.config import get_settings
from app.core.db import NAMING_CONVENTION


def utcnow() -> datetime:
    """业务时间统一以 UTC 存储（DATETIME(3)），界面按 Asia/Shanghai 展示。"""
    return datetime.now(UTC).replace(tzinfo=None)


DATETIME_3 = DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=3), "mysql")

# 业务主键：MySQL 用 BIGINT AUTO_INCREMENT；SQLite（离线单测）降级为 INTEGER。
PkBigInt = BigInteger().with_variant(INTEGER, "sqlite")


def pk_column() -> MappedColumn[int]:
    """BIGINT 自增主键列。API 层以字符串对外暴露（见 common.responses.to_id_str）。"""
    return mapped_column(PkBigInt, primary_key=True, autoincrement=True)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类，供 Alembic 使用统一 metadata 与命名约定。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """可修改记录：created_at + updated_at。"""

    created_at: Mapped[datetime] = mapped_column(
        DATETIME_3, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME_3, nullable=False, default=utcnow, onupdate=utcnow
    )


class CreateTimeMixin:
    """不可变版本/历史表：只需创建时间。"""

    created_at: Mapped[datetime] = mapped_column(
        DATETIME_3, nullable=False, default=utcnow
    )



_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """惰性创建 Engine。create_engine 本身不会建立物理连接。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """脚本 / 非依赖场景使用的独立 Session 事务上下文。

    成功则提交，异常则回滚，最终关闭。请求内业务优先在 Service 顶层使用
    Session.begin() 统一管理，见技术方案 5.1。
    """
    session = get_session_factory()()
    try:
        with session.begin():
            yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：提供只读/请求级 Session，结束后关闭。

    写业务事务应在 Service 内部通过 begin() 掌控，不在依赖里隐式提交。
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
