# CourseManagement 查课管理系统

面向学校多学院的查课管理平台，包含教务资料导入、学生与班级、志愿者组织、课次抽查、任务排班、考勤异议和报表，以及独立的学生云端个人课表。

主仓库：[Ouroboros-ga/CourseManagement](https://github.com/Ouroboros-ga/CourseManagement)，主协作分支 `dev-main`。小程序上游：[Mo-Qiong/wxsign](https://github.com/Mo-Qiong/wxsign)；本地 `apps/wechat-miniapp/` 是适配副本，来源和同步边界见 [UPSTREAM_PROVENANCE](apps/wechat-miniapp/UPSTREAM_PROVENANCE.md)。

## 优先阅读

1. [产品、架构与 Web 重构总体设计](docs/development/CAMPUS_PRODUCT_ARCHITECTURE_WEB_REDESIGN_20261015.md)：最新讨论形成的七入口、学院自导、跨学期数据、权限、跨院结果归属和 R0—R6 计划；智能体本轮暂缓。
2. [全校产品需求](docs/product/CAMPUS_MANAGEMENT_PRD.md)：需求编号、已确认规则和验收场景。
3. [当前实施状态与下一步](docs/development/IMPLEMENTATION_STATUS.md)：区分已有代码、后续改造和未启用/未验收事项。

全部有效资料见 [文档导航](docs/README.md)。旧方案、阶段记录与发布验收见 [历史归档](docs/archive/README.md)，不作为当前执行计划。

## 当前边界

仓库已有 FastAPI 后端、Vue 管理端及小程序适配代码；多学院配置、资源授权、多作息、组织成员与排班、影响处置和个人课表已有相应实现。代码存在不代表生产全部启用或完整产品验收完成。

最新七入口及生命周期页面重构、共享教务身份和跨院独立检查仍属于后续设计。此前生产正式业务隔离及组织排班保持关闭；本 README 不代替实时服务器核验。剩余工作以当前状态页和最新设计为入口，不以历史测试数字判定完成。

## 开发入口

| 部分 | 技术栈 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.12、FastAPI、Pydantic 2、同步 SQLAlchemy 2、PyMySQL、MySQL 8.4、Alembic、uv | [后端开发](backend/README.md) |
| Web | Vue 3、TypeScript、Vite、Pinia、Element Plus | [管理端开发](apps/admin-web/README.md) |
| 小程序 | 原生 WXML/JavaScript/WXSS/JSON、TDesign | [小程序开发](apps/wechat-miniapp/README.md) |

后端：

```powershell
cd backend
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web：

```powershell
cd apps/admin-web
npm.cmd ci
npm.cmd run dev
```

Vite 固定监听 `127.0.0.1:3000`，默认将 `/api` 和 `/health` 代理到 `http://127.0.0.1:8000`；`BACKEND_URL` 可以覆盖目标。启动和数据库写入前核对实际环境；本地数据库 Compose 示例在 `deploy/docker-compose.yml`，不能用其端口推断生产连接。

## 接口、规则与运行资料

- [API 契约](docs/API_CONTRACT.md)、[接口索引](docs/API_INDEX.md)、[OpenAPI](docs/openapi.json)。
- [权限策略](docs/PERMISSIONS.md)、[排班规则参考](docs/SCHEDULING_RULES.md)。
- [小程序现有业务交接](docs/integration/WECHAT_DEVELOPER_CHANGES_20261014.md)、[个人课表与通知接口](docs/integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md)。
- [微信配置](docs/WECHAT_RUNTIME_CONFIG.md)、[备份恢复手册](docs/RUNBOOK_BACKUP_RESTORE.md)、[按需负载验收手册](docs/RUNBOOK_LOADTEST_ACCEPTANCE.md)。

核心约束：服务端范围授权、字符串 ID、关键写入与审计同事务、版本冲突 409、生成与排班两阶段、异议一次审核、个人课表不参与正式业务。历史文档中的旧状态、旧目录或初终审设计不能覆盖后续确认规则。

本地 `tmp/`、凭证、真实学生资料、依赖与编译产物不纳入公开文档。归档保留原始设计和证据的 Git 历史，不通过删除旧记录伪造当前完成状态。
