# Web 管理端所需后端能力补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 执行说明：以上技能若在当前环境不可用，按本计划逐项执行，不安装框架、不假称已调用技能。本文现按本轮代码与验收结果更新；测试由用户已授权的 Sol medium 子 Agent 执行，主 Agent 负责设计、修复与复核。未完成的上线或后续产品项保留未勾选。

**Goal:** 优先补齐学院级查课系统的管理权限、人员生命周期、按周精确选课次及下发能力，并修复管理审核读取、班级周报范围和周报源修订问题；之后完成课程导出、周报发现和审计读取，使 Web 管理端能完成真实业务闭环。

**Architecture:** 保持 FastAPI 模块化单体与 MySQL。复用现有任务生成器、排班器、版本校验和权限解析，新增小型查询/编排服务；一键下发采用现有生成与自动分配接口的两阶段组合，不引入后台队列、独立 worker 或发布审批状态机。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + MySQL + openpyxl；管理端继续 Vue 3 + TypeScript，小程序继续 WXML/JS/WXSS。

## Global Constraints

- 约 900 人的单学院系统；负责人覆盖全部年级，不宣称已有多学院隔离。
- 体育课不生成查课任务，但参与志愿者本人上课冲突；补课采用来源教学周和星期。
- 志愿者周上限按 ISO 自然周累计，手动改派也不能绕过冲突、资格和次数约束。
- 允许逾期补交，截止时未执行的考核事实不可被补交、取消或恢复擦除。
- 人工原因统一选填，保留操作人、时间、变更和版本审计；系统失败原因码必须保留。
- ID 对外使用字符串，沿用现有请求命名和响应封装，版本过期返回 409；无权查看具体资源不泄漏存在性。
- 不物理删除已有业务历史、考勤、周报版本或账号审计。本文“删除教师/学生”采用停用及退出有效业务范围的实现建议。
- 不增加每次下载重新鉴权、即时撤销已签发下载链接的机制；沿用现有短期文件访问方式。
- 全部数据库测试在显式配置的隔离 `_test` 数据库执行，不读取或修改正式业务数据。生产更新单独按发布流程执行。
- 当前工作区已有其他未提交修改。每阶段只核对本阶段差异，不重置、不批量提交、不自动推送。

## 1. 代码现状与本轮范围

基于 2026-09-29 本地代码核对，不代表部署环境。A–F 对应接口代码已落地，OpenAPI 已由本地路由定义重导；隔离 MySQL 全量回归 353 passed / 0 failed / 0 skipped（1589.07 秒，6 条警告），之后另有边界专项 11 项通过（前 10 项 44.91 秒、双管理员精确生成 1 项 32.29 秒）。数据库 seed 双次幂等、审计索引迁移复验、真实规模与学校环境验收仍待最终记录。原清单采用“先 RED 后实现”的施工顺序，本轮并未对每项完整保留该过程证据；下方改为当前可验收功能断言，不追认历史 RED。固定格式 Word 仍属后续交付。

| 功能 | 当前证据 | 本轮交付 |
| --- | --- | --- |
| 负责人权限 | 两项可选授权；有效学生绑定；排班、课表导入导出和学院周报为默认能力 | 代码已落地，待 seed 与权限回归最终验收 |
| 教师账号 | 独立 `/teacher-accounts` 创建、停用、重置口令与本人改密 | 仅超管可管理教师；后端已验收 |
| 学生管理 | POST/PATCH 沿用；停用联动解绑、撤权、会话与未来受派 | 后端已验收，待前端联调 |
| 课程任务生成 | 候选课次查询和逐课次选择已落地；返回 `selection_scope` 与修订 | 双管理员同课次并发专项已通过，待最终联调 |
| 生成结果与分配 | 返回所选 `tasks`、`assignable_task_ids`；自动排班及人工改派；恢复保留历史受派 | 待端到端验收 |
| 管理审核 | review 写入口及独立管理列表、详情 GET；本人读取入口保持本人范围 | 后端专项 49 项已通过，待管理端联调 |
| 周报 | `GET /reports` 发现主记录；仅学院考勤汇总，`CLASS` 请求 422 | 代码已落地，固定格式 Word 待后续实现 |
| 课程导出 | 有界 XLSX 导出；基础模型无任课教师字段，教师列为空 | 后端已验收，待前端联调 |
| 审计 | 超管 `GET /audit-logs` 与详情，字段白名单脱敏 | 后端已验收，待前端联调 |
| 原因选填 | 上轮已调整七类 schema、小程序及测试 | 本轮集成验收，不重复实现 |

