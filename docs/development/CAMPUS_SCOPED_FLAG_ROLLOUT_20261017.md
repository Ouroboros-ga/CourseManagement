# 学院范围与作息开关的生产启用联动改造清单

基线：`dev-main` @ `2e3e5cf`，2026-10-17 编制。

本清单只回答一件事：要把 `CAMPUS_BUSINESS_SCOPED_ENABLED` 和 `CAMPUS_SCHEDULING_ENABLED` 在生产打开，必须先完成哪些改造、必须核对哪些入口、必须留下什么回退。它不是排期，也不构成开启授权。

## 0. 已核实事实与未核实事实

已核实（本机对 `https://course.zsitai.xyz` 的无凭证探测，2026-10-17）：

| 探测 | 结果 | 读法 |
| --- | --- | --- |
| `GET /api/v1/colleges/1/academic/semesters/1/time-versions` | 403 `FORBIDDEN 学院作息和组织业务尚未启用` | `require_scheduling_enabled()` 拒绝 |
| `GET /api/v1/colleges/1/academic/semesters/1/school-time-templates` | 同上 403 | 同一守卫 |
| `GET /api/v1/school/academic/semesters/1/time-templates` | 同上 403 | `semester_defaults_router` 复用同一守卫 |
| `GET /api/v1/colleges/1/academic/semesters/1/time-versions/profiles` | 同上 403 | 同一守卫 |
| `GET /api/v1/colleges/1/capabilities`、`/colleges/1/academic/administrative-classes`、`/colleges/1/volunteer-groups`、`/colleges/1/time-templates` | 401 | 路由存在，守卫已通过，只差登录 |
| `POST /api/v1/colleges/1/academic/semesters/1/publication-preview`、`/publish`、`GET /api/v1/me/academic-notices` | 401 | 教务发布链在生产是开着的 |
| `GET /api/v1/academic/semesters/2/period-definitions` | 401 | 学校共享节次仍走旧路径且可用 |
| `GET /api/v1/colleges/1/academic/semesters/2/period-definitions` | 404 | 学院路径下没有这个资源，符合设计 |

判读口径：`401` 表示路由存在且开关已过；`403 学院作息和组织业务尚未启用` 来自 `backend/app/modules/academic/time_router.py:25`；`503 院级正式业务链尚未启用` 来自 `backend/app/modules/attendance/scoped_router.py:24`。以后复查用这套区分，不要只看状态码数字。

未核实：生产 `/etc/course-management/backend.env` 的实际内容（本轮没有登录服务器）；上面第 1 节的开关值取自 `docs/archive/2026-10-16/operations/R6_RELEASE_20261016.md:34` 与 `deploy/production/deploy_campus_p5_20261015.py:91-93`，与探测结果一致，但启用前要在服务器复核。

## 1. 开关现状与生效方式

- 文件：`/etc/course-management/backend.env`（服务读取）、`/etc/course-management/migration.env`（迁移读取）。两者由部署脚本一起改写，改完 `systemctl restart course-management`。
- 定义：`backend/app/core/config.py:28-36`。
- 当前：`CAMPUS_CONFIGURATION_ENABLED=true`、`CAMPUS_ACADEMIC_SCOPED_ENABLED=true`、`ACADEMIC_PUBLICATION_ENABLED=true`、`CAMPUS_BUSINESS_SCOPED_ENABLED=false`、`CAMPUS_SCHEDULING_ENABLED=false`。
- 粒度：全局布尔，**没有逐院灰度**。一旦为真，所有学院的旧全局业务入口同时失效。要做单院试点，得先补一个按学院生效的机制，这本身是一项改造，不是配置。

## 2. 依赖顺序

`require_scheduling_enabled()` 要求 scheduling、business_scoped、academic_scoped 三者同时为真，所以只有两条可执行顺序：

1. 先 `CAMPUS_BUSINESS_SCOPED_ENABLED=true`，观察一轮，再开 scheduling；
2. 或一次改两个、一次重启。

第 2 种把两个变量绑在一起，出问题无法归因，不建议。本清单按第 1 种组织。

## 3. 打开 CAMPUS_BUSINESS_SCOPED_ENABLED 之前必须完成的改造

### 3.1 后端：旧全局入口的拒绝点，逐个要有对应学院入口

这些位置在开关为真时会拒绝或改变行为，是"打开即断"的地方：

