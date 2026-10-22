# CourseManagement 审计整改决议记录（唯一决策入口）

建立日期：2026-10-21（本轮追加，工作树未改动任何代码）
工作包：**T00 决议落库**
决策来源：项目负责人 2026-10-21 明确的四项产品口径（`CourseManagement_审计整改工作计划_v2_已确认产品规则.md`）
审计依据：`docs/audits/initial-review.md`，原基线 `dev-main@eb30c03`

## 0. 重新基线（实施前必须重做的一步）

| 项 | 值 | 取得方式 |
| --- | --- | --- |
| 本地工作树 | `dev-main@eb30c03`，`git status --short` 仅 `?? docs/audits/` | 本轮实测 |
| 远端实际基线 | `origin/dev-main@8da55fed0f9a9b9cc2daee6c5dbe0bbb11bcaf6e` | `git fetch --all --prune` 后 `git rev-parse` |
| 与审计基线的差距 | 远端领先 **5 个提交**，本地无未推送提交（可安全快进） | `git log --oneline HEAD..origin/dev-main` |
| 5 个提交 | `8da55fe` docs / **`6f4299b` fix(identity) 微信换绑保留学生业务归属** / `484d455` docs / `145dfe8` merge / `fed8518` feat(identity) 教职工绑定码批量 Excel | 同上 |
| 数据库版本 | `f26a1019s007`（`6f4299b` 发布记录确认"数据库版本保持"，本轮无迁移） | `alembic heads` + `docs/development/WECHAT_REBIND_IDENTITY_FIX_20261021.md` |
| V2 文件声称的 `484d455` | 是 `8da55fe` 的祖先，已被后续 2 个提交超越 | `git cat-file -t` + 提交图 |

**结论：本文及其引用的所有行号一律以 `8da55fe` 为准。** 下表是审计报告需要更正的位置（其余引用文件在这 5 个提交中未被改动，行号仍然有效）：

| 审计条目 | 报告内旧引用（eb30c03） | `8da55fe` 正确位置 | 是否影响结论 |
| --- | --- | --- | --- |
| P0-2 任命回填 | `identity/service.py:533-538` | **`identity/service.py:558-563`**（`allowed_actions=sorted(MANAGER_FUNCTION_CODES - {"statistics.read"})` 实测仍在） | 不影响，结论成立 |
| P0-2 默认集 | `identity/policy.py:58-82` | **未变**（`:76` `attendance.correct`、`:78` `attendance.expected_count_adjust`、`:80` `submission.review`、`:104` `MANAGER_FUNCTION_CODES`） | 不影响 |
| P2 会话解析 | `identity/service.py:329`/`:355` | **`identity/service.py:354`/`:372`** | 不影响 |
| P2 学生绑定 | `identity/service.py:1171` | **`identity/service.py:1188`** | 不影响 |
| §1 实测计数：openapi 352 路径 / 413 操作 / 225 写 / 407 标注 security | — | **353 路径 / 414 操作 / 226 写操作 / 408 标注 security**（重新解析 `git show origin/dev-main:docs/openapi.json`） | 数量+1，性质不变 |
| P1-1 `bulk` 双入口仍可达 | 已确认 | **仍成立**：`/api/v1/imports/bulk` 与 `/api/v1/colleges/{cid}/imports/bulk` 都在 `8da55fe` 的 OpenAPI 中 | 不影响 |

## 1. 已确认的四项产品规则（不再由 agent 重新选择）

