"""数据库公共规范：约束命名约定与 MySQL 方言默认值。

集中定义，供 Base.metadata 使用，让 Alembic 生成一致的约束名（技术方案 5.2、8）。
"""

from __future__ import annotations

from typing import Any

# InnoDB 表选项与字符集：所有 __table_args__ 复用。
MYSQL_TABLE_ARGS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

# Alembic/DDL 约束命名约定，避免默认匿名约束导致迁移漂移。
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