| 位置 | 行为 | 学院替代入口 | 状态 |
| --- | --- | --- | --- |
| `attendance/service.py:62-66` | 旧全局考勤列表/更正拒绝 | `attendance/scoped_router.py` | 已有 |
| `objection/service.py:310,332` | 旧全局异议审核拒绝，改判须同院 | `objection/scoped_router.py` | 已有 |
| `inspection/service.py:232,298,1321,1383,1945,2050` | 任务生成/名单/取消按学院收敛 | `inspection/scoped_router.py`（克隆旧路由，排除 `/me/*` 与志愿者自助 POST） | 已有，需核对排除集 |
| `importer/router.py:39` | 旧导入入口拒绝 | `importer/scoped_router.py` + `confirmation_router.py` | 已有 |
| `report/listing.py:78-85` | 周报按授权学院收敛 | `report/scoped_router.py` | 已有 |
| `audit/service.py:57` | 审计按学院收敛 | `audit/scoped_router.py` | 已有 |
| `identity/deps.py:90`、`identity/service.py:337` | 绑定管理须带学院范围 | `identity/scoped_router.py` | 已有 |
| `file/service.py:155` | 文件访问改走 `_can_access_scoped` | 无独立学院路由，URL 不变 | **待核** |
| `academic/management_router.py:13` | 学校学期归档本身要求 business_scoped 为真 | — | 打开后才可用 |
| `importer/service.py:467` | 课表节次上限 20 → 60 | — | 行为变更，需回归 |
| `inspection/course_occurrences.py:200` | 实际课次计算切学院作息 | — | 与 scheduling 联动 |

**待核项要落成结论**：`file` 模块没有学院列，`_can_access_scoped` 靠"文件挂接的业务对象的学院"推导。没有业务挂接的文件（导入上传的原始表、导出产物）在 scoped 模式下谁能读，要用真实账号跑一遍，不能靠读代码判定。

### 3.2 前端：`workspaceUrl()` 的路径白名单必须与后端学院路由集合一致

`apps/admin-web/src/api/workspaceHttp.ts:22-25` 用正则枚举"业务前缀"，命中才改写成 `/api/v1/colleges/{cid}/...`。白名单之外的调用在开关打开后仍然打旧全局路径，被后端拒绝。

当前白名单：`inspection-tasks`、`inspection-course-occurrences`、`inspection-volunteers`、`inspection/volunteers`、`assignments`、`assignment-change-requests`、`management/submissions`、`submissions`、`attendance`、`objections`、`statistics`、`reports`、`report-versions`、`imports`、`import-templates`、`audit-logs`、`submission-deadlines`、`role-assignment-targets`、`optional-permission-targets`、若干绑定令牌路径。

需要逐条判定"该不该改写"的调用（现在都不改写）：

- `api/files.ts:30,34` — `/api/v1/files`、`/api/v1/files/{id}/access`
- `api/accounts.ts:77-120,155,178` — `/teacher-accounts`、`/accounts/{id}/password-reset`、`/users/{id}/roles`、`/users/{id}/optional-permissions/{code}`
- `api/administrators.ts:7-16` — `/administrator-accounts*`
- `api/campusManagement.ts:15` — `/school/academic/semesters/{sid}/archive`
- `api/reports.ts:194` 之后的 `/school/statistics/semesters/...`
- `api/academic.ts:334,340` — `/academic/semesters/{sid}/reset-preview|reset-data`，被 `workspaceHttp.ts:19-20` 显式排除出 shared 白名单后改写成学院路径；学院侧要确认这两个路由真的存在（探测显示 `POST /colleges/1/academic/semesters/2/reset-data` 返回 401 而非 404/405，说明可达，但要在带凭证下核对语义）

判定规则要写进清单结论：账号与权限管理是"跨院人员主数据"还是"本院业务"，决定了它是否要带学院前缀。这个决定还没做。

### 3.3 前端：开关翻转瞬间的上下文竞态

`workspaceHttp.ts:27,29` 在 `runtime` 已加载但 `collegeId` 为空时抛 `ApiError(409 WORKSPACE_REQUIRED)`。开关打开后，`AppShell` 的待办徽标（`objections?final_status=PENDING&page_size=1`）从"不改写的旧全局路径"变成"必须改写的学院路径"，于是它从"永远能发"变成"依赖学院上下文已就绪"。

要做的是：给 `workspaceUrl` 的 `collegeId` 为空补一条可观测的降级（排队等上下文或直接跳过本轮读取），并在冷启动、切换学院、切换账号三种路径下验证徽标不再红。

### 3.4 已知代码阻断（打开前修掉，或明确接受）

来自 `docs/archive/2026-10-15/execution/CAMPUS_P1_P6_DESIGN_AUDIT_20261015.md` §3，当时都已用最小用例复现：

- A02 同一课次在两个组各生成一份任务：`inspection/group_sampling.py:286` 的 task_key 追加了 `:group:{gid}`，`inspection/service.py` 的 `_materialize` 按完整 key 去重。违反 PR-06/AC24。
- A03 人工确认规则未真正执行。
- A04 旧/通用生成入口没有统一要求执行组。
- A05 负责人字段没有形成组限定权限。
- A01 学籍交接列表被通用路由截获返回 422：`app/main.py` 先挂 `/colleges/{cid}/academic/{kind}/{rid}` 再挂交接别名。

A02/A03/A04 直接落在"打开 business_scoped 后才会走到的新链路"上，属于硬前置。A01、A05 是范围收敛正确性问题，同批处理更省一次回归。

## 4. 打开 CAMPUS_SCHEDULING_ENABLED 之前必须完成的改造

### 4.1 后端