| ID | 规则 | 权威级别 | 本轮状态 |
| --- | --- | --- | --- |
| **DEC-01** | 志愿者查课提交**立即生效**；自首次成功提交起 **2 小时**内允许本人撤回、修改、重新提交；需要的后端接口**新增**。原始提交与证据永久保留；变动通过事务原子更新当前有效考勤、考勤版本与周报源修订；本人不得覆盖已产生的管理员更正或已处理的异议结果。 | 产品口径（已定） | 已实现（`f26a1021w001` + `f26a1022e001`）：`POST /submissions/{id}/revise`、`POST /submissions/{id}/withdraw`；窗口 `SUBMISSION_CORRECTION_WINDOW_MINUTES`（默认 120，0 关闭）。考勤另立 `effect_state` 有效性轴，默认查询隐藏已撤回行。设计见本地 `docs/audits/T06_WITHDRAW_REVISE_DESIGN.md`（未入库） |
| **DEC-02** | `STUDENT_AFFAIRS_MANAGER` **默认保留** `attendance.correct` 与 `attendance.expected_count_adjust`；仍受有效任命、权限配置与本院资源范围约束；**不得由此推导默认允许 `submission.review`**。 | 产品口径（已定） | 两项已存在于代码，保留；`submission.review` 的遗留越界见 §3 |
| **DEC-03** | 名单导入默认为**补充／差异确认**：上传文件中未出现的现有学生不得被自动删除、停用或隐式移出任务名单；旧 `replace` 参数不得继续形同虚设；任何真实删减必须由明确列示的差异 + 主动确认触发。 | 产品口径（已定） | 已实现：`/imports` roster 恒 `preserve_existing=True`、不再整体替换；传 `replace=true` 时返回 `roster_additive_only` warning；管理端默认 `replace=false` |
| **DEC-04** | 生产继续 **systemd + venv**，本轮**不迁移 Docker**。Dockerfile 只作为单独维护的非生产构建资产，不得形成第二份交付真相。 | 产品口径（已定） | 保持现状；文档需按 §4 标注 |

> DEC-01 取代审计报告 P0-1 中"任选一边"的建议；DEC-02 **推翻**审计 P0-2 中"移除两项"的建议，仅保留 `submission.review` 部分；DEC-03 采纳 P0-4；DEC-04 采纳 P2-7 的"记录不一致但不阻断"。

## 2. DEC-02 的执行边界（防止二次误读）

DEC-02 说"默认允许"，指的是**权限注册层面允许**，不是免除其余判定。实施时必须同时核查以下四处是否一致，任一不一致都算未完成：

1. `identity/policy.py:58-82` 默认集 —— 保留两项，按 §3 处理第三项。
2. `identity/policy.py:104` `MANAGER_FUNCTION_CODES = 默认集 | {statistics.read, volunteer.manage}` —— 该定义使 `allowed_actions` 交集恒不生效，属于"逐人关闭机制失效"的根因，见 §3。
3. `identity/service.py:558-563` 任命创建时回填整个默认集。
4. `academic/college_service.py:196-197`（`configurable_actions` 目录）与 `:224`（`allowed_actions = sorted(set(actions))`）—— 确认 UI 能逐项取消这两项；若产品要求"可逐人关闭"，此处必须可关。
5. `identity/repository.py:128-131` 与 `identity/role_scope.py:130-137` 的运行态交集过滤，以及 `identity/authorization.py:120-123` 的院级动作解析。

验收要求（来自 V2 §三）：同院更正与应到人数调整成功；无任命、失效任命、跨院、已关闭权限者 403/404；普通学生与志愿者不越权；更正写入审计与 `AttendanceRecordVersion(source=CORRECTION)`。

## 3. 由 DEC-02 派生的唯一遗留问题：`submission.review`

`identity/policy.py:80` 目前把 `submission.review` 也放进负责人默认集。DEC-02 未授予它，且 `docs/PERMISSIONS.md` §5 该行标注"否"。

**建议处理（T01，需负责人一句话确认）**：从负责人默认集移除 `submission.review`，保留另外两项。理由：

- 在 DEC-01 落地后，`submission.review` 对负责人**已无任何可执行动作**——提交即生效使审核入口必然 409（`inspection/service.py:3638-3639`），该权限仅剩"读取管理提交工作台"的作用（`inspection/service.py:3530-3534` `_require_management_submission_read`）。
- 保留一个只有读侧副作用、文档明令为"否"、且实现上无写路径的权限，是纯粹的口径噪声。
- 若负责人确实需要浏览志愿者提交明细，正确做法是给它一个显式的读取动作，而不是复用审核权限。

不采纳的替代方案：把 `submission.review` 补写进 `docs/PERMISSIONS.md`。那会让 DEC-01 之后仍然不存在的人工审核权限被文档永久背书。

