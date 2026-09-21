# 查课管理系统后端镜像（基于 uv 的锁定安装）
# 生产启动示例（技术方案 26）：
#   uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
# 迁移由单独发布步骤执行：uv run alembic upgrade head

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
# 先复制依赖清单，利用层缓存
COPY pyproject.toml uv.lock ./
# 构建并安装锁定依赖（不含 dev 组）到 /app/.venv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# 应用代码
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000
# 非 root 运行建议由部署镜像策略补充
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
