# CourseManagement 智能协作与开发指引

本文档适用于整个仓库，是 AI Agent 与开发者协作的基础。以开放、前瞻、准确的态度参与设计、实现、审查、测试和交付：理解功能目的，主动指出架构与代码缺陷，讨论更好的方案，并在已确认范围内推进工作。

保持独立技术判断。发现次优决策时，用具体场景、代码证据和收益解释改进建议；既不机械服从陈旧实现，也不为了“优雅”引入没有实际收益的重构。用户本次明确要求优先于本文档中的一般约定。

**模型分工：默认 GPT/ChatGPT 直接完成工作，并亲自编写复杂、高要求的代码和内容。不主动调用子 agent；只有用户明确询问或要求拆分/委派/任务书时，才为边界明确的执行任务生成低成本模型交接包。生成任务书与启动执行分别授权，GPT 保持集成和最终验收责任。**

## 1. 核心阵地与开源协作

- **主项目**：[Ouroboros-ga/CourseManagement](https://github.com/Ouroboros-ga/CourseManagement)。origin 为 `git@github.com:Ouroboros-ga/CourseManagement.git`，主协作分支目前为 `dev-main`。
- **小程序上游**：[Mo-Qiong/wxsign](https://github.com/Mo-Qiong/wxsign)，默认分支 `main`。
- **本地适配副本**：`apps/wechat-miniapp/`。它不是子模块或上游逐字镜像；本地包含 FastAPI 接口适配、测试及独立功能。
- **来源记录**：[UPSTREAM_PROVENANCE.md](apps/wechat-miniapp/UPSTREAM_PROVENANCE.md)，维护上游完整 SHA、同步范围、许可信息、冲突选择和验证结果。

每次开始工作先核对 `git status --short`、`git branch --show-current`、`git log -5 --oneline`。保留其他任务留下的修改，清楚区分本任务差异；可以主动建议更好的分支或提交策略，但不要自行切换 HEAD、重置工作区或覆盖脏文件。

同步上游时先独立拉取到 `tmp/`，备份本地文件及 binary diff，再用“上次已同步上游 / 当前本地 / 最新上游”三方合并。CRLF/LF 不作为业务冲突；实际冲突按本项目后端契约解决。引入业务代码和公开配置，保留本地文档、测试、环境适配和未提交功能；删除资源前核对引用。不要引入 `.git`、私有开发者配置、node_modules 或编译产物。同步完成更新来源记录。

## 2. 技术栈与架构演进

- **后端**：`backend/`，Python 3.12、FastAPI、Pydantic 2、同步 SQLAlchemy 2、PyMySQL、MySQL 8.4、Alembic；使用 `uv` 和 `uv.lock` 管理依赖及环境。
- **业务模块**：`backend/app/modules/{identity,academic,importer,inspection,attendance,objection,report,file,audit}`。`app/main.py` 负责应用组装与路由挂载。
- **职责边界**：Router 处理 HTTP 和入口守卫，Schema 定义契约，Service 执行授权、规则、事务与审计，Repository 负责查询，Model 定义表结构。发现 Router 堆积业务逻辑时，说明具体问题并移入合适的业务单元。
- **公共规则**：解析在 `app/common/parsing/`；实际课次与抽查在 `inspection/course_occurrences.py`；排班约束与规划器在 `inspection/scheduling/`。复用这些规则，避免双端或新服务维护第二套算法。
- **管理端**：`apps/admin-web/`，Vue 3、TypeScript、Vite、Pinia、Element Plus。接口在 `src/api/`，身份与学期上下文在 `stores/session.ts`，页面在 `views/`。
- **小程序**：`apps/wechat-miniapp/miniprogram/`，原生 WXML/JavaScript/WXSS/JSON 与 TDesign；按 `api / utils / pages` 分工。
- **工程资料**：迁移在 `backend/migrations/versions/`，ORM 聚合入口为 `app/models.py`；部署配置与清理脚本在 `deploy/`，资料在 `docs/`，本地备份和复现在 Git 忽略的 `tmp/`。

从正确性、维护成本、性能和用户体验讨论架构演进。提出重构时说明触发场景、替代方案、迁移成本和验证方法；涉及队列、异步数据库、缓存或额外服务时，先证明现有方案的瓶颈，再推动有依据的调整。

## 3. 动态事实与开发资料

**当前实现用代码和可复现行为核对，正确目标以用户确认的需求和业务约束为准。** 代码中的缺陷不能因为“已经这样运行”就成为规范。文档提供设计意图与历史上下文，发现差异要指出并同步更新。

| 资料 | 用途 |
| --- | --- |
| [技术开发方案](查课管理系统V1.0开发技术方案.md)、[建设说明](查课管理系统V1.0建设说明.md) | 产品目标、设计背景 |
| [权限策略](docs/PERMISSIONS.md) | 权限与数据范围；实际默认矩阵在 `identity/policy.py`，数据库映射由 `seed.py` 同步 |
| [API 契约](docs/API_CONTRACT.md)、[接口索引](docs/API_INDEX.md)、[OpenAPI](docs/openapi.json) | 接口资料；与当前挂载路由、schema 和调用端一起核对 |
| [排班规则](docs/SCHEDULING_RULES.md)、[功能说明](docs/FUNCTIONAL_GUIDE.md)、[管理补全计划](docs/BACKEND_COMPLETION_PLAN.md) | 领域规则与业务路径 |
| [后端说明](backend/README.md)、[管理端说明](apps/admin-web/README.md)、[小程序说明](apps/wechat-miniapp/README.md) | 开发入口，命令与地址须核对当前配置 |
| [2026-10-13 代码审查](docs/CODE_REVIEW_20261013.md) | 本次发现、同步范围和验证边界；后续修复更新状态 |
| [全校升级产品需求](docs/product/CAMPUS_MANAGEMENT_PRD.md) | 多学院、权限、作息、自习、组织及个人课表的需求/验收入口；配置底座已开始实施，整体进度见实施计划 |
| [后端与 Web 开发设计](docs/development/CAMPUS_BACKEND_WEB_DESIGN.md) | 数据模型、范围授权、API、事务、Web 页面、迁移及测试；只涵盖后端与 Web 开发，小程序仅见产品需求 |
| [升级实施计划](docs/development/CAMPUS_IMPLEMENTATION_PLAN.md)、[配置底座说明](docs/development/CAMPUS_CONFIGURATION_GUIDE.md) | 分阶段进度与当前已实现边界；配置底座不等于旧业务已隔离或新规则已参与排班 |
| [智能体交接工作流](docs/AGENT_HANDOFF_WORKFLOW.md)、[任务模板](templates/agent-handoff/TASK.md) | 简单任务拆包、第三方执行、并行隔离与 GPT 验收 |
| [开发技能清单](docs/DEVELOPMENT_SKILLS_20261013.md) | 已安装技能及针对本项目的适配边界 |
| [发布验收](docs/RELEASE_ACCEPTANCE.md)、[后端部署](docs/DEPLOYMENT_20260930.md)、[管理端部署](docs/ADMIN_WEB_DEPLOYMENT_20260930.md) | 历史发布证据，不代替当前线上核验 |
| [微信配置](docs/WECHAT_RUNTIME_CONFIG.md)、[恢复手册](docs/RUNBOOK_BACKUP_RESTORE.md)、[压测手册](docs/RUNBOOK_LOADTEST_ACCEPTANCE.md) | 平台接入与运行验收 |

例如，旧 README 的“管理后台尚未实现”“固定 Word 待实现”已经与 2026-10-13 工作区不符。不要被这些旧描述限制，也不要把历史测试数字当作当前通过结果。接口变化同步契约、索引和 OpenAPI；业务行为变化同步规则和验收说明。

## 4. 流畅的开发体验

### 后端

在 `backend/` 工作，新环境使用 `uv sync --locked`；已有环境可直接使用 `.venv/Scripts/python.exe`，避免 Windows Store Python 占位程序。

```powershell
# backend/
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

本地 MySQL Compose 为 `deploy/docker-compose.yml`，宿主机端口 `13306`。开发库未就绪时，核对 `.env.example`、实际目标和服务状态，再完成必要的启动、迁移或 seed；这些步骤会写数据库，应落在任务明确授权的环境。不要用迁移或 seed 掩盖未知连接目标。

`/health/live` 检查进程，`/health/ready` 检查数据库连接；它们不证明业务、权限或迁移完整性。

### 管理端

```powershell
# apps/admin-web/
npm.cmd ci
npm.cmd run dev
# http://127.0.0.1:3000
```

Windows/PowerShell 优先 `npm.cmd`。当前 Vite 在 `127.0.0.1:3000` 固定端口运行，默认将 `/api` 和 `/health` 代理至 `http://127.0.0.1:8000`，可通过 `BACKEND_URL` 覆盖。设置云端地址后，页面写操作作用于云端数据库。

管理端 access token 在内存，refresh token 使用 HttpOnly Cookie；保留串行 401 刷新与至多一次重试。生产页面/API 使用同源代理。

### 微信小程序

在 `apps/wechat-miniapp/miniprogram/` 安装依赖，再由微信开发者工具导入 `apps/wechat-miniapp/`，执行“工具 → 构建 npm”。公开配置保持 `urlCheck=true`，本机调试使用被忽略的 `project.private.config.json`。

当前 `utils/env.js` 默认 `prod`，指向 `https://course.zsitai.xyz`；使用前核对模式和地址。AppID 与后端配置必须匹配，AppSecret 留在服务端。真实登录还需合法 HTTPS 域名、`wx.login → code2session` 和平台验证。

小程序 refresh 使用 JSON `refresh_token`，Web refresh 使用 Cookie；上传使用 `wx.uploadFile`，业务提交只传后端文件 ID。预览证明材料先申请经授权的短期签名 URL，不把 object_key 或裸下载路径当有效链接。

## 5. 核心业务领域模型

- **身份与授权**：五类角色为 `SUPER_ADMIN`、`TEACHER_ADMIN`、`STUDENT_AFFAIRS_MANAGER`、`VOLUNTEER`、`STUDENT`。前端依据 `/me` 有效权限显示操作，服务端核对权限、资源归属及生命周期；按钮隐藏不代替授权。保留最后有效超管保护和停用/解绑后的会话联动。
- **本人范围**：志愿者操作本人当前受派，学生查询/申诉本人考勤。未绑定微信的有效志愿者可以有排班底册账号；这不等于真实微信身份、绑定和提交验收完成。
- **个人课表边界（已确认需求，待实现）**：小程序个人课表只供本人查看和编辑，以本人最后成功保存为准；教务更新仅在小程序内提示，用户主动采用后才修改个人副本。个人课表不作为排班、考勤、免到、资格或报表的输入，学校作息变化也不能隐式覆盖个人显示。
- **全校升级配置目标（待实现）**：早晚自习与普通课共用课程、课表、名单和课次流程；课程类型及志愿者组均可新建、编辑与停用，类型是学院配置数据，不硬编码枚举或名称。教学班持有唯一类型，组内分别配置查课范围和本人课程冲突规则；先按授权、类型和班级筛选，再随机抽查，缺额不跨类型补齐。冲突按具体教学班例外、本人课程类型、默认规则依次匹配，仍检查跨组受派。变更展示未来影响，历史保留快照；停用类型不消除正式课程忙碌。大一值勤是通用配置的验收场景，不另建自习计划或自动免到模块，排班放行不自动改本人考勤。
- **精确下发**：正向勾选本周具体日期/节次课次，使用 `selection_scope`、`selection_revision`。任务生成与指派排班两阶段解耦，第二阶段失败保留第一阶段结果，仅对返回的 `assignable_task_ids` 排班。
- **时间与冲突**：周次日期复用 `first_monday` 和校历；体育课不生成任务，但参与本人课程冲突。手动改派/任务编辑也需保持资格、本班回避、课程/任务冲突、日周上限约束；周上限按 ISO 自然周。
- **考勤状态机**：志愿者提交自动生成正式考勤；提交审核与学生异议初核/终审分清。禁止在查课日期前提交，允许逾期补交，但不得擦除截止时形成的考核事实；取消、恢复和停课联动保持同一边界。
- **并发与审计**：写操作使用 `lock_version` 或 `current_version`，过期返回 409；关键事实、版本和审计同事务。对外 ID 使用字符串，避免 JavaScript Number/parseInt 截断 BIGINT。
- **人工说明**：原因和备注按已确认要求选填，保留业务字段、长度、权限、版本和审计校验；系统失败原因码仍需完整。
- **统计与报表**：当前认定与历史版本分离，异议有效改判、删除等事实变更更新源修订。不可可靠推导班级分母时，不均摊或伪造比例。版本周报保留不可变历史，直接导出与版本归档区分。
- **存储与删除**：当前 local 文件存储可用，object/COS/OSS 仍是占位。删除、重置和解绑前核对历史、外键、文件、角色、会话与报表影响，给出与操作范围匹配的恢复办法。

## 6. 探索式质量保证

测试服务于正确行为和持续演进。真实 bug 先补能失败的回归，再修实现；不删除失败用例或放宽关键门禁来制造全绿。选择能验证变化的检查，不为简单可逆文档修改增加无关测试。

```powershell
# backend/
.\.venv\Scripts\python.exe -m pytest tests/unit -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests --no-cache
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m alembic heads

# apps/admin-web/
npm.cmd run build

# 仓库根：显式枚举小程序 Node 用例
$testFiles = @(Get-ChildItem -LiteralPath apps/wechat-miniapp/tests -Filter '*.test.mjs' | ForEach-Object { $_.FullName })
node --test --test-timeout=5000 --test-reporter=tap @testFiles
git diff --check
```

小程序 package.json 的 `npm test` 目前是占位命令，使用实际 `.test.mjs` 集合。超时、取消、跳过与失败分别记录。

MySQL 集成夹具会删除重建表，只能运行在确认过的独立 `*_test` 数据库，先检查 `tests/integration/conftest.py`。SQLite/模拟 wx 证明局部逻辑，不能证明 MySQL 锁语义、微信编译或真机行为。构建通过也不代替浏览器交互和中文 Word/Excel 版式检查。

交付说明区分已实现、本次验证、历史证据、未验证和未部署。审查按实际影响排序，提供准确位置、触发条件、证据和建议；静态格式告警数量不等于业务 bug 数量。

## 7. 开放、前瞻与工程本能

主动发现跨模块问题，必要时提出全局方案；从用户价值和工程证据解释取舍，避免只追逐新工具或只修表面症状。清晰、直接地指出问题，同时给出可执行的替代方案。

在用户已授权且范围清楚时继续完成工作，不把一般惯例变成反复确认。代码审查、上游拉取与生产发布是不同操作：推送、部署或生产数据变更按对应环境的明确授权执行，发布时记录版本、迁移/权限、验证和回滚路径。

保护 `.env`、AppSecret、私钥、真实 token 和完整学生名单，测试与共享材料使用脱敏数据。保持工作区和 Git 状态可追溯，Windows 删除/移动使用已核对的绝对路径和同一 shell。把这些习惯落实到具体操作，让主要精力用于可靠的功能、体验与性能改进。

## 8. GPT 主导与低成本执行协作规定

- **GPT 必须承担**需求澄清、架构与接口决策、复杂/高要求实现、权限身份、事务并发、关键业务规则、跨模块改造，以及高标准文档/交互。不能把尚未分析清楚的任务包装后直接丢给小模型，也不能为了省 token 牺牲正确性。
- **默认由 GPT 直接完成任务，不主动调用子 agent**，包括执行、审查和验证用途；任务复杂、节省 token、存在可并行步骤或技能建议均不构成调用授权。只有用户明确要求调用子 agent 时，才在该要求范围内调用；过去允许并行不视为后续任务的持续授权。
- **只有用户明确询问或要求任务拆分、委派或任务书时，才生成任务书/交接包**。一般开发、修复、审查请求不触发生成。生成任务书不等于获准启动子 agent、投递第三方工具或自动执行；默认由用户手动投递。
- 用户请求拆分时，可选择已定位根因的局部修复、明确枚举/字段调整、按既定方案补测试、机械性文档同步及确定性检查，先衡量打包、协调、重做与验收成本。用户明确要求多 agent 协作时才安排并行，且受工具和文件所有权约束。
- 用户要求生成任务书后，在 `tmp/agent-handoffs/<batch-id>/<task-id>/` 产出 `TASK.md`、`ACCEPTANCE.md`、`manifest.json`、`BASELINE.json` 和待填写的 `RESULT.md`；在当前用户会话中给出可点击路径、目标、建议执行模型档位及独立验收命令。第三方自动投递还需具体调用授权及已配置入口。
- 任务包写明基线 HEAD/分支、工作区增量与文件哈希、必读材料、允许编辑文件、依赖、预期行为、验收证据、提交格式和升级条件。路径以仓库相对路径为主；实际工具/模型及 token 成本未知时写 unknown/null，不猜测。
- 仅把所需资料交给执行者；技能按任务加载，不灌入整个会话、整个仓库或所有技能。提供已确定的接口与失败用例，让执行者做工程执行而非重复规划。
- 并行任务必须有独立文件所有权，优先独立 checkout/副本并返回补丁；同一文件或共享接口由单一 owner 修改。脏工作区要同步实际文件内容，不能用 HEAD 代替；冲突由 GPT 集成处理，执行者不自行扩范围。
- `allowed_edit_paths` 限制源码/测试修改；任务目录的 RESULT、changes.patch、evidence 写入由 `result_artifacts` 单独允许，验收合同、脚本和基线由 GPT 管理。执行者回传相对基线的最小 patch、实际命令/退出码及必要日志，只在 RESULT 标记 submitted/blocked，不能自称 GPT 已验收；manifest 状态由 GPT/控制器维护，用量无法取得时保留空值。
- GPT 独立核对差异、基线、作用范围、行为和测试，再标记 accepted 或 rework。提交工作不等于完成工作；既有失败和本次新增失败分开，不要求执行者靠关闭门禁或删测试制造全绿。
- 发现权限/事务/业务决策、需要修改共享接口、超出文件范围，或连续两次定向验收仍失败时，立即回传并升级给 GPT，不无限尝试或静默更改目标。
- task_id 状态按 ready → claimed → running → submitted → accepted/rework 流转，必要时 blocked；未投递保持 ready。主模型记录结果和真实成本，减少重复读取和轮询，不承诺未经测量的节省比例。

详细协议、可复用模板与人工投递方式见 [智能体交接工作流](docs/AGENT_HANDOFF_WORKFLOW.md)。本规定定义职责与交付方式，不会自行改变产品模型设置、创建第三方连接或建立自动调度服务。

## 9. 已安装技能的按需使用

本机已补充 `find-skills`、`auth-implementation-patterns`、`mysql`、`vue-best-practices`、`vue-testing-best-practices`、`systematic-debugging` 和官方 `fastapi`。与现有 TDD、代码审查、完成前验证配合；具体内容先读对应 SKILL.md，并以用户需求和项目约束校准。

身份授权/事务等技能主要供 GPT 分析与高要求实现；Vue/定向测试等技能可提示执行模型使用。第三方工具不会自动共享本机 `C:/Users/LIU/.codex/skills`，跨工具任务包提供规则摘要和来源，不假设已安装或已加载。FastAPI 新版本功能、MySQL 托管推荐或组件拆分建议不能代替本项目版本与架构判断。
