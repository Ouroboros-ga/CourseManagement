# 查课管理系统 — 后端 (FastAPI)

V1.0 后端工程，技术基线来自 `../查课管理系统V1.0开发技术方案.md`：
Python 3.12 · FastAPI · SQLAlchemy 2.x · Alembic · MySQL 8.4 · openpyxl（模块化单体，同步 PyMySQL 驱动）。

## 环境要求

- [uv](https://docs.astral.sh/uv/)（依赖与虚拟环境管理）
- Python 3.12（由 uv 自动下载锁定，本仓库 `.python-version` 固定为 `3.12`）
- Docker（本地用 `deploy/docker-compose.yml` 拉起 MySQL 8.4）；或自备可达的 MySQL 实例

## 快速开始（本地全链路）

```bash
cd backend

# 1. 创建虚拟环境并安装锁定依赖（生成 uv.lock / .venv）
uv sync

# 2. 复制环境配置并按需填写（DATABASE_URL / TEST_DATABASE_URL / SECRET_KEY）
copy .env.example .env      # Windows；macOS/Linux 用 cp
#   注意：本机 3306 若被占用，deploy/docker-compose.yml 已把开发库映射到宿主机 13306
#   （避开 Windows 开机动态预留的 3305-3404 端口段），.env 里连接串需与之一致。

# 3. 拉起 MySQL 8.4（含独立测试库 course_management_test）
docker compose -f ../deploy/docker-compose.yml up -d

# 4. 执行迁移建表
uv run alembic upgrade head

# 5. 种子数据：5 角色 / 3 可选权限 / 超级管理员 / 演示班级与学生
#    口令通过环境变量注入，绝不写入仓库
set SEED_ADMIN_PASSWORD=Admin#123   # Windows；Linux/macOS 用 export
uv run python -m app.modules.identity.seed --admin-username admin --admin-display-name 超级管理员

# 6. 启动开发服务器（uvicorn reload）
uv run uvicorn app.main:app --reload --port 8000
```

## 健康检查

- `GET /health/live` — 存活探针：进程在跑即返回 `ok`，不触碰数据库。
- `GET /health/ready` — 就绪探针：执行一次 `SELECT 1` 验证数据库可连通；
  数据库不可用时返回 `503`（`database: down`），不回显敏感信息。
- `GET /docs` — 交互式 OpenAPI（非生产环境开启）。

## 常用命令

```bash
uv run pytest                       # 全部测试（单测 + 连真实 MySQL 的集成测试）
uv run pytest -m "not integration"  # 仅离线单测（无需数据库）
uv run ruff check .                 # Lint
uv run ruff format .                # 格式化
uv run mypy app                     # 类型检查（关键业务）
uv run alembic revision --autogenerate -m "..."   # 生成候选迁移（需可连通 MySQL）
uv run alembic upgrade head         # 执行迁移（由单独发布步骤运行）
```

## 目录结构

```
backend/
├── app/
│   ├── main.py            # 应用组装与路由注册（不放业务流程）
│   ├── models.py          # ORM 模型聚合导入入口（供 Alembic metadata）
│   ├── api/               # 系统级全局端点（健康检查）
│   ├── core/              # 配置、连接、安全、权限基础、异常、中间件、日志
│   ├── common/            # 分页、统一响应、通用校验
│   └── modules/           # 业务模块：identity / academic / inspection /
│                          #   attendance / objection / report / file / audit
├── migrations/            # Alembic 环境与版本
├── tests/                 # unit / integration（集成测试连真实 MySQL，缺库自动跳过）
├── pyproject.toml         # 依赖与工具配置（版本范围，精确版由 uv.lock 锁定）
├── .python-version        # 固定 3.12
└── .env.example           # 环境配置模板（真实 .env 不入库）
```

业务模块按需划分 `router.py / schemas.py / service.py / repository.py / models.py / permissions.py`。
Router 处理 HTTP，Schema 定义输入输出，Service 负责授权/规则/事务，Repository 执行查询，Model 定义表映射。

## 实现状态

运行时权限与接口契约以 [权限策略 V1.1](../docs/PERMISSIONS.md)、[实施对照](../docs/PERMISSIONS_IMPLEMENTATION.md)
和 [后端 API 契约](../docs/API_CONTRACT.md) 为准。

- **第一步（最小后端骨架）已完成**：应用可启动，`/health/live`、`/health/ready`
  （真实连库）通过，Alembic 迁移可连实库执行，密钥（`.env`）不进入 Git。
- **P1 权限基础与管理闭环 已完成**：`PermissionCode` 补齐 38 项、默认角色矩阵经
  `seed.py` 幂等同步；`audit_log` 追加审计表与 `user_account.lock_version` 迁移已落地。
  角色分配与负责人可选权限通过同事务加锁（按 ID 固定顺序 `SELECT … FOR UPDATE`）、
  事务内重验身份/权限/版本、审计同事务单次提交；越权 403、不可见目标 404、
  未知 code 422、版本冲突 409；真实 MySQL 并发与"审计失败整笔回滚"均有集成测试。
- **P2 微信身份闭环 已完成**：`identity/wechat.py` 抽象 code2session（生产 httpx 实现 +
  测试 Mock），凭证非法 401、上游/超时 502；首次微信登录按 appid+openid 自动建"无口令"
  账号并进入 PRE_BINDING 受限会话（仅 `/me`、绑定、刷新、登出白名单）；有效绑定在同一事务
  核销一次性码 + 自动授予 STUDENT + 写审计，绑定码核销对同一码行加 `FOR UPDATE` 锁，
  并发核销仅一人成功；管理员可签发/作废绑定码、换绑/解绑并撤销旧会话；
  `session_key/appid/secret` 绝不进入响应/审计/日志。
- **待接入（P3+）**：`academic` 基础数据与课表/名单导入（解析参考见
  `../docs/legacy_parser_reference/`）、学期志愿者资格自动身份、inspection /
  attendance / objection / report / file 业务模块，以及各模块 permissions.py 的行级数据范围过滤。

> `../INITIALIZATION_GUIDE.md` 与 `../PROJECT_STATUS.md` 为早期 Java 方案的历史文档，
> 不代表当前实现。