## 2. 目标权限与产品决策

以下基线已进入本地代码；数据库角色映射仍须经受控 seed 同步及隔离库验收，不把本地常量等同于生产已生效。

| 操作者 | 目标能力 | 明确边界 |
| --- | --- | --- |
| 超管 | 新建/停用教师账号，现有角色与平台管理 | 教师历史保留；禁止停用最后一个有效超管 |
| 教师 | 学生新增/修改/停用；给已绑定学生账号授予或撤销负责人 | 不新增教师，不授予教师角色；不替学生提交业务事实 |
| 学生工作负责人 | 全年级课表查询、课程导入导出、生成/取消/恢复任务、自动排班与手动改派、周报生成/读取/下载 | 不默认赋予教师账号管理、学生维护、考勤更正、提交审核、终审、截止修改 |
| 负责人可选项 | statistics.read、objection.initial_review | 默认关闭，教师逐人设置；周报按最新需求改为默认能力，不再作为可选项 |

负责人复用该学生原账号，授予 STUDENT_AFFAIRS_MANAGER，保留学生身份；不另造脱离学生的负责人账号。新增负责人须验证有效学生绑定，解绑/学生停用后撤销负责人及其个人可选授权；不能继续凭旧会话保有管理能力。已有不满足绑定条件的负责人先列差异供迁移处理，不静默破坏其他账号角色。

课程导入不得通过授予宽泛 academic.manage 顺带开放校历、学期维护。新增 `course_schedule.import`、`course_schedule.export`，负责人获得 academic.read、volunteer.read、import.execute 及上述两项；导入服务按 target 再核权，只放行现有课表导入目标。名单、资格等其他导入仍要求原目标权限。report.read/report.generate 默认授权只提供周报能力，不附带 statistics.read。

## 3. 阶段 A：权限基线和数据库同步（本地后端验收通过）

**Files:** 修改 backend/app/core/permissions.py、modules/identity/{policy,seed,service}.py、modules/importer/service.py、modules/report/permissions.py；测试 tests/unit/test_permission_policy.py、tests/integration/{test_admin_rbac,test_seed,test_importer}.py；文档 docs/PERMISSIONS.md、PERMISSIONS_IMPLEMENTATION.md、ADMIN_WEB_ROLE_UI_DESIGN.md。

- [x] 当前权限回归断言：负责人可生成、取消与排班，课表导入独立于名单/资格导入，周报默认可用而统计默认关闭；教师不能建教师，未绑定有效学生不能获得负责人。见 `test_admin_rbac.py`、`test_importer.py`、`test_account_management.py`。
- [x] 本地默认矩阵与逐目标导入授权已更新；个人可选项为两项，旧 `report.read` 个人授权的清理逻辑已落地。
- [x] 提供受控同步命令的差异预览；在隔离库运行现有 seed 同步机制，验证既有角色新增/删除权限映射，连续运行两次第二次无变化。不能仅修改 Python 常量。
- [x] 当前测试覆盖权限撤销、学生解绑/停用联动、会话失效与版本冲突；负责人须有效学生绑定。
- [x] seed 幂等、迁移记录及阶段审查通过；受控旧 report.read 个人授权首次清理并追加审计，第二次同步 changed=False。

**Produces:** 稳定权限集合；课程导入目标白名单；负责人身份绑定规则。后续所有新端点必须消费这里的权限，不能在路由另写角色名单绕过 Service。

## 4. 阶段 B：精确选择本周课次（本地后端验收通过）

**Implemented in:** backend/app/modules/inspection/{course_occurrences,schemas,service,router}.py；专项测试见 backend/tests/integration/{test_inspection_generate,test_exact_generation_concurrency,test_management_completion_edges}.py。以下按本轮隔离测试结果记录。

**Interfaces:** 新增 `GET /api/v1/inspection-course-occurrences`，要求 inspection.generate；查询 semester_id、date_from、date_to、teaching_class_ids、page、page_size。日期跨度最多 31 天、每页最多 100 条；稳定排序为日期、节次、课表 ID。

