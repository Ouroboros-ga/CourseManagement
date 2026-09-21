"""Alembic 迁移环境（同步 SQLAlchemy + PyMySQL）。

约定（技术方案 5.2）：
- `--autogenerate` 仅生成候选迁移，必须人工检查重命名/回填/索引/约束。
- 生产发布由单独步骤执行 `uv run alembic upgrade head`，不由服务进程启动抢跑。
- 数据库 URL 从应用配置读取（DATABASE_URL），不在本文件硬编码。

生成迁移需要可连通的 MySQL；仅 `alembic revision`（无 -a）或离线 SQL 不需连库。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.core.config import get_settings
from app.models import Base  # 聚合导入所有模型 metadata
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境配置注入数据库 URL，避免在 alembic.ini 暴露凭证。
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