## 4. 需要修订的既有文档条款（T00 交付内容）

引用方式改为**章节 + 原文片段**，不再依赖行号（远端文档已随 `8da55fe` 变动）。

| 文件 | 待修正条款（现状原文要点） | 修订方向 | 关联决议 |
| --- | --- | --- | --- |
| `AGENTS.md` §顶部实施补充 | "最新迁移为 `f26a1014e001`，基于 `f26a1014m001`" | 改为当前单头 `f26a1019s007`，并约定该行由发布记录驱动更新，不再手写 | 基线正确性 |
| `AGENTS.md` §2 技术栈 | 业务模块清单列 8 个 | 补 `organization / timetable / volunteer`（实测 12 个） | D-3 |
| `AGENTS.md` §3 资料表 | 引用 `docs/FUNCTIONAL_GUIDE.md`、`docs/BACKEND_COMPLETION_PLAN.md`、`docs/RELEASE_ACCEPTANCE.md`、`docs/DEPLOYMENT_20260930.md`、`docs/ADMIN_WEB_DEPLOYMENT_20260930.md`、根目录两份 `查课管理系统V1.0*.md` —— 均已不在声称路径 | 指向 `docs/archive/…` 实际位置或标注"已归档，非现行入口" | D-2 |
| `AGENTS.md` §5 考勤状态机 | "志愿者提交自动生成正式考勤；提交审核与学生异议初核/终审分清" | 补 DEC-01 的 2 小时本人纠错窗口与"不得覆盖管理员更正/已处理异议" | DEC-01 |
| `docs/PERMISSIONS.md` §1.3 | "不具有终审、更正最终考勤、提交审核…" | 更正为负责人默认**具有** `attendance.correct` 与 `attendance.expected_count_adjust`（DEC-02），终审一节已由 2026-10-13 章节改写；`submission.review` 明确为**不具有** | DEC-02 / §3 |
| `docs/PERMISSIONS.md` §5 矩阵 | `attendance.correct`、`attendance.expected_count_adjust` 两行负责人列标"否" | 改"是"；`submission.review` 行保持"否" | DEC-02 |
| `docs/PERMISSIONS.md` §4 注册表 | 表内约 38 项，`core/permissions.py` docstring 亦写"38 项" | 补齐至实际 **42 项**（含 `administrator_account.manage`、`statistics.school.read` 等），docstring 同步 | D-4 |
| `docs/API_CONTRACT.md` 附录 B | `POST /imports` 表单含 `replace=true` | 删除该字段或改为真正的"补充/差异确认"契约；同时说明未列成员不删除 | DEC-03 |
| `docs/API_CONTRACT.md` 附录 D.2/D.3 | "插 `PENDING` 提交"、"`submission.review` 审核通过生成考勤"、"学生工作负责人默认没有 `submission.review`" | 改写为 DEC-01 的提交即生效 + `withdraw`/`revise`；D.3 审核链路标注为遗留/停用 | DEC-01 |
| `docs/API_CONTRACT.md` §12.8（PERMISSIONS） | `POST /submissions/{id}/review` 作为现行端点公布 | 与 DEC-01 一起裁决：标注 deprecated 或说明仅在异常数据修复时使用 | DEC-01 |
| `docs/API_CONTRACT.md` §9 测试覆盖 | 描述 `test_importer.py` 等的 PENDING/审核两步语义 | 随 DEC-01 更新断言描述 | DEC-01 |
| `docs/openapi.json` | 无 `withdraw`/`revise`；写操作 226 个 | T06 落地后再生成，不在本轮手改 | DEC-01 |
| `backend/Dockerfile` 头部注释 | "生产启动示例 … --workers 2"，与线上 `--workers 1`、systemd+venv 不符 | 顶部加一行"非生产构建资产；生产见 `deploy/production/course-management.service`" | DEC-04 |
| `docs/development/IMPLEMENTATION_STATUS.md` | 多条仍写"正式业务隔离与组织排班关闭"，而 2026-10-20 起生产五项开关均为 true | 顶部加当前开关实况，旧条目保留原语境标注 | 运行事实 |