返回 `{items,page,page_size,total,selection_revision,selection_scope}`；条目包含 course_schedule_id、inspection_date、start_period、end_period、教学班/课程/教室展示值、existing_task_id、existing_task_status、selectable、disabled_reason。体育/停课等不可查项不进入可选集合；已取消项可展示但禁用，并提示显式恢复。页面行政班筛选先通过教学班关联查询转成教学班集合，不能把行政班 ID 当教学班 ID。

扩展现有 preview/generate 请求，新增 `occurrences`：

```json
{
  "semester_id": "1",
  "inspection_type": "COURSE",
  "selection_revision": "服务端返回的范围修订摘要",
  "selection_scope": {
    "date_from": "2026-09-28", "date_to": "2026-09-30",
    "teaching_class_ids": [101, 102], "require_photo": false
  },
  "occurrences": [
    {"course_schedule_id": "101", "inspection_date": "2026-09-28"},
    {"course_schedule_id": "102", "inspection_date": "2026-09-30"}
  ],
  "reason": ""
}
```

精确模式与旧 week_nos/date_from/date_to/teaching_class_ids 生成模式互斥；旧客户端契约继续工作。occurrences 最多 500 条且不能为空；同课次去重；服务端按课表重新推导节次、课程、名单、校历与体育排除，禁止接收客户端人数/课程名作为生成依据。

selection_revision 对已限定查询范围内的候选数据、校历、节次、名单及照片要求等影响生成的输入计算稳定摘要；查询范围标识随摘要返回并在提交时验证，不能只摘要可见的一页。课表或名单改变后返回 409 SELECTION_STALE，要求刷新预览，不静默换课。生成与相关写路径沿用一致的学期锁顺序；在锁内重读并比较，避免检查后又变化。

- [x] `test_inspection_generate.py` 覆盖跨页精确选择、只生成选中课次、幂等返回同一任务 ID、旧模式兼容及名单变更后的 409；`test_management_completion_edges.py` 覆盖伪造日期 422。
- [x] 候选查询与生成复用既有课程计划构建，校历、体育排除、数量限制和 `selection_scope` 在服务端复核。
- [x] 两名管理员并发生成同一课次的专项用例已通过，见 `tests/integration/test_exact_generation_concurrency.py`；精确模式并发验收关闭。

**Produces:** 精确模式只生成用户确认的课次。不得在生成后用“取消多余任务”模拟精确选择。

## 5. 阶段 C：一键下发与手动调整闭环（本地后端验收通过）

**Implemented in:** inspection/{schemas,repository,service,router,restore_service}.py；生成结果组装位于 `service.py`，安全恢复已接入。以下按本轮隔离测试结果记录。

扩展 GenerateResultResponse，保留原字段，增加 `tasks:[{task_id,created,status,assignment_id}]` 和 `assignable_task_ids`。列表必须覆盖此次选择对应的所有任务；取消、已完成、待审核或已分配的任务不进入 assignable_task_ids。旧模式也返回有界完整结果；若现有生成上限更大，前端按自动排班 500 条上限拆批。

一键下发采用 `preview → generate → POST /assignments/auto`，自动分配只传 generate 返回的 assignable_task_ids，禁止回退为“全周排班”。不新增 dispatch 数据表和工作队列。重复 generate 按 task_key 返回相同任务，重复 auto 跳过已受派任务，不挪动别人已有安排；失败重试重新生成/查询对应任务以恢复精确 ID 集合。

前端呈现：生成失败、已生成待分配、部分分配、全部分配四种结果；普通排不下仍返回明确 unassigned 原因，不包装成系统 500。断网不推断失败，重试可恢复现状。当前受派即小程序可见，无额外发布/通知承诺。

手动指定/更换复用现有 PUT assignment。新增 `POST /inspection-tasks/{id}/restore`，复用 inspection.generate 权限并校验 lock_version；仅允许未开始且无提交/正式考勤/截止考核事实的已取消任务恢复，重检课表仍有效、名单及截止快照是否兼容，不兼容返回 409 要求重新规划。恢复保留取消审计并设为未分配，旧 assignment 标记历史失效，不能悄悄恢复旧志愿者；已有截止考核的任务不开放恢复。

