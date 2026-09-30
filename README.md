# 查课管理系统 V1.0

统一产品依据见 [建设说明 V1.01 合并版](./查课管理系统V1.0建设说明.md)：志愿者继承学生本人权限；新增“已逾期”，允许补交但保留截止时未执行考核结果。当前实现与验收边界见 [功能说明](./docs/FUNCTIONAL_GUIDE.md) 和 [发布验收记录](./docs/RELEASE_ACCEPTANCE.md)。

> 当前选型：FastAPI + SQLAlchemy + Alembic + MySQL + openpyxl；原生微信小程序与 Vue 管理后台。

## 当前开发基线

[技术开发方案 V1.5：Python 原生微信小程序版](查课管理系统V1.0开发技术方案.md) 是设计依据；权限专项以 [业务资源与权限策略 V1.1](./docs/PERMISSIONS.md) 为准。阶段历史与未完成事项见 [开发路线](./docs/DEVELOPMENT_PLAN.md)。

产品用于学院线下查课：基础数据 → 任务生成与排班 → 志愿者提交 → 管理审核 → 学生查询与异议 → 考勤更正 → 统计与版本化周报。

当前仓库已实现 P1–P7 主要业务后端及管理补全接口：管理审核列表/详情、负责人排班权限、精确课次选择与任务 ID、教师账号管理、学生停用联动、课程导出、学院周报发现和审计读取。`CLASS` 周报请求返回 422；周报只含考勤汇总，固定格式 Word 尚待实现。后端综合 MySQL 回归、数据库权限同步、管理端联调仍在验收阶段。原生[微信小程序](./apps/wechat-miniapp/README.md)已接入登录、绑定和查课任务等页面，仍待真实微信身份与真机验收；Vue 管理后台尚未实现。真实规模压测、恢复演练和双端验收尚未完成，整套产品尚未交付。功能路径见 [功能说明](./docs/FUNCTIONAL_GUIDE.md)、[API 索引](./docs/API_INDEX.md) 与 [排班规则](./docs/SCHEDULING_RULES.md)；实际回归结果和发布边界以 [发布验收记录](./docs/RELEASE_ACCEPTANCE.md) 为准。

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
| 部署规划 | Nginx、Docker Compose、私有 COS/OSS；当前代码文件存储仅 `local` 可用，COS/OSS 适配器仍为占位 |
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

## 规划目录（含尚未创建的前端）

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

不设独立 worker.py、job/ 或通用后台任务表。并发测试放在 tests/integration/；到期材料清理入口放在 deploy/scripts/。上图是规划结构，不能据此推断 `apps/` 或所列 docs 文件均已存在；实际端点和操作说明以文档状态表中的当前文档为准。

## 文档状态

| 文档 | 状态 |
|---|---|
| [技术方案 V1.5](查课管理系统V1.0开发技术方案.md) | 当前开发基线，已同步教师角色管理边界 |
| [业务资源与权限策略 V1.1](./docs/PERMISSIONS.md) | 40 个 Permission、默认矩阵、身份生命周期及 API/范围规则 |
| [开发路线](./docs/DEVELOPMENT_PLAN.md) | 分阶段交付范围、依赖与验收门槛，以及首批开发任务 |
| [权限实施对照](./docs/PERMISSIONS_IMPLEMENTATION.md) | 设计接入细节、当前代码差距和新增验收项 |
| [功能说明](./docs/FUNCTIONAL_GUIDE.md) | 已实现的后端功能、角色与操作路径 |
| [API 索引](./docs/API_INDEX.md) | 已挂载 API 的入口索引 |
| [排班规则](./docs/SCHEDULING_RULES.md) | 自动排班约束与校验口径 |
| [P7 统计与周报计划](./docs/P7_REPORT_PLAN.md) | P7 落地状态及 W7d 待办 |
| [发布验收记录](./docs/RELEASE_ACCEPTANCE.md) | 最终回归结果、环境与未完成的交付验收 |
| [建设说明](./查课管理系统V1.0建设说明.md) | 原始产品输入；已调整条款以当前技术方案及用户决定为准 |

早期 Java/课程查询方案的历史文档（初始化报告、初始化指南、旧 database.sql 与 database_design.md）已清理；当前数据库设计以 SQLAlchemy 模型、Alembic 迁移及技术方案第 8–9 节为准。

GitHub：[Ouroboros-ga/CourseManagement](https://github.com/Ouroboros-ga/CourseManagement)