**不在本轮改动**：`initial-review.md` 的 P0 正文保留原样（它是 V2 计划的引用依据），只在末尾追加"重新基线"附录，见 §6。

## 5. T00–T09 实施包、文件所有权与合并顺序

约束继承 V2 §六，并按本轮读到的真实文件边界做了两处收紧（新增 `T06b` 口径扩散清单、`T09` 存量归属核实）。

| 包 | 目标 | 允许改动的文件（所有权唯一） | 依赖 | 完成标准（必须含"先红后绿"） |
| --- | --- | --- | --- | --- |
| **T00** | 本决议 + §4 文档修订 | `docs/audits/decisions.md`（新）、`docs/audits/T06_WITHDRAW_REVISE_DESIGN.md`（新）、`AGENTS.md`、`docs/PERMISSIONS.md`、`docs/API_CONTRACT.md`、`backend/Dockerfile` 首行注释、`docs/development/IMPLEMENTATION_STATUS.md` 顶部 | 无 | 文档内不再存在互相矛盾条款；旧契约段落显式标注失效；不改任何 `.py` |
| **T01** | 负责人默认授权对账 | `identity/policy.py`、`academic/college_service.py`、`identity/service.py`（仅任命段）、`tests/unit/test_permission_policy.py`、`tests/integration/test_admin_rbac.py` | T00 | 新断言先失败后通过：两项**保留**、`submission.review` 移除；跨院/无任命/已关闭三态 403/404 |
| **T02** | 名单导入收敛为补充/差异确认 | `importer/service.py`（roster 解析与 `_apply_roster`、`_apply_admin_roster` 名单段）、`importer/confirmation_diff.py`、`importer/router.py`（删 `replace`）、`academic/roster_lifecycle.py`、相关 `tests/integration/test_importer.py` | T00；**不得与 T03 并发编辑 `importer/service.py`** | 10→12、重复 12、仅 1 名旧成员仍 12；无静默删除；`git grep replace` 在该路径归零 |
| **T02b** | 旧 `bulk` 处置 | `importer/router.py`（`/imports/bulk`）、`importer/scoped_router.py`（路由复制表）、`importer/service.py::import_bulk_files` | 先做调用方调查（只读） | 无依赖则整条下线（含学院别名）并同步 OpenAPI；若保留则必须有读限 + 取消自动 confirm + 异常脱敏 |
| **T03** | 解析资源防护 | `common/parsing/xlsx_tabular.py`、`importer/zip_preview.py`、`importer/intake.py`、`importer/attendance_roster.py`、`tests/unit/parsing/*`、`tests/unit/test_import_large_archive.py` | T00；与 T02 错峰 | 早停限额（不需先全量物化）、ZIP 按**实际字节**累计、兜底不重复解析、CSV 兜底保留 `_source_row`；`tracemalloc` 峰值有记录 |
| **T04** | 小程序异议修复 | `apps/wechat-miniapp/miniprogram/api/admin.js`、`api/record.js`、`pages/admin/index.js`、`pages/record/**`、`apps/wechat-miniapp/tests/*.test.mjs` | 无 | 不再请求 `/initial-review`；`desired_type`/`final_type` 四值可选；`node --test` 全绿；记录是否真机验证 |
| **T05** | 门禁与集成可执行性 | `tests/integration/conftest.py`、`inspection/repository.py`/`report/repository.py`/`report/source_revision.py`（仅方言分支）、4 个 `test_*_migration.py`、新增 `scripts/quality_gate.ps1`（或 `.sh`） | T00 | 一条命令产出红/绿；MySQL 缺失不再"跳过仍成功"；16 项失败逐条归类为风格债／期望过期／真实回归 |
| **T06** | 2 小时纠错闭环 | `inspection/models.py`、`inspection/service.py`（提交/新增 withdraw+revise）、`inspection/repository.py`、`inspection/scoped_router.py`、`inspection/router.py`、`migrations/versions/<新>`、**§6 扩散清单全部 14 处**、`tests/integration/test_inspection_submission.py` + 新测试文件 | **T00 → 设计批准 → T05（需真 MySQL 门禁）**；与 T01 注意 `identity` 耦合；与 T08 前端契约需先冻结 | 设计文档 §7 的 9 组矩阵全部在真 MySQL 通过；撤回不等于"正常"、不等于"没提交过" |
| **T07** | 范围守卫 fail-closed | `identity/query_scope.py`、新 `tests/unit/test_query_scope_coverage.py`、`tests/unit/test_campus_execution_regressions.py` | T01/T05 | 84 表逐张归类；新增未登记敏感表即测试失败；P1-5 重复防重红测给出"回归／期望过期"的定论 |
| **T08** | UI/UX | `apps/admin-web/**`（`InspectionsView.vue`、考勤与导入相关组件、删/接 `ReviewsView.vue`）、小程序页面 | T02/T06 契约稳定后 | 倒计时、撤回二次确认、修改预填、失败提示；Web E2E 与教师高频路径计时 |
| **T09**（新增，V2 未列） | 存量账号归属核实 | **只读**核查脚本 + 记录；不移动数据 | 无 | 产出"1 个已知待核实账号"的证据链（审计、原受派身份、时间），恢复动作单独提请 |