- [x] generate 返回本次选择的任务 ID 和 `assignable_task_ids`；幂等生成不复活取消任务，自动排班只消费明确的任务 ID。见 `test_inspection_generate.py`、`test_inspection_assignment.py`。
- [x] 现有排班集成回归覆盖周上限、冲突和版本校验；撤销 assignment 保留历史，见 `test_assignment_revocation.py`。
- [x] restore 的安全恢复与五类拒绝边界已由 `test_inspection_generate.py` 和 `test_management_completion_edges.py` 验证，旧受派保留历史且恢复后未分配。
- [x] 冻结真实资料离线复跑：9 月 28–30 日及 10 月 12–18 日，共 10 个检查日；10 月 1–7 日不排。115 个任务、75 已分配、40 未分配，独立核验约束违反 0、残留可直接分配任务 0；40 个未分配原因全部核对，9 次重复结果一致。这是规划器验收，不是 HTTP 压测。
- [x] 验收每个选中课次均有“已分配、已存在、未分配及原因”结果，未选中任务完全不受本次下发影响。

## 6. 阶段 D：教师账号与学生生命周期（本地后端验收通过）

**Implemented in:** identity/{account_router,account_schemas,account_service,service}.py、academic/{service,student_lifecycle}.py；学生停用联动保留历史。以下按本轮隔离测试结果记录。

拟定端点：

| 方法与路径（/api/v1 前缀） | 请求/返回重点 | 权限 |
| --- | --- | --- |
| GET /teacher-accounts | 分页、姓名/用户名/status；返回版本，绝不返回 password_hash | account.read |
| POST /teacher-accounts | username、display_name、initial_password；创建账号和教师角色同事务，201 | account.manage + 超管角色约束 |
| PATCH /teacher-accounts/{id} | display_name、status、lock_version、reason? | 同上；停用为删除语义 |
| POST /teacher-accounts/{id}/password-reset | new_password、lock_version、reason?；撤销全部会话，204 | 同上 |
| POST /me/password-change | current_password、new_password；只适用于密码账号，撤销旧会话，204 | 有效登录 |

口令使用现有 Argon2id，初始口令不写审计、不在列表或创建响应回显；重用现有口令验证约束。重复用户名 409，拒绝对非教师目标使用教师专用端点；兼任超管的账号停用受最后超管保护，保护检查需锁定稳定管理对象避免并发互停绕过。

学生沿用 POST/PATCH /students，停用入口复用已有 status 字段及其现有枚举约束，不新增物理 DELETE；停用事务使绑定业务身份/负责人授权和有效志愿者资格失效、撤销会话、保留历史；未来未执行受派关系应撤销并变成待重排，不能删除截止考核事实。停用预览或响应返回受影响待重排任务数量，供管理端提示。角色撤销只是取消负责人职责，不能顺带停用学生账号。

- [x] `test_account_management.py` 覆盖超管创建教师、重复用户名、教师拒绝、停用后 access/refresh 失效、版本冲突、本人改密及重置密码。
- [x] 学生停用联动撤销负责人身份、资格、会话和未来无事实受派；历史受派与事实保留，停用/排班并发专项已通过。
- [x] 审计敏感字段、最后超管保护及学生停用/负责人排班并发专项通过，阶段 D 后端验收完成。

## 7. 阶段 E：管理审核、课程导出、周报发现

每个子项独立交付，不等待所有子项一起合并。

### E1 管理提交查询（已实现，待管理端联调）

**Implemented in:** inspection/{router,schemas,repository,service}.py；tests/integration/test_management_submissions.py。

已新增 GET /management/submissions 和 GET /management/submissions/{id}，守卫 submission.review；列表按学期、日期范围、任务、状态筛选并稳定分页。详情返回任务/名单版本、异常项、照片文件 ID、提交版本和当前审核状态；不返回存储密钥或长期签名链接。原 /submissions/{id} 仍为本人语义。当前负责人默认不取得此权限。新增 6 项集成用例与已有提交审核用例合计 49 项通过；这只证明隔离测试环境的后端行为，管理端联调尚未完成。

- [x] 用教师看他人待审提交、志愿者只能看本人、负责人默认拒绝的测试覆盖权限范围。
- [x] 实现数据库范围过滤，详情/列表统一授权；避免每个列表行单独查询名单或文件。
- [x] 验证已被另一人审核后提交旧版本返回 409，读列表不改变状态；文档记录照片访问既有规则。

### E2 课程导出（接口及隔离回归已验证，待最终联调）

**Implemented in:** academic/{export_router,export_service}.py；专项测试见 backend/tests/integration/test_course_schedule_export.py。