- 受影响路由：`academic/time_router.py`（学院作息版本与方案）、`academic/semester_defaults_router.py`（学校默认模板）、`academic/school_time_router.py`（学院模板引用与更新提示）、`volunteer/management_router.py:24`、`volunteer/member_router.py:29`（志愿者组与成员）。后两个是"组织排班"，和作息共用同一个开关，不能只开一半。
- 受影响计算：`inspection/course_occurrences.py:200` 起，实际课次从固定节次表切到学院作息版本；`attendance` 的应到时间与截止随之变。
- 缺口（P3 未完成项）：完整作息模板/草稿/归档管理、时段自定义名称、教学班绑定多套方案的闭环页面、未来任务处置只返回 ID 集合没有处置界面。

### 4.2 前端

- 页签显隐与运行开关不一致：`views/AcademicView.vue:20` 只看 `academic.manage` 能力就渲染"作息与校历""发布给学生"，靠子组件的 `campusRuntime` 判断降级；`components/campus/CampusConfiguration.vue:55` 用 `:disabled="!schedulingReady"`。两种写法并存，审计 §1 已点名。统一成一处：由 `campusRuntime` 决定入口是否出现，能力只决定能否操作。
- 已经正确跟随开关的：`views/TaskListView.vue:547`（节次上限 6 与 60）、`components/academic/TeachingSchedule.vue:51`、`components/campus/CampusDimensions.vue:10`、`views/InspectionsView.vue:30-32`、`views/OrganizationsView.vue:27,34`、`views/SchoolView.vue:43`。这些不用动，但要一起回归。
- 作息数据在开关为假时全部 403：`api/collegeTime.ts`、`api/schoolTime.ts`、`api/timeProfiles.ts`、`api/schoolTimeTemplates.ts` 的失败目前只落到组件内的 error 条，没有统一的"功能未启用"识别。建议后端把 403 换成可判别的 code，前端据此显示说明而不是红色报错。

## 5. 数据前置（两个开关共用）

`docs/archive/2026-10-16/operations/R6_RELEASE_20261016.md:36` 记录的生产事实：

- 74 条旧任务缺负责学院
- 260 个教学班未分类，其中 15 个无学院
- 26 条课表无学院、70 门课程无学院
- 志愿者组织与成员均为 0
- 1 条资格归属未知

其中"教学班未分类"已有本机未上线的处理：`9cf47d5` 让网格课表导入可选课程类型，`backend/migrations/versions/f26a1017c001_backfill_teaching_class_regular_type.py` 按学院 `builtin_key='regular'` 回填。注意它把无学院的教学班兜底到 `college_id=1`，这个默认值是否适用于生产全部 15 条，要单独确认，不能靠迁移猜。

其余归属和成员数据是业务决定，不是代码问题：需要用户先给出"这些历史任务/课程/组织归哪个学院、是否补成员"的口径。

## 6. 建议执行顺序

1. 修前端空白页签缺陷（独立于开关，见第 8 节），并把页签显隐统一到 `campusRuntime`。
2. 定稿 3.2 的白名单判定：账号权限类、files、school 级路径各自要不要学院前缀；改 `workspaceHttp.ts` 并补单测。
3. 修 A02/A03/A04（A01/A05 同批），每项带能失败的回归用例。
4. 完成第 5 节的存量归属与分类，产出前后计数对比。
5. 在隔离库用 `deploy/production/rehearse_campus_completion.py`、`test_campus_candidate.py` 那套夹具做 business_scoped=true 的全链路预演，含旧入口拒绝、学院入口可达、文件访问、报表分母。
6. 决定是否需要逐院灰度；不需要则记录"全局切换 + 回退即改回 false"作为验收口径。
7. 生产开 `CAMPUS_BUSINESS_SCOPED_ENABLED`，观察一轮。
8. 补 4.1 的作息缺口，再开 `CAMPUS_SCHEDULING_ENABLED`。

## 7. 回退

- 两个开关改回 `false` 并重启即恢复旧全局入口；部署脚本已把改前的 env 落盘为 `backend.env.before`（`deploy/production/deploy_campus_p5_20261015.py:124`）。
- 开关为真期间写入的 `college_id`、`college_id_snapshot`、作息版本、发布版本是**业务事实，回退不会清除**。回退只恢复入口，不恢复数据。
- 回退前必须备份：沿用 `deploy/production/backup.sh` 并在发布记录里留 SHA-256 核对结果。

## 8. 与开关无关的那个缺陷

"作息与校历""发布给学生"两个页签整块空白，不是开关造成的：开关为假时 `AcademicView.vue:62` 应显示说明条，而"发布给学生"的后端本来就已启用。`教学班与分类`/`课程类型` 正常说明 `CampusWorkspace` 的 `college` 已就绪。当前最可疑的是 `views/AcademicView.vue:57` 的内层 `<Transition name="tab-fade" mode="out-in">`：`ScopedAcademicBrowser` 和 `CourseTypeManager` 都是单根，而 `key="time"` 分支的 `<div>` 与 `AcademicPublication` 在切换时若未触发 `transitionend`，`mode="out-in"` 会一直不挂载新内容，表现就是纯空白。

定位方法已给出（读 `.tab-stage` 的 `innerHTML.length` 与 `opacity`）。确认前不改代码。