合并顺序：`T00 → T05 → (T01 ∥ T03 ∥ T04) → (T02 → T02b) → T06 → (T07 ∥ T08)`，`T09` 随时并行（只读）。

**共享文件单一 owner 规则**：`importer/service.py` 只允许 T02 或 T03 之一在同一时间窗内改动；`app/main.py`、`docs/openapi.json`、`navigation/workspaceNavigation.ts` 由当波次的**集成者**独占；T06 涉及 `inspection/service.py` 与迁移，禁止与其它包并行。

## 6. 每个 PR 的共同验收门禁（本轮实测基线，供"先红"对照）

在 `8da55fe` 上应当先复现的当前状态（本轮已在 `eb30c03` 实测，快进后需重跑）：

```powershell
# backend/
.\.venv\Scripts\python.exe -m pytest tests/unit -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests --no-cache
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m alembic heads
```

| 门禁 | `eb30c03` 实测 | 期望处置 |
| --- | --- | --- |
| `pytest tests/unit` | **16 failed / 813 passed / 6 skipped**（147.70 s） | T05 逐项归类；PR 不得让总数上升 |
| `ruff check app tests` | **500**（E501 388、F401 37、I001 34、E402 21、E702 5、F841 4…） | 风格债与回归分开计数；PR 只允许减少不允许新增（`6f4299b` 已示范"与 HEAD 比较无新增长行"的做法） |
| `mypy app` | **61 errors / 16 files** | 同上；本轮复核未发现由这些错误指示的确定运行崩溃 |
| `alembic heads` | 单头 `f26a1019s007` | T06 必须新增单一迁移并保持单头 |
| MySQL 集成 | 368 个用例在库不可用时**静默跳过、退出码 0** | T05 改为显式失败或显式开关 |
| CI | 无 `.github/` 等任何流水线 | 本轮以单命令门禁替代，不承诺自动化 |

每个 PR 必须同时交付：业务不变式清单、能复现问题的**失败测试**（修改前）、修改后的命令与真实输出、迁移影响与降级兼容、回滚方案、以及"未验证项"的明说。SQLite 或合成浏览器结果不得替代真 MySQL 锁语义与实机验收。

## 7. 本轮未做与需负责人指示的事

1. **未改动任何代码**，工作树仅新增本目录三份文档；未快进 HEAD（`eb30c03 → 8da55fe` 是纯快进、无本地提交，但是否执行由你决定）。
2. `submission.review` 从负责人默认集移除——**这是 §3 的建议，需要一句话确认**（DEC-02 只说"不因此获得"，未直接说"要删"）。
3. T02b 的"下线 `bulk`"需要确认旧调用面是否真的无人使用；本轮尚未穷举 `apps/` 内的调用（V2 §四也要求先调查）。
4. 生产已有 1 个账号的历史归属需要核实并决定是否逐项恢复（`6f4299b` 明确未处理）。V2 计划未包含这条，建议按 T09 单列，且恢复动作必须单独授权。
5. T06 含数据库迁移与考勤有效性语义变更，属于难以回滚的一类改动：**设计文档批准之前不动代码**。
