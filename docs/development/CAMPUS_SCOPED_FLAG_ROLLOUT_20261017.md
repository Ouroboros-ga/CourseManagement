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

- ~~页签显隐与运行开关不一致：`views/AcademicView.vue` 只看 `academic.manage` 能力就渲染"作息与校历""发布给学生"，靠子组件的 `campusRuntime` 判断降级；`components/campus/CampusConfiguration.vue:55` 用 `:disabled="!schedulingReady"`。两种写法并存，审计 §1 已点名。~~ 已统一：`AcademicView` 的本院作息页签改由 `campusRuntime.business_scoped && campusRuntime.scheduling` 决定是否出现，页签存在即可用，不再渲染只能读提示的空页签；`CampusConfiguration.vue` 整页无任何路由引用，已删除（见第 9 节）。剩余同类写法在 `views/InspectionsView.vue:32,34,37`（`sampling`/`deadlines`/`impacts` 页签存在但内容降级为提示），本轮未动。
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

1. ~~修前端空白页签缺陷（独立于开关，见第 8 节），并把页签显隐统一到 `campusRuntime`。~~ 空白缺陷已定位为 out-in 过渡多根子组件并修复（`19438bb`）；教务资料的本院作息页签显隐已统一到 `campusRuntime`，作息入口的作用域拆分见第 9 节；`InspectionsView` 的页签显隐仍按旧写法。
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

## 8. 页签整块空白（已定位并修复，与开关无关）

"作息与校历""发布给学生"整块空白不是开关造成的：开关为假时 `AcademicView.vue:62` 本应显示说明条，而"发布给学生"的后端本来就已启用。

根因是 `<Transition mode="out-in">` 的子组件多根：`ScopedAcademicBrowser` 和 `CourseTypeManager` 渲染成 fragment，Vue 不挂载过渡钩子，`afterLeave` 永不触发，`isLeaving` 永久为真，Transition 之后只返回空占位节点。同一缺陷在 `SchoolView` 的 `OwnershipReconciliation` 上可稳定复现（切到"存量归属核对"再切回即空白）。

已按调用点包单元素根的方式修复，并加静态守卫 `apps/admin-web/tests/transition-root-invariant.test.mjs` 遍历全部 `mode="out-in"` Transition。证据见[过渡单根修复发布记录](../archive/2026-10-17/operations/TRANSITION_ROOT_RELEASE_20261017.md)。

仍待处理：`GroupManager`、`ImportHome` 等组件本身仍是多根，目前只靠调用点包裹规避；新页面把它们直接放进 out-in Transition 会重新触发同一缺陷，由上述测试拦截。`CampusAdministration` 与 `TeacherCollegeEditor` 已在第 9 节的重排中改为单根 `<section>`。

## 9. 作息入口与学院管理页的作用域拆分（2026-10-17）

用户报告"学校与学院管理"页逻辑混乱：同屏出现两个学院选择器，学校作息模板编辑器挂在"学院、教师与授权"页签里，而作息入口在"教务资料→作息与校历""学期与平台设置"也各有一处。

先纠正一个前提：这三处**不是同一份数据**，不能简单当成冗余删掉。

| 入口 | 实际编辑的对象 | 后端 | 生产可用 |
| --- | --- | --- | --- |
| 学期与平台设置 → 节次作息时间表 | 当前全校学期的节次定义 | `GET/PUT /api/v1/academic/semesters/{sid}/period-definitions/{no}` | 是 |
| 学期与平台设置 → 学校作息模板（本次移入） | 学院可引用的全校可复用模板及不可变版本 | `/api/v1/schools/{sid}/time-templates` | 否（写路径要求超管，消费端受 scheduling 开关） |
| 教务资料 → 本院作息与校历 | 学院自己的作息版本、校历与网格映射 | `/api/v1/colleges/{cid}/academic/semesters/{sid}/time-versions` | 否（`CAMPUS_SCHEDULING_ENABLED=false`） |

本次改动：

