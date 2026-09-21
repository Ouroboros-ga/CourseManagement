# 查课管理系统 V1.0

统一产品依据见 [建设说明 V1.01 合并版](./查课管理系统V1.0建设说明.md)：志愿者继承学生本人权限；新增“已逾期”，允许补交但保留截止时未执行考核结果。设计已同步，新增规则的代码适配与验收见 [开发路线增补](./docs/DEVELOPMENT_PLAN.md)。

> 当前选型：FastAPI + SQLAlchemy + Alembic + MySQL + openpyxl；原生微信小程序与 Vue 管理后台。

## 当前开发基线

[技术开发方案 V1.5：Python 原生微信小程序版](查课管理系统V1.0开发技术方案.md) 是当前实施依据；权限专项以 [业务资源与权限策略 V1.1](./docs/PERMISSIONS.md) 为准。下一阶段按 [开发路线](./docs/DEVELOPMENT_PLAN.md) 推进。

产品用于学院线下查课：基础数据 → 任务生成与排班 → 志愿者提交 → 管理审核 → 学生查询与异议 → 考勤更正 → 统计与版本化周报。

当前已存在后端工程、身份相关代码和初始迁移；完整业务授权、查课功能、Web 与小程序仍待建设。最新设计与代码差距见 [权限实施对照](./docs/PERMISSIONS_IMPLEMENTATION.md)，不能以设计已采纳或测试文件存在认定功能已验收。

## 技术栈

| 部分 | 选型 |
|---|---|
| 后端 | Python 3.12 基线、FastAPI、Pydantic 2.x、Uvicorn |
| 数据库访问 | 同步 SQLAlchemy 2.x + PyMySQL |
| 数据库与迁移 | MySQL 8.4 / InnoDB、Alembic |
| Excel | openpyxl |
| Web 管理后台 | Vue 3、TypeScript、Vite、Element Plus |
| 微信小程序 | 原生 WXML、JavaScript、WXSS、JSON |
| 执行方式 | 导入、排班和周报有界同步执行；材料清理由部署定时脚本处理 |
| 部署 | Nginx、Docker Compose、私有 COS/OSS |
| 工程与测试 | pyproject.toml、uv.lock、Ruff、mypy、pytest、真实 MySQL 集成测试 |

## 已确定的业务规则

- 五类角色：超级管理员、教师管理员、学生工作负责人、志愿者、普通学生。
- 学生工作负责人覆盖所有年级；统计查看、异议初核等可选权限默认关闭，由教师管理员逐人开关。
- 教师的 role.assign 仅可手工管理学院内负责人角色，不可授予/撤销 SUPER_ADMIN 或 TEACHER_ADMIN（含本人）；教师角色和全局账号维护由超管负责。
- 超管、教师、学生工作负责人均可管理学生绑定；STUDENT 由有效学生绑定自动维护，VOLUNTEER 由学期资格驱动。
- 未绑定微信用户使用 PRE_BINDING 受限会话，不新增角色；志愿者改派或资格停用后保留本人历史只读。
- 管理端配置每日提交截止时间，任务状态和逾期统计分别处理。
- 照片与证明材料分别定义保留期限；短时签名链接申请时鉴权。
- 考勤当前认定与历史版本分离，关键写入与审计同事务。
- 周报保留不可变历史版本，展示最新版本及更新时间。

保留天数、默认截止时间、逾期补交等推荐参数尚待业务确认，详见技术方案第 1.2 节与第 29 节。

## 规划目录

```text
CourseManagement/
├── apps/
│   ├── admin-web/
│   │   └── src/
│   │       ├── api/
│   │       ├── views/
│   │       ├── components/
│   │       ├── stores/
│   │       ├── router/
│   │       └── utils/
│   └── wechat-miniapp/
│       ├── app.js
│       ├── app.json
│       ├── app.wxss
│       ├── pages/
│       ├── components/
│       ├── services/
│       ├── utils/
│       └── project.config.json
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── security.py
│   │   │   ├── permissions.py
│   │   │   ├── exceptions.py
│   │   │   ├── middleware.py
│   │   │   └── logging.py
│   │   ├── common/
│   │   │   ├── pagination.py
│   │   │   ├── responses.py
│   │   │   └── validators.py
│   │   └── modules/
│   │       ├── identity/
│   │       ├── academic/
│   │       ├── inspection/
│   │       ├── attendance/
│   │       ├── objection/
│   │       ├── report/
│   │       ├── file/
│   │       └── audit/
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   └── tests/
│       ├── unit/
│       └── integration/
├── deploy/
│   ├── docker-compose.yml
│   ├── nginx/
│   └── scripts/
├── docs/
│   ├── PRD.md
│   ├── TECHNICAL_DESIGN.md
│   ├── DATABASE.md
│   ├── API.md
│   ├── PERMISSIONS.md
│   └── templates/
└── README.md
```

不设独立 worker.py、job/ 或通用后台任务表。并发测试放在 tests/integration/；到期材料清理入口放在 deploy/scripts/。docs/ 内文件是后续拆分位置，当前技术方案仍以根目录文件为准。

## 文档状态

| 文档 | 状态 |
|---|---|
| [技术方案 V1.5](查课管理系统V1.0开发技术方案.md) | 当前开发基线，已同步教师角色管理边界 |
| [业务资源与权限策略 V1.1](./docs/PERMISSIONS.md) | 38 个 Permission、默认矩阵、身份生命周期及 API/范围规则 |
| [开发路线](./docs/DEVELOPMENT_PLAN.md) | 分阶段交付范围、依赖与验收门槛，以及首批开发任务 |
| [权限实施对照](./docs/PERMISSIONS_IMPLEMENTATION.md) | 设计接入细节、当前代码差距和新增验收项 |
| [建设说明](./查课管理系统V1.0建设说明.md) | V1.0 与 V1.01 合并版，统一产品需求依据 |
| [初始化指南](./INITIALIZATION_GUIDE.md) | 历史 Java 初稿，待按当前方案重写 |
| [项目初始化报告](./PROJECT_STATUS.md) | 历史记录，不代表当前业务已实现 |
| [数据库设计](./database_design.md) | 旧课程查询模型，待按当前查课业务细化 |
| [database.sql](./database.sql) | 旧数据库脚本，不能直接用作当前方案的初始化迁移 |

本轮根据用户提供的权限文件更新设计与实施对照，未修改业务代码或执行数据库赋权。后续按新基线补齐权限种子、身份生命周期、受限角色分配和业务范围；旧 database.sql 不作为当前查课系统的初始化依据。

GitHub：[Ouroboros-ga/CourseManagement](https://github.com/Ouroboros-ga/CourseManagement)