已新增 GET /course-schedules/export，要求 course_schedule.export，参数 semester_id、teaching_class_ids；返回 XLSX，固定列为教学班、课程、教师、周次、星期、开始节次、结束节次、教室。当前基础数据模型没有任课教师字段，教师列为空，不能伪造教师名。只导出有权限的课表，不顺带导出学生个人信息；上限 10000 行，超过返回 422 建议缩小范围。

- [x] 权限拒绝、限定班级、空结果、超过 10000 行上限及公式样式文本已有单元和隔离集成断言，见 `tests/unit/test_course_schedule_export.py`、`tests/integration/test_course_schedule_export.py`。
- [x] 使用 `openpyxl` 的 `write_only` 模式有界生成；公式样式文本强制为字符串，测试回读 XLSX 核对表头、内容和单元格类型。
- [x] 课程导入保留既有预览和确认两步；其既有测试随本轮 MySQL 全量回归通过。
- [ ] 在 Web 联调中核对有权限教学班的筛选和浏览器下载体验；不将空白教师列当作已具备教师数据。

### E3 周报主记录及版本一致性（现有考勤报表链路已通过隔离回归，Word 待后续交付）

**Implemented in:** report/{listing,router,schemas,repository,version_service}.py；`GET /reports` 由 `listing.py` 实现并在路由接入，相关专项测试见 `backend/tests/integration/test_management_completion_edges.py`、`test_report_source_revision.py`、`test_report_version.py` 及 `backend/tests/unit/test_report_listing.py`。

已新增 GET /reports，参数 semester_id、week_no、page、page_size，仅学院范围；返回 report_id、week_no、latest_version_id、latest_version_no、latest_version_created_at、source_changed。这里“最终版本修改时间”定义为最新不可变版本生成时间，不伪造文件修改时间。周报内容仅包含考勤汇总，不写任务总数、未完成或逾期统计。固定格式 Word 文档为后续交付，模板及下载契约另行明确；现有版本列表和下载接口继续使用，不提供文件上传覆盖。

- [x] 负责人默认可读取和生成、无权限用户拒绝、列表只返回最新发布版本及源修订状态，已由报表列表、版本与权限集成用例覆盖。
- [x] 审核生成考勤、应到调整、考勤更正、异议终审有效改判及无效改判不递增的源修订路径，已由 `tests/integration/test_report_source_revision.py` 覆盖；任务状态不作为考勤汇总修订触发条件。
- [x] 不可变版本递增、并发生成版本号不重复、旧版本仍可下载、文件保存失败标记失败且不留下可下载的假成功版本，已由 `tests/integration/test_report_version.py` 覆盖。
- [ ] 固定格式 Word 模板、生成和下载契约尚未实现，作为后续独立交付；现有 JSON/XLSX 考勤汇总继续可用。

## 8. 阶段 F：审计读取已落地，上线前验收待完成

**Implemented in:** audit/{router,schemas,repository,service}.py 并在 app/main.py 注册；相关文档与 OpenAPI 已按本地路由更新。以下上线验收项尚待最终核对。

新增 GET /audit-logs 与 GET /audit-logs/{id}，仅 audit.read；限定时间窗口最多 31 天，支持操作者/动作/资源筛选，page_size 最多 100。before/after 输出采用字段白名单，不输出密码、token、证明正文。按实测查询计划为 created_at/id 或资源查询加必要索引，不给每列机械建索引。

通用 system_config 的在线写入不进入本轮：日截止已有接口，照片与证明保留期继续分开配置；校历、节次复用已有接口。Web 不展示不可保存的假配置表单。逐班周报和每班自动抽 N 次不是基础管理链路的前置条件；当前仅有学院周报，`CLASS` 请求返回 422。