- `CampusAdministration.vue` 去掉 `SchoolTimeTemplates` 与"当前学院：改名/停用"两块，只剩学院结构创建与授权/任命；根节点改为单 `<section>`。
- `SchoolTimeTemplates.vue` 与 `TimePeriodEditor.vue` 移入 `SettingsView.vue` 第四个页签"学校作息模板"，由 `hasAnyRole('SUPER_ADMIN') && campusRuntime.scheduling` 控制显隐。**不能直接删除**：`TimeProfiles.vue` 的"从学校模板导入"（`importTemplateDraft`、`listTemplateUpdates`）是它的唯一消费端，删掉编辑入口会让 P3 开启后模板列表恒为空。
- `AcademicView.vue` 的本院作息页签改由 `campusRuntime.business_scoped && campusRuntime.scheduling` 决定出现，页签名改为"本院作息与校历"与全校级区分；删掉原先只能读提示的降级条。
- `SchoolView.vue` 把"管理对象"提升为页面上方上下文条，选择器、状态标签、重命名、停用/恢复集中在此，并明确说明它不切换当前业务工作区。全页只剩这一个学院选择器。
- `TeacherCollegeEditor.vue` 不再显示裸 `college_id`，改显示"现在的归属 / 已归属「本院」"，按钮带目标学院名，已绑定时禁用；`handoff` 由原来的 `[object Object]` 改为可读摘要。
- `CollegeGrantEditor.vue` 把"未选择的资源不开放""受限授权暂不支持导入、报表和全院教学数据动作"从段落改为随"资源范围"选择实时变化的字段提示，并给范围与动作选择器加占位说明。
- 删除 `components/campus/CampusConfiguration.vue`：它不在任何路由里（`/dashboard/campus` 渲染的是 `CampusView.vue` 的迁移说明页），却是上述三处作息重叠里的第三处，保留会误导后续改动。

静态守卫：`apps/admin-web/tests/college-admin-scope.test.mjs` 固定这五条边界（学院与授权组件不含作息与改名、全页仅一个学院选择器、作息页签跟随开关、模板编辑在设置页且限超管、已删除页面不被接回路由）。

未做：`InspectionsView` 的 `sampling`/`deadlines`/`impacts` 仍是"页签存在但内容降级为提示"的旧写法；本次未动，避免把开关改造扩到查课页。

本节改动已上线，证据与回退见[学院管理与作息入口作用域拆分发布记录](../archive/2026-10-17/operations/COLLEGE_ADMIN_SCOPE_RELEASE_20261017.md)。

### 9.1 全校节次作息作为唯一入口，当前只有超管能写（已用 TestClient 核实）

生产 `CAMPUS_ACADEMIC_SCOPED_ENABLED` 已为 `true`，`guard_legacy_academic`（`app/modules/academic/router.py:44`）因此已经生效：`/academic/semesters/{sid}/period-definitions` 与 `/academic/semesters/{sid}/calendar-overrides` 的读在 `shared_reads` 内放行，写在 `shared_writes` 内额外要求 `"SUPER_ADMIN" in list_role_codes(actor)`。前端 `workspaceUrl()` 把 `/academic/semesters*` 判为 shared 不改写，两端一致，所以这不是缺陷而是现行策略；问题在于它让"唯一作息入口"只对一类账号可用。

本机 sqlite + TestClient 实测（同一账号只换 CurrentUser，服务内纵深重读固定为持有 `academic.manage`）：

| 账号 | GET period-definitions | PUT period-definitions/1 | POST calendar-overrides |
| --- | --- | --- | --- |
| TEACHER_ADMIN（持 `academic.manage`） | 200 | **403 FORBIDDEN** | **403 FORBIDDEN** |
| SUPER_ADMIN | 200 | 200 | — |

403 文案是"请使用包含学院工作区的基础数据入口"。节次与校历是全校共享资源，学院侧没有对应写入口（`scoped_router.py` 的 `ResourceKind` 不含 period-definitions），所以这句话对教师管理员是一个无法执行的指引；页面上的"一键恢复高校标准作息"会连发 12 个 PUT，全部落到同一条 403。

待定口径（择一，属产品决定）：

1. 把"学期与平台设置"的节次与校历写入定为超管职责：前端按 `SUPER_ADMIN` 隐藏编辑动作或整页，后端文案改为"全校节次由平台管理员维护"。改动最小，与"全校统一作息基准"的现状一致。
2. 放开教师管理员写：把两个 route name 从超管限定里拆出来。等于在学院隔离方向上开一个全校写入口，与第 2、3 节的方向相反，不建议。
3. 等 P3 的 `CAMPUS_SCHEDULING_ENABLED` 打开后由学院作息版本承担差异，全校表退为默认值。依赖 4.1 的缺口先补齐。