- [x] 教师/负责人拒绝、超管时间窗口/分页筛选与字段白名单脱敏已有单元和隔离集成测试，见 `tests/unit/test_audit_read.py`、`tests/integration/test_audit_read.py`。
- [x] 隔离 MySQL 后端全量回归 353 通过、0 失败、0 跳过、6 warnings（1589.07 秒）；之后恢复、名单保护、学生停用并发、报表读取、伪造日期及双管理员精确生成等 11 项边界测试通过。小程序独立 Node 测试 42 通过。以上为本轮测试记录，不等于浏览器端端到端验收。
- [x] `pytest` 全量、单元测试 163 项、`mypy app` 114 个源码文件、`ruff check app tests` 已分别通过。全量回归之后新增审计索引迁移，其升级/回退和查询计划仍待单独复验；测试仅连接隔离数据库，不连接业务库执行迁移。
- [ ] 在 2 核 2GB 验收环境用 900 人规模数据、50 并发读请求及 10 并发写请求进行基线测量；初始目标查询 p95 < 1 秒、写入 p95 < 2 秒、500 课次预览/生成/排班各 < 10 秒、进程与数据库无 OOM。目标未达先分析 SQL/内存/锁等待，不直接增加框架；这些是验收目标，不是已有性能结论。
- [x] 后端组合回归覆盖重复请求、权限撤销、过期预览、节假日/补课、体育排除、截止前后取消与补交；并发专项覆盖无重复生成及学生停用锁序。真实浏览器断网恢复体验随 Web 联调验收。
- [x] 核对默认 seed 连续执行两次的幂等性，以及审计 `(created_at, id)` 索引迁移 `d42a9e6c71b0` 的升级/回退、metadata 和执行计划；该索引源于 5010 行审计数据上原查询出现 ALL + filesort 的实测。最终发布门禁另行记录。
- [x] 已同步 OpenAPI（92 paths/112 operations）、权限矩阵、三角色接口示例及 Web 联调清单；Web 页面本身仍须另行接入与验收。

## 9. 交付顺序与验收出口

A 权限 → D 人员管理 → B 精确课次 → C 下发与调整，是当前优先的管理基础链路；这些接口及 E1 审核读取、E2 导出、E3 周报发现、F 审计读取已在本地代码落地，并通过本轮隔离 MySQL 全量回归；双管理员精确生成并发另经专项通过。seed 幂等和索引迁移复验已通过；容量与 Web 联调仍待验收。固定格式 Word 另行交付。

每阶段以可复核的功能断言、隔离回归、文件差异、文档/OpenAPI 和验收记录关闭。原计划要求“先 RED 后实现”，但历史实施过程未完整留存失败先行证据，不能追认该过程；上方已完成项仅表示当前代码与回归断言成立。

本轮不承诺工期；完成 A–C 后即可交付“本周选择这些课次，一键下发，排不下可手调”的核心链路，完成 D–F 后再称 Web 管理端所需后端能力补齐。


## 10. 关键契约测试示例与计划自检

以下断言作为对应集成用例的验收核心，测试使用现有教师/负责人、学期与课表夹具建立输入，不连接业务库。`response` 是 generate 的 HTTP 响应，`selected_schedule_ids` 是该用例准备的两条课表主键；另行 GET 每个任务核对精确日期。

```python
assert response.status_code == 200
result = response.json()["data"]
assert result["created"] == 2
assert len(result["tasks"]) == 2
assert len(set(result["assignable_task_ids"])) == 2
for item in result["tasks"]:
    detail = client.get(f"/api/v1/inspection-tasks/{item['task_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["course_schedule_id"] in selected_schedule_ids
```

该示例沿用当前 generate 的 200 响应；不能将数量断言替代数据范围断言。两个课次位于同一教学班但不同日期时，还必须断言实际日期集合等于选中日期集合。重复生成时 created=0、existed=2，返回相同任务 ID。

自检结果：原因选填、负责人排课和手动调整、课程导入导出、周报、超管新增/停用教师、教师管理学生均有对应代码；A–F 相关后端用例已纳入本轮隔离 MySQL 353 项全量回归。追加 11 项边界测试均通过；新增审计索引后另通过 2 项迁移与 2 项审计查询专项。seed 幂等及执行计划已复核；容量、浏览器联调和上线事项仍待完成。未重写现有排班求解器，也未新增 worker 或消息队列；未部署。

## 11. 本轮验收结论

本地后端基础管理能力已交付：单元 163 项、MySQL 全量 353 项、全量后追加边界 11 项、小程序 42 项通过；Ruff 通过，mypy 检查 114 个源文件通过。全量后仅增加审计时间分页索引，并单独验证新 head `d42a9e6c71b0` 的升级/回退、metadata 一致性及审计接口。约 5000 行审计查询由 ALL/filesort 改为 range/索引倒序扫描；这不是 2 核 2GB 容量验收结果。详细证据见 [发布验收记录](./RELEASE_ACCEPTANCE.md)。

正式更新数据库时须按发布流程应用 Alembic，并先用 seed `--dry-run` 核对差异再同步角色权限；遗留无有效学生绑定的负责人须人工核对。本轮仅验证隔离库，没有迁移业务库、提交或部署。
