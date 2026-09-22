# 后端 API 契约（身份与授权 + 基础数据 + 导入 + 查课 + 提交/审核/考勤/文件 + 异议，P1 + P2 + P3 + P4 + P5 + P6 已实现）

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-22 |
| 权限基线 | [PERMISSIONS.md V1.1](./PERMISSIONS.md)（第 12 节 API 映射为权威来源） |
| 实施对照 | [PERMISSIONS_IMPLEMENTATION.md](./PERMISSIONS_IMPLEMENTATION.md) |
| 范围 | 本文只描述 **已落地并纳入真实 MySQL 测试** 的端点可执行契约（身份/授权 P1+P2、基础数据与两步原子导入 P3、查课任务与排班/申请/截止 P4、文件/提交/审核/考勤/到期清理 P5、异议 P6）；未实现端点见 PERMISSIONS.md 第 12 节标注。 |
| 代码 | `backend/app/modules/identity/{router,service,schemas,repository,wechat,deps}.py`、`backend/app/modules/audit/models.py`、`backend/app/modules/academic/{router,service,schemas,repository,models}.py`、`backend/app/modules/importer/{router,service,schemas,repository,models,permissions}.py`、`backend/app/modules/inspection/*`、`backend/app/modules/attendance/*`、`backend/app/modules/file/*`、`backend/app/modules/objection/{router,service,schemas,repository,models,permissions}.py`、`backend/app/common/parsing/{time_slots,xlsx_tabular}.py` |

## 1. 通用约定

- 前缀：业务 API 均为 `/api/v1`（`/health/*` 除外）。
- 成功响应信封：`{"data": <载荷>, "requestId": "<uuid>"}`。`requestId` 同时以响应头 `X-Request-Id` 返回，并写入审计与日志关联。
- 错误响应信封：`{"code", "message", "fieldErrors", "requestId"}`。`code` 为稳定业务错误码；`fieldErrors` 为字段级补充（可空对象）。不返回堆栈或数据库内部信息。
- ID 一律以字符串对外暴露（BIGINT 防 JS 精度丢失）。
- 版本字段命名：请求体用驼峰 `lockVersion`（Pydantic alias），响应体用蛇形 `lock_version`。
- 访问令牌：`Authorization: Bearer <access_token>`，有效期 15 分钟（`ACCESS_TOKEN_EXPIRE_MINUTES`）。每次请求都回查会话有效性，不单纯信任 JWT 签名。
- 刷新凭证传输分两条路径（技术方案 7.1）：
  - Web：`refresh` 经 `HttpOnly`、`SameSite=Lax`、`Path=/api/v1/auth` 的 Cookie 下发（`Secure` 生产必须开启）；响应体只含访问令牌，绝不含 `refresh_token`。`/auth/refresh` 走 Cookie 时叠加 CSRF 校验。
  - 原生/小程序：无 Cookie 语义，`refresh` 在 JSON 请求/响应体中往返。

## 2. 令牌传输契约速查

| 端点 | 客户端 | refresh 来源 | refresh 去向 | 响应体含 refresh？ | Set-Cookie？ |
|---|---|---|---|---|---|
| `POST /auth/web/login` | Web | — | 响应头 Set-Cookie | 否 | 是 |
| `POST /auth/wechat/login` | 小程序 | — | JSON 体 | 是 | 否 |
| `POST /auth/refresh` | Web | 请求 Cookie | 响应头 Set-Cookie | 否 | 是 |
| `POST /auth/refresh` | 小程序 | JSON 体 | JSON 体 | 是 | 否 |
| `POST /auth/logout` | Web | — | 清除 Cookie | 否 | 是（清除） |

## 3. 端点明细（身份 / 会话）

### 3.1 `POST /auth/web/login` — 账号密码登录（公开）

请求：`{"username": string, "password": string}`
成功 `200`：`data = {access_token, token_type:"bearer", expires_in}`；并下发 refresh Cookie。
错误：`401 UNAUTHENTICATED`（账号或密码错误 / 账号未启用）；`429 STATE_CONFLICT`（连续失败触发锁定）。

### 3.2 `POST /auth/wechat/login` — 微信登录（公开，P2）

请求：`{"code": string}`（`wx.login` 临时凭证，1–512）。
前置：`WECHAT_LOGIN_ENABLED=true`，否则 `403 FORBIDDEN`。
行为：`code2session` 换取 `openid` → 按 `appid+openid` 定位账号；不存在则自动创建"无口令、无角色"账号并写入 `wechat_identity`。签发 `WECHAT` 会话。首次登录（无 `student_id` 且无角色）→ `need_binding=true`，会话处于 PRE_BINDING 受限态。
成功 `200`：`data = {access_token, token_type, expires_in, refresh_token, need_binding}`。
错误：`401 UNAUTHENTICATED`（code 非法/已用）；`502 UPSTREAM_UNAVAILABLE`（微信超时/上游错误/响应不可解析/无有效 openid）。
安全：响应/审计/日志绝不含 `session_key`、`appid`、`secret`。

### 3.3 `POST /auth/refresh` — 刷新（轮换 + 重放检测）

无请求体（Web，从 Cookie 取值）或 `{"refresh_token": string}`（原生）。
成功 `200`：Web 返回 `{access_token, token_type, expires_in}` 并轮换 Cookie；原生返回含 `refresh_token` 的令牌对。
错误：`401 UNAUTHENTICATED`（缺凭证 / 无效 / 过期 / 重放旧凭证触发全族撤销）；`403 CSRF_FAILED`（Web 路径 Sec-Fetch-Site=cross-site 或 Origin 不在白名单）。
不变量：每次刷新旧凭证即时失效；检测到已撤销凭证被再次使用即撤销整个刷新族。

### 3.4 `POST /auth/logout` — 登出（需访问令牌）

成功 `204`（无响应体）；撤销当前会话并清除 Web refresh Cookie。

### 3.5 `GET /me` — 当前身份（需访问令牌）

成功 `200`：`data = {id, username|null, display_name, status, roles[], permissions[], binding_required}`。
`binding_required=true` 即 PRE_BINDING 受限态（`student_id` 为空且无任何角色）。Web 管理员即使无 `student_id`，因持有角色而不进入该态。
`permissions` 为「角色权限 ∪ 三项个人可选授权」的实时并集，每次现取不缓存。

### 3.6 `POST /me/student-binding` — 本人绑定学生（PRE_BINDING）

请求：`{"student_no": string, "binding_code": string}`。
成功 `200`：`data = {student_id, student_no, name}`。同事务核销一次性码、写 `student_id`、自动授予 STUDENT、`lock_version+=1`、追加审计。
错误：`404 NOT_FOUND`（账号/学号不存在）；`422 VALIDATION_ERROR`（码无效 / 码与学号不匹配）；`409 STATE_CONFLICT`（码已用 / 码过期 / 账号已绑定 / 学生已被他人绑定）。
并发：对同一码的并发核销以绑定码行 `SELECT … FOR UPDATE` 串行，仅一人成功，另一人 `409`。

## 4. 端点明细（授权管理闭环，P1）

### 4.1 `GET /role-assignment-targets` — 角色分配目标选择器

守卫：`role.assign`。成功 `200`：`data = {items:[{id, username|null, display_name, status, roles[], lock_version}], assignable_roles[]}`。`assignable_roles` 为操作者可手工管理的角色（超管三类管理角色；教师仅 `STUDENT_AFFAIRS_MANAGER`；均不含 STUDENT/VOLUNTEER）。

### 4.2 `PUT /users/{user_id}/roles` — 完整替换角色集合

守卫：`role.assign` + 角色差集边界。请求：`{"roles": string[], "lockVersion": int>=0, "reason"?: string}`。
成功 `200`：`data = {roles[], lock_version}`（实际角色与新版本）。
错误：`403 FORBIDDEN`（缺权限 / 越界 / 保护角色 / 试图手工授 STUDENT·VOLUNTEER）；`404 NOT_FOUND`（目标不可见）；`422 VALIDATION_ERROR`（未知角色 code）；`409 VERSION_CONFLICT`（版本不符）。
行为：撤销负责人角色时同事务清除其个人可选授权（不自动恢复）。请求模型刻意不含 password/status/permissions，防账号编辑旁路。

### 4.3 `GET /optional-permission-targets` — 可选权限目标选择器

守卫：`optional_permission.manage`。成功 `200`：`data = {items:[{id, display_name, status, permissions:[{code, enabled}], lock_version}], configurable_codes[]}`。仅返回持有 `STUDENT_AFFAIRS_MANAGER` 的账号；三项默认关闭。

### 4.4 `PUT /users/{user_id}/optional-permissions/{code}` — 逐人开关

守卫：`optional_permission.manage` + 三项许可清单。请求：`{"enabled": bool, "lockVersion": int>=0, "reason"?: string}`。`code ∈ {statistics.read, report.read, objection.initial_review}`。
成功 `200`：`data = {code, enabled, lock_version}`。
错误：`403 FORBIDDEN`（缺权限 / 自我提权）；`404 NOT_FOUND`；`422 VALIDATION_ERROR`（非三项 code / 目标非负责人）；`409 VERSION_CONFLICT`。
生效：下一次请求立即体现（不使用长期权限缓存）。

## 5. 端点明细（绑定码管理 / 换绑，P2）

统一守卫：`identity.binding.manage`。

### 5.1 `POST /students/{student_id}/binding-tokens` — 签发一次性绑定码

请求：`{"reason"?: string}`。
成功 `200`：`data = {token_id, student_id, plaintext_code, expires_at}`。`plaintext_code` **仅此响应回显一次**，库中只存 sha256 摘要；有效期由 `BINDING_TOKEN_VALID_MINUTES`（默认 60）控制。
错误：`403`（缺权限）；`404 NOT_FOUND`（学生不存在）。

### 5.2 `POST /binding-tokens/{token_id}/revoke` — 作废未使用绑定码

请求：`{"reason"?: string}`。
成功 `200`：`data = {token_id}`。
错误：`403`；`404 NOT_FOUND`；`409 STATE_CONFLICT`（码已核销，不可作废）。已作废重复调用幂等返回 `200`。

### 5.3 `POST /users/{user_id}/student-binding-reset` — 换绑 / 解绑（线下核验后）

请求：`{"new_student_no"?: string|null, "reason"?: string}`。`new_student_no` 为字符串则换绑到该学号；`null`/省略则解绑。
成功 `200`：`data = {user_id, student_id|null, revoked_sessions, lock_version}`。
行为：同事务锁定操作者与目标（按 ID 固定顺序），改绑保持/授予 STUDENT，解绑收回 STUDENT，并撤销目标全部有效会话（下一次请求需重新登录）。
错误：`403`；`404 NOT_FOUND`（学号不存在）；`409 STATE_CONFLICT`（该学生已被其他账号绑定）。

## 6. PRE_BINDING 受限会话语义（PERMISSIONS.md 1.6）

PRE_BINDING 是会话状态，不是角色：仅当账号 `student_id` 为空 **且** 无任何角色时成立。
- 放行白名单：`GET /me`、`POST /me/student-binding`、`POST /auth/refresh`、`POST /auth/logout`（登录类不算业务白名单）。
- 刷新只能延续该受限态，不能因旧令牌曾含角色而获得管理入口。
- 功能权限守卫（`require_permission`）天然拦住受限用户的业务访问（其 `permissions` 为空）；`require_binding_complete` 为「依赖本人 student_id」的接口再加一道纵深。
- Web 管理员不受此态影响（持有角色）。

## 7. 错误码字典

| code | HTTP | 语义 |
|---|---|---|
| `VALIDATION_ERROR` | 422 | 输入/业务规则不满足（未知角色、非三项 code、码无效等） |
| `UNAUTHENTICATED` | 401 | 未登录、令牌/会话失效、凭证无效或重放 |
| `FORBIDDEN` | 403 | 缺功能权限、越权边界、自我提权、功能未开放 |
| `CSRF_FAILED` | 403 | Cookie 写接口跨站校验未通过 |
| `NOT_FOUND` | 404 | 资源不存在或对操作者不可见 |
| `STATE_CONFLICT` | 409 | 状态冲突（已绑定、码已用/过期、账号锁定 429 亦复用此码） |
| `VERSION_CONFLICT` | 409 | `lock_version` 乐观并发不符；异议终审改判时考勤版本 ≠ 发起版本亦返回此码（不覆盖他人新认定） |
| `DUPLICATE_ACTIVE_OBJECTION` | 409 | 同一考勤已存在未完成异议（`final_status=PENDING`），并发下锁考勤行串行化恰一成功（P6） |
| `OBJECTION_WINDOW_CLOSED` | 409 | 超过可配置异议窗口（`OBJECTION_WINDOW_DAYS`）再对考勤提异议（P6） |
| `FILE_EXPIRED` | 410 | 访问已清理（`PURGED`/`PURGE_PENDING`）或超保留期的材料（P5，技术方案 16.3） |
| `UPSTREAM_UNAVAILABLE` | 502 | 微信 code2session 超时/上游错误/响应异常（P2） |
| `INTERNAL_ERROR` | 500 | 兜底内部错误（不回显细节） |

## 8. 配置项（环境注入，P2 新增）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WECHAT_LOGIN_ENABLED` | `false` | 微信登录总开关；关闭时 `/auth/wechat/login` 返回 403 |
| `WECHAT_APPID` | — | 小程序 appid，身份唯一键之一；不入响应/日志 |
| `WECHAT_SECRET` | — | code2session 密钥；仅进程内使用，绝不外泄 |
| `WECHAT_CODE2SESSION_URL` | `https://api.weixin.qq.com/sns/jscode2session` | 出站换取地址 |
| `WECHAT_TIMEOUT_SECONDS` | `5.0` | 出站超时，避免抖动拖垮同步线程池 |
| `BINDING_TOKEN_VALID_MINUTES` | `60` | 一次性绑定码有效期 |
| `BINDING_TOKEN_MAX_FAILED` | `5` | 绑定码失败次数上限（预留） |
| `IMPORT_PREVIEW_TTL_MINUTES` | `30` | 导入预览批次有效期；超时确认置 EXPIRED 并返回 409 |
| `IMPORT_MAX_ROWS` | `5000` | 单文件解析行数上限，超限预览返回 422 |
| `OBJECTION_WINDOW_DAYS` | `7` | 学生对某条考勤可提异议的窗口天数（自考勤生成时刻起算）；`0` 表示不限窗口（部署未定异议期时的保守值）（P6） |
| `OBJECTION_MAX_FILES` | `5` | 单条异议可关联的证明材料数上限，超限创建返回 422（P6） |

## 9. 测试覆盖

真实 MySQL 集成测试（`backend/tests/integration/`）：
- `test_identity.py`：Web 登录/Cookie/CSRF/刷新轮换重放/登出/锁定/本人绑定一次性。
- `test_admin_rbac.py`：角色边界矩阵、可选权限三项、目标选择器、会话自洽、并发与审计回滚。
- `test_wechat_binding.py`：code2session 错误映射、首次登录建号与 PRE_BINDING、完整链路签发→绑定→自动授 STUDENT、同一码并发核销仅一人成功、作废与幂等、明文只回显一次且库中仅存摘要、换绑/解绑撤销旧会话、Web 管理员不受限、敏感字段不外泄。
- `test_migrations.py` / `test_seed.py`：迁移升级/回滚零漂移、单 head、种子矩阵幂等。
- `test_academic.py`：基础数据 CRUD 与错误码矩阵（学期/节次/校历/行政班/学生/课程/教学班/名单/课表/志愿者资格）、`FOR UPDATE` 真实并发（名单整体替换、志愿者资格核销恰一成功）、有效资格自动授 VOLUNTEER、审计。
- `test_importer.py`：三类导入（roster/timetable/volunteer）预览→确认两步、组合权限象限（execute/target-manage 缺一即 403）、作用域校验、周次解析（区间/单双周/越界）、错误阻断确认、引用在两步之间失效的原子回滚零副作用、过期/重复确认状态机、审计，以及"先导入资格后绑定"由 `bind_student` 反向补授 VOLUNTEER。
- `test_inspection_*.py`（P4/P5）：任务生成预览→确认、排班改派、调班申请、取消/名单改版/截止结算、志愿者提交、审核通过生成考勤、考勤读取范围/更正/应到人数调整；含 `threading.Barrier` 真实 MySQL 并发不变式（改派/核销/审核与取消互斥等恰一成功）。
- `test_file_upload.py` / `test_file_purge.py`（P5）：上传尺寸/类型/保留期固化、按资源归属访问与签名下载；到期清理状态机 `READY→PURGE_PENDING→PURGED`、底层删除失败留 `PURGE_PENDING` 不改判、重跑幂等、系统触发空操作者审计。
- `test_objection.py`（P6）：创建守卫/归属防枚举/诉求与当前一致 422/未完成异议去重 409/窗口超期 409/材料校验 422 与合法关联；读取 OWN vs MANAGE、负责人默认无路径 403 及授予初核后派生管理读取（关闭即失去）、详情越界 404；初核不改考勤、重复 409；终审驳回不改、通过改判并追加 `OBJECTION_FINAL` 版本、陈旧/他人新认定 `VERSION_CONFLICT`、重复 409、负责人无终审 403；同一考勤并发创建恰一成功；未完成异议暂停其材料到期清理、关闭后重新纳入并清理。

## 附录 A：P3 基础数据端点（`/api/v1/academic`）

守卫以功能权限为准（`require_permission`）；写操作均在服务端会话取操作者、同事务追加 `AuditLog`、`SELECT … FOR UPDATE` 串行化父资源。ID 一律字符串出入。

| 方法 路径 | 守卫 | 关键错误码 |
|---|---|---|
| `POST/PATCH /semesters[/{id}]`、`GET /semesters[/{id}]` | 写 `academic.manage` / 读 `academic.read` | `409`（code 重复、归档后写子资源）、`422`（结束早于开始、非法状态） |
| `PUT/GET/DELETE /semesters/{id}/period-definitions[/{no|id}]` | `academic.manage` / `academic.read` | `422`（`period_no` 越界 1..20、时刻逆序）；节次号以路径为权威，请求体可省略 |
| `POST/GET/DELETE /semesters/{id}/calendar-overrides[/{oid}]` | `academic.manage` / `academic.read` | `422`（补课缺来源星期）、`409`（同日期唯一） |
| `POST/PATCH/GET /administrative-classes[/{id}]` | `academic.manage` / `academic.read` | `409`（class_code 重复） |
| `POST/PATCH/GET /students[/{id}]`、`GET /students` | 写 `student.manage` / 读 `student.read` | `404`（行政班不存在）、`409`（学号重复）、`422`（非法状态） |
| `POST/PATCH/GET /courses[/{id}]` | `academic.manage` / `academic.read` | `409`（course_code 重复） |
| `POST/PATCH/GET /teaching-classes[/{id}]` | `academic.manage` / `academic.read` | `404`（课程不存在）、`409`（同学期同课同码重复、非活跃学期） |
| `GET/PUT /teaching-classes/{id}/students`（名单整体替换） | `student.read` / `student.manage` | `404`（含不存在学生）；PUT 语义为整体替换并去重 |
| `POST/PATCH/GET/DELETE /course-schedules[/{id}]` | `academic.manage` / `academic.read` | `422`（周次越界、结束早于开始）、`404`（教学班不存在、删除后读取） |
| `PUT/GET /volunteer-qualifications` | `volunteer.manage` / `volunteer.read` | `404`（学生不存在）；启用且学生已绑定则同事务自动授 VOLUNTEER，停用不回收 |

## 附录 B：P3 两步原子导入（`/api/v1`）

设计（技术方案 19、PERMISSIONS.md 12.5）：上传解析只暂存为 `import_batch`（规范行入 `payload_json`、统计入 `summary_json`、结构化问题入 `error_json`），确认阶段不再依赖原文件，仅重校验外部引用后整批单事务落库、**单次提交**。明文文件不入库。

组合权限：执行导入 = `import.execute` **且** 目标资源 `manage`。目标映射 roster→`student.manage`、timetable→`academic.manage`、volunteer→`volunteer.manage`。路由级 `ImportExecuteDep` 早拦（缺 execute → 403），服务事务内重读有效权限纵深复核（缺 target-manage → 403）。模板下载仅需 target-manage。

预览→确认状态机：

```
(上传) --POST /imports--> PREVIEW --POST /{id}/confirm--> CONFIRMED（终态，重复确认 409）
                              |                 ^-- 有 error 项 --> 422（拒绝确认）
                              |-- 过期 --> EXPIRED（确认时置位并 409）
```

| 方法 路径 | 守卫 | 说明 |
|---|---|---|
| `GET /import-templates/{target}` | target-manage | 返回 `{target, scope_fields, columns[], example_rows[]}`；`target∈{roster,timetable,volunteer}`，未知 422 |
| `POST /imports`（multipart） | import.execute（+服务纵深） | 表单：`file`(xlsx)、`target`、`semester_id?`、`teaching_class_id?`、`replace=true`。成功 `200`：`data={id,target,status:"PREVIEW",semester_id,teaching_class_id,summary,errors[],warnings[],expires_at,can_confirm}`。非法/损坏 xlsx→422；行数超 `IMPORT_MAX_ROWS`→422；作用域缺失→422、作用域资源不存在→404；写审计 `import.batch.preview` |
| `GET /imports/{id}` | import.execute（+纵深） | 复用预览视图；批次不存在 404 |
| `GET /imports/{id}/errors` | import.execute（+纵深） | 返回 `{errors[], warnings[]}`（按 severity 拆分） |
| `POST /imports/{id}/confirm` | import.execute（+纵深） | 成功 `200`：`data={id,target,status:"CONFIRMED",summary}`（并入创建计数）。`409`（已确认 / 非 PREVIEW / 已过期）；`422`（存在 error 项、两步之间外部引用失效、周次超学期范围）。**任一失败整批回滚、业务零副作用**；成功写审计 `import.batch.confirm` |

`can_confirm` = `status==PREVIEW` 且无 error 级问题且未过期。确认对批次行 `SELECT … FOR UPDATE`，并锁定父作用域（roster 锁教学班→其学期须 ACTIVE；timetable/volunteer 锁学期须 ACTIVE，归档 409）。

各目标落库语义：roster 对目标教学班整体替换名单（学号→ID，缺任一即写前 422）；timetable 按课程代码 get-or-create 课程、按 `(学期,课程,教学班码)` get-or-create 教学班，再建课表与生效周（`1-16`、`单周/双周`、`1,3,5`、`第x-y周` 等组合，越界/倒置为 error）；volunteer 按 `(学期,学生)` upsert 资格行，`enabled` 且学生已绑定则即时补授 VOLUNTEER（幂等，`lock_version+=1`）。

"先导入资格后绑定"对称：导入阶段资格已启用但学生尚未绑定，则仅落资格行；待该生后续 `POST /me/student-binding` 绑定时，`bind_student` 检测到其持有 ACTIVE 学期下启用中的资格，反向补授 VOLUNTEER（与正向补授对称）。

## 附录 C：P4 查课任务生成与排班（`/api/v1`）

数据前缀 `/api/v1`，Inspection 路由独立挂载。令牌双路径与错误字典同第 2、7 节。ID 一律字符串出入；所有写操作在服务会话取操作者、事务内 `SELECT … FOR UPDATE` 串行化、末尾单次 `commit`、同事务追加 `AuditLog`。

### C.1 任务生成（预览 → 生成两步，`inspection.generate`）

`POST /inspection-tasks/preview` 与 `POST /inspection-tasks/generate` 共用 `InspectionGenerateRequest`：`semester_id`、`inspection_type∈{COURSE,MORNING_STUDY}`、时段选择 `week_nos` **或** `date_from/date_to`（至少其一，越学期 422）、`COURSE` 需 `teaching_class_ids`、`MORNING_STUDY` 需 `administrative_class_ids`+`start_period`+`end_period`（`end>=start`）；`require_photo`、`reason`。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /inspection-tasks/preview` | `inspection.generate` | **只读**：返回 `{task_count,new_task_count,existing_task_count,date_count,student_total,within_limit,sample[]}`，`finally` 必 `rollback`，零写库。校历 `STOP` 日跳过、`MAKEUP` 取来源星期 |
| `POST /inspection-tasks/generate` | `inspection.generate` | 事务内锁学期（`FOR UPDATE`）串行化同学期并发；按 `task_key` 幂等物化新任务 + 名单版本 `v1` + 成员快照 + 缺失查课日的 `SubmissionDeadlineDay/Version v1`（默认时刻本地转 naive-UTC），**整批单事务单次提交**；计划任务数超 `INSPECTION_GENERATE_MAX_TASKS` 在写入前 422。归档学期 409。审计 `inspection.task.generate` |

生成后读取：`GET /inspection-tasks`、`GET /inspection-tasks/{id}`、`GET /inspection-tasks/{id}/students`（名单，`inspection.roster.read`+可见性范围）、`GET /me/inspection-tasks`（强制本人受派范围）。数据范围：管理角色全部可见、志愿者仅本人受派（`resolve_scope`，管理范围优先）。

### C.2 排班与改派（Wave 3a，`assignment.manage`）

硬约束（技术方案 11.2，人工与自动同判、不允许旁路）：账号为启用志愿者、本学期资格有效、避开本人行政班被查名单（本班回避）、与本人课表时段不冲突、与本人其他受派任务时段不冲突（按完整起止节次重叠比较）。软约束单日上限 `ASSIGNMENT_MAX_TASKS_PER_DAY`（默认 `0`=不限）。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `PUT /inspection-tasks/{task_id}/assignment` | `assignment.manage` | 人工分配/改派：`AssignmentSetRequest{volunteer_user_id,lock_version,reason?}`。锁层级先取 `(志愿者,日期)` 日期锚点（含换人时新旧双方），再锁任务行；已取消 409 `STATE_CONFLICT`、`lock_version` 不符 409 `VERSION_CONFLICT`、硬约束不过 422 `VALIDATION_ERROR`+`fieldErrors.reason_code`；受派 upsert（`assign_method=MANUAL`，改写则 `assignment.lock_version+=1`）、`task.lock_version+=1`；审计 `assignment.manual_set`（含 before/after 快照） |
| `POST /assignments/auto` | `assignment.manage` | 自动排班：`AutoAssignRequest{semester_id, task_ids \| inspection_date \| date_from/date_to, candidate_user_ids?, reason?}`（三选一范围、`date_to>=date_from`）。Phase A 无锁贪心（任务按 `(date,id)`、候选按 id 升序，批内占用记 busy），Phase B 单事务按全局锁层级加锁后逐条**锁内重验**再落库（`assign_method=AUTO`）。全成全败，一任务一受派；审计 `assignment.auto_run`。返回 `{target_task_count,assigned_count,unassigned_count,assigned[],unassigned[{task_id,reason_code,message}]}` |

排班拒绝原因码（`fieldErrors.reason_code` / `unassigned[].reason_code`）：`NOT_VOLUNTEER`、`NO_QUALIFICATION`、`OWN_CLASS_CONFLICT`、`SELF_CLASS_AVOID`、`TASK_TIME_CONFLICT`、`DAY_TASK_CAP`、`TASK_CANCELED`。判定优先级即按上序取首个命中。

### C.3 并发不变式（技术方案 15）

全局锁层级：`(志愿者, 日期)` 锚点 → 任务 → …，一律升序取得。人工改派先锁新旧志愿者当日锚点、自动排班 Phase B 先锁全部计划锚点再按 id 升序锁任务，杜绝交叉死锁。落库阶段的时段冲突重查用 `SELECT … FOR SHARE` 锁定读（`list_assignments_for_volunteer_on_date(for_update=True)`）——REPEATABLE READ 快照读会错过并发方刚提交的受派，锁定读绕过旧读视图，确保"同一志愿者同日重叠时段至多一条受派"。集成测试以独立连接 + `threading.Barrier` 双线程验证：恰好一条落库、另一方在锁内重验被拒（`VALIDATION_ERROR`/`VERSION_CONFLICT`/死锁回滚均可）。

### C.4 调班申请（Wave 3b，志愿者发起 / 管理人员处理）

语义边界：志愿者对**本人当前受派**发起调班诉求并留痕；`APPROVED/REJECTED` 仅迁移申请状态，**不隐式改派**——真正的换人仍走 `assignment.manage`（申请模型无替补志愿者字段，避免审核即换人的越权副作用）。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /assignment-change-requests` | `assignment.change_request` | `ChangeRequestCreateRequest{assignment_id,reason}`。"当前受派人"边界：受派不存在 404、非本人受派 403；任务已取消 409 `STATE_CONFLICT`；同受派已有 `PENDING` 再发起 409。成功建 `PENDING` 行，返回 `ChangeRequestResponse`（回填 `task_id`）。审计 `assignment.change_request.create` |
| `GET /me/assignment-change-requests` | `assignment.change_request` | 志愿者读取**本人**申请（无论角色强制 `request_user_id=本人`），分页 + 可选 `status` 过滤 |
| `GET /assignment-change-requests` | `assignment.change_review` | 管理视图读取**全部**申请，分页 + 可选 `status` 过滤 |
| `POST /assignment-change-requests/{request_id}/review` | `assignment.change_review` | `ChangeRequestReviewRequest{decision∈{APPROVED,REJECTED},comment?}`。`SELECT … FOR UPDATE` 锁申请行，仅 `PENDING` 可处理（否则 409）、申请不存在 404；置 `status/processed_by/processed_at/comment`。审计 `assignment.change_request.review`（before/after 状态） |

响应 `ChangeRequestResponse`：`{id,assignment_id,task_id,request_user_id,reason,status,processed_by,processed_at,comment,created_at,updated_at}`。

申请并发不变式：同一 `PENDING` 申请被两连接同时处理时，申请行 `FOR UPDATE` + "非 `PENDING` 即 409"保证**恰好一次转态**、另一方被拒；`approve` 后受派人 `volunteer_user_id` 保持不变（集成测试断言无隐式改派）。

### C.5 取消 / 名单改版 / 截止配置 / 截止时结算（Wave 3c）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /inspection-tasks/{task_id}/cancel` | `inspection.cancel` | `TaskCancelRequest{reason,lock_version}`。`SELECT … FOR UPDATE` 锁任务，不存在 404、已取消 409 `STATE_CONFLICT`、版本不符 409 `VERSION_CONFLICT`。**锁内先按当前适用旧截止版本幂等结算锁定既有逾期事实**，再置 `canceled_at/canceled_by/cancel_reason`、`lock_version++`。审计 `inspection.task.cancel`。返回任务 DTO（`status=已取消`） |
| `POST /inspection-tasks/{task_id}/roster-versions` | `inspection.roster.manage` | `RosterVersionCreateRequest{student_ids,reason,lock_version}`。锁任务，已取消 409、版本不符 409；学生含不存在/非在读 → 422 `fieldErrors{missing_student_ids,inactive_student_ids}`。生成 `roster_version+1` 新版本、冻结学生快照（学号/姓名/班名/年级），更正 `expected_count_current`、`lock_version++`。审计 `inspection.roster.revise` |
| `GET /inspection-tasks/{task_id}/roster-versions` | `inspection.roster.read` | 叠加任务可见性范围（志愿者仅本人受派，否则 404）；返回 `[{version_no,reason,created_by,member_count,created_at}]` |
| `GET /submission-deadlines/default` | `submission_deadline.read` | 只读反射部署配置的全局默认提交截止时刻（本地墙上时钟 `HH:MM`）+ `utc_offset_hours` + 说明。**改默认值属部署/配置动作、无写接口**，仅影响后续新建日截止，不追溯改写既有（技术方案 13.1、冻结纪律） |
| `GET /submission-deadlines/days?semester_id&date_from&date_to` | `submission_deadline.read` | 某学期日截止列表（可选日期范围），每项含 `task_count`（当日未取消任务数） |
| `GET /submission-deadlines/days/{inspection_date}?semester_id` | `submission_deadline.read` | 单日截止；无记录 404 |
| `GET /submission-deadlines/days/{inspection_date}/versions?semester_id` | `submission_deadline.read` | 该日截止版本历史（`version_no/deadline_at/changed_by/reason/created_at`） |
| `PUT /submission-deadlines/days/{inspection_date}?semester_id` | `submission_deadline.manage` | `DeadlineDayUpdateRequest{time(HH:MM),reason,lock_version(ge1)}`。锁日截止行，学期/记录不存在 404、版本不符 409。`time` 非法 → 422 `fieldErrors{time}`。**改期前先对该日未结算任务按旧截止版本幂等结算锁定既有事实**；若新截止早于当日最晚任务结束时刻 → 422 `fieldErrors{reason_code:DEADLINE_BEFORE_TASK_END,latest_task_end}`（无节次时刻定义时不阻断）。成功 `version++` 并写 `SubmissionDeadlineVersion` 历史。审计 `submission_deadline.day_update`（before/after 截止值以 ISO 字符串入库） |
| `POST /submission-deadlines/settle` | `submission_deadline.manage` | `DeadlineSettleRequest{semester_id,inspection_date?,task_ids?,limit(默认500,≤2000)}`。有界同步结算，不依赖页面访问。对未结算任务逐个 `FOR UPDATE` 锁行后幂等生成 `task_deadline_assessment`。返回 `{semester_id,considered,settled,already_settled,not_due,results[{task_id,result}]}`。审计 `submission_deadline.settle` |

截止时考核结果 `result ∈ {VALID_SUBMISSION, OVERDUE_UNEXECUTED, CANCELED}`：截止前已取消 → `CANCELED`；服务端时间严格超过适用截止（等值仍按时）且未取消 → `OVERDUE_UNEXECUTED`；未到期 → 不生成快照（`deadlineAssessment=null`）。`VALID_SUBMISSION` 留待 P5 提交域填充。任务视图回填 `deadline_at/deadline_version_id/deadline_assessment`。

任务当前态五态精判（`_derive_status`，技术方案 12）：`canceled_at → 已取消`；（P5）审核通过提交 → 已完成；（P5）待审核提交 → 待审核；`utcnow() > 当日 deadline_at → 已逾期`；否则 `待执行`。`已完成/待审核` 为提交域注释钩子。

结算/改期并发不变式：`settle` 与 `cancel`/`day_update` 均在任务行（或日截止行）`FOR UPDATE` 锁内先结算再变更，`_settle_assessment` 对已存在快照返回 `SKIP`（幂等）；两连接同时结算同一到期任务时，任务锁串行化 + 已有快照检查保证**恰好一行 `task_deadline_assessment`**（集成测试 `threading.Barrier` 双线程验证）。改晚截止不清除已结算的 `OVERDUE_UNEXECUTED`（截止时事实不可被普通业务改写）。

## 附录 D：P5 文件 / 提交 / 审核 / 考勤 / 到期清理（`/api/v1`）

数据前缀 `/api/v1`。令牌双路径与错误字典同第 2、7 节；ID 一律字符串出入。写操作事务内 `SELECT … FOR UPDATE` 串行化、末尾单次 `commit`、同事务追加 `AuditLog`（到期清理系统作业除外，见 D.5）。

### D.1 文件域（Wave 5b，技术方案 16）

文件无独立功能权限，访问按"业务资源归属"放行。存储后端可插拔（`FILE_STORAGE_BACKEND=local|object`，V1.0 dev/test 用 `LocalStorage`）。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /files` | 类别相关（multipart） | `category ∈ {SUBMISSION_PHOTO,OBJECTION_PROOF,IMPORT_FILE,REPORT_FILE,TEMP}`，受限类别经 `required_upload_permission` 追加校验（如导入/报表需 `import.execute`/`report.*`）。PRE_BINDING 受限会话 403。服务端随机 `object_key`（绝不用原名作路径）、纯解析器读头校验尺寸/像素/类型，超限 422。落 `READY` 行，`expires_at` 按类别保留期（`FILE_RETENTION_*_DAYS`，起算上传成功时刻）固化，`retention_policy_version` 记命中版本。审计 `file.upload` |
| `GET /files/{file_id}/access` | 资源归属 | 不可见/不存在统一 404 防枚举；已清理/到期 → `FILE_EXPIRED`；未就绪（`UPLOADING/FAILED`）→ 409。返回短时签名 GET 链接（`FILE_SIGNED_URL_TTL_SECONDS`，默认 300s） |
| `GET /files/{file_id}/download` | 仅签名 | **不再鉴权**（技术方案 16.2：不即时撤销已发链接），只校验 HMAC 签名 + 过期时间戳 + 对象未清理；已清理/到期 `FILE_EXPIRED`，签名无效/过期 403 |

`can_access`：上传者本人恒可访问自己的 `READY` 材料；已挂到提交的材料，持 `submission.review` 者经任意提交链接可得、仅持 `submission.read` 的志愿者只能经本人受派提交访问。

### D.2 查课提交（Wave 5c，`submission.create` / `submission.read`）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /inspection-tasks/{task_id}/submissions` | `submission.create` | `SubmissionCreateRequest{result∈{NORMAL,ABNORMAL},abnormal_items[{student_id,attendance_type,note?}],file_ids[]}`。守卫链：`_require` 锁操作者并重读权限 → PRE_BINDING 403 → 账号 `ACTIVE` → 持 `VOLUNTEER` 角色（仅持权限码无角色 403）→ 任务 `FOR UPDATE` 且未取消 → `assignment.volunteer_user_id==actor`（非本人受派 403）→ 本学期志愿者资格 → 无开放提交（否则 409 `STATE_CONFLICT`）→ 结论一致性（NORMAL 带明细 / ABNORMAL 无明细 → 422）→ 异常学生须在本任务当前名单版本且无重复（422 `fieldErrors{duplicate_student_ids,not_in_roster_student_ids}`）→ 附件校验（要求照片却空 / 超 `FILE_MAX_FILES_PER_SUBMISSION` / 非 `READY`/非本人/类别不符/已过期 → 422）。写前幂等结算锁"截止时"事实，冻结 `deadline_version_id`，`attempt_no=max+1`，插 `PENDING` 提交 + 异常明细 + 提交文件关联，`task.lock_version++`，审计 `submission.create` |
| `GET /me/submissions` | `submission.read` | 强制 `volunteer_user_id=本人`（`OWN_SUBMISSION` 范围），分页 |
| `GET /submissions/{id}` | `submission.read` | 读他人/越界提交统一 404 防枚举；本人可读 |

不变式"至多一个待审核/审核通过"：存在 `PENDING|APPROVED` 提交时再次提交 → 409；真实并发恰好一成一拒（任务 `FOR UPDATE` 串行化）。

### D.3 审核通过生成考勤（Wave 5d，`submission.review`）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /submissions/{submission_id}/review` | `submission.review` | `SubmissionReviewRequest{decision∈{APPROVED,REJECTED},comment?(≤512)}`。锁序遵 §15：先探提交（不加锁，缺失 404）→ `get_task_for_update`（任务先于提交）→ 再 `FOR UPDATE` 提交行；非 `PENDING` → 409 `STATE_CONFLICT`（提交已处理），任务已取消 → 409（提交已处理）。`APPROVED`：先幂等结算锁截止事实，再**按名单当前版本逐生生成考勤**（命中异常明细者取 `attendance_type` + `source_submission_item_id`，未列者 `NORMAL`；`current_version=1`、写 `AttendanceRecordVersion v1 source=SUBMISSION`），`AttendanceRecord` 批量 `add→flush` 取 id 再补版本行。`REJECTED` 仅记审核痕迹、不生成考勤、不改事实（可再次提交 `attempt_no+1`）。`task.lock_version++`；审计 `submission.review.approved`/`.rejected` |

考勤事实唯一约束 `unique(task_id, student_id)`；审核与取消互斥（都锁任务，恰一成功，绝不"既取消又生成考勤"，集成测试 `threading.Barrier` 断言 `canceled XOR has_attendance`）。已有 `APPROVED` 提交（考勤已成立）后取消任务 → 409 `STATE_CONFLICT`（技术方案 51）。

### D.4 考勤读取 / 更正 / 应到人数调整（Wave 5d）

数据可见性（PERMISSIONS.md 6.3）：`attendance.read` 全五角色持有，但 **SA/TA/SAM=全院 `MANAGE` 范围、VOLUNTEER+STUDENT=仅本人 `SELF_STUDENT`**。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `GET /me/attendance` | `attendance.read` | 强制 `student_id=本人`；无绑定学生 403 |
| `GET /attendance` | `attendance.read` | 仅 `MANAGE` 范围可列（非管理范围 403）；分页 + `task_id/semester_id/effective_type` 过滤 |
| `GET /attendance/{record_id}` | `attendance.read` | 越界（非管理读他人、本人无该记录）统一 404 防枚举 |
| `GET /attendance/{record_id}/versions` | `attendance.read` | 同读取范围门禁，返回不可变版本历史 |
| `POST /attendance/{record_id}/corrections` | `attendance.correct` | `AttendanceCorrectionRequest{attendance_type,reason(1–512),current_version(ge1)}`。`AttendanceRecord` 行 `FOR UPDATE`，`current_version` 不符 → 409 `VERSION_CONFLICT`；改 `effective_type` + `current_version+=1`，**追加** `AttendanceRecordVersion(source=CORRECTION,source_id=record.id,changed_by=actor)`（不可变多态来源）。审计 `attendance.correct` |
| `PATCH /inspection-tasks/{task_id}/expected-count` | `attendance.expected_count_adjust` | `ExpectedCountUpdateRequest{expected_count_current(ge0),reason(1–512),lock_version(ge0)}`。锁任务，已取消 409、版本不符 409 `VERSION_CONFLICT`；`expected_count_current < 该任务非 NORMAL 考勤数` → 422 `fieldErrors{expected_count_current,abnormal_count}`。仅改 `expected_count_current`（`expected_count_snapshot` 冻结不动）、`lock_version++`；审计 `attendance.expected_count_adjust`（before/after 人数） |

`AttendanceRecord` 仅 `CreateTimeMixin`（记录无 `updated_at`，更正以版本行追加留痕）；`AttendanceRecordVersion` 不可变多态来源 `source_type ∈ {SUBMISSION,CORRECTION,OBJECTION_FINAL}`、`source_id` 无外键。响应不含 `updated_at`。

### D.5 到期材料清理（Wave 5e，部署定时脚本）

**不在 API 进程内起独立定时器**（技术方案 66）。清理由部署侧定时任务（cron / 任务计划）执行 `deploy/scripts/cleanup_expired_files.py`，复用 `FileService.purge_expired_files`，逐文件独立事务提交、可重跑幂等：

状态机（技术方案 16.1/16.3）：到期 `READY` → 先落库 `PURGE_PENDING`（持久化清理意图，崩溃可恢复）→ 删底层对象，成功才置 `PURGED` 记 `purged_at`；底层删除失败**保留 `PURGE_PENDING`** 待下次运行、绝不改判为已清理；对象已缺失视作清理完成。访问侧已 `PURGED`/`PURGE_PENDING`/已过期文件一律 `FILE_EXPIRED`。审计 `file.purge` 由**系统触发**（`actor_user_id=NULL`，`reason=retention_expired`，before/after 记状态）。已 `PURGED` 者不再入选候选，重复运行无副作用。`expires_at`/`retention_policy_version` 落库后不随配置改动无审计地缩短旧材料期限。

## 附录 E：P6 异议域（`/api/v1`）

数据前缀 `/api/v1`。令牌双路径与错误字典同第 2、7 节；ID 一律字符串出入。写操作事务内 `SELECT … FOR UPDATE` 串行化、末尾单次 `commit`、同事务追加 `AuditLog`。全局锁层级（技术方案 15）：考勤 → 异议——创建**先锁考勤行**再在其保护下查重与落异议；终审**先锁考勤、再锁异议**（`populate_existing` 重读）；初核不改考勤故仅锁异议行（对缺席层跳过）。

**读取路径的特殊性（PERMISSIONS.md 7.6 / 8.2 / 8.3）**：异议"管理读取"并非靠 `objection.read`，而是路由用 `require_any_permission(objection.read | objection.initial_review | objection.final_review)` 早拦后，由 Service 依有效权限解析范围——持 `initial_review` 或 `final_review` 之一 = `MANAGE`（全学院）；仅持 `objection.read` 且能解析出有效 `student_id` = `OWN`（只见本人）；二者皆无或 `read` 却无学生绑定 = `NONE`。学生工作负责人默认**不持** `objection.read`（矩阵"条件派生"），仅当被授予可选项 `objection.initial_review` 后才派生出 `MANAGE` 读取来源，关闭初核即失去（`attendance.read` 不提供替代证明读取）。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /attendance/{record_id}/objections` | `objection.create` | `ObjectionCreateRequest{desired_type∈{NORMAL,LEAVE,LATE,ABSENT},reason(1–512),file_ids[](≤50)}`。守卫链：`_require` 锁操作者并重读权限 → 解析本人 `student_id`（无绑定 403）→ `AttendanceRecord` 行 `FOR UPDATE`（他人生成/不存在统一 404 防枚举）→ 窗口校验（`utcnow() > created_at + OBJECTION_WINDOW_DAYS` → 409 `OBJECTION_WINDOW_CLOSED`，`0`=不限）→ 诉求 == `effective_type` → 422 → 同考勤有 `final_status=PENDING` 未完成异议 → 409 `DUPLICATE_ACTIVE_OBJECTION`。材料校验：去重后须 ≤ `OBJECTION_MAX_FILES`（超 422），逐个 `get_for_update` 核验仍 `READY`、类别 `OBJECTION_PROOF`、`uploader==本人`、未过期（任一不符 422，与到期清理同锁协议串行化）。落 `Objection`（记 `base_attendance_version=record.current_version`）+ `ObjectionFile` 关联，审计 `objection.create` |
| `GET /objections` | `objection.read \| initial_review \| final_review`（任一） | Service 解析范围：`MANAGE` 全量 / `OWN` 加 `student_id=本人` 谓词 / `NONE` 403。分页 + `attendance_record_id/final_status/initial_status` 过滤 |
| `GET /objections/{objection_id}` | 同上（任一） | 越界/不可见与不存在统一 404 防枚举；`MANAGE` 可读任意、`OWN` 仅本人 |
| `POST /objections/{objection_id}/initial-review` | `objection.initial_review` | `ObjectionInitialReviewRequest{decision∈{PASSED,REJECTED},comment?(≤512)}`。锁异议行，`initial_status≠PENDING` → 409 `STATE_CONFLICT`；置状态/处理人/时刻/意见，**绝不改考勤**，审计 `objection.initial_review` |
| `POST /objections/{objection_id}/final-review` | `objection.final_review` | `ObjectionFinalReviewRequest{decision∈{APPROVED,REJECTED},final_type?(∈全集),comment?,current_version(ge1)}`。先探异议（不加锁，缺失 404）→ `AttendanceRecord` `FOR UPDATE` → 异议 `FOR UPDATE` 重读；`final_status≠PENDING` → 409。`REJECTED` 不改考勤。`APPROVED` 须给 `final_type`（缺 422）；`final_type≠effective_type` 即"更正"，须另持 `attendance.correct`（否则 403），且 `current_version==record.current_version` 且 `record.current_version==base_attendance_version`（任一不符 409 `VERSION_CONFLICT`，不覆盖他人新认定），通过则同事务改 `effective_type`、`current_version=base+1`、**追加** `AttendanceRecordVersion(source=OBJECTION_FINAL,source_id=objection.id)`。审计 `objection.final_review`（before/after 含考勤） |

状态机：`initial_status∈{PENDING,PASSED,REJECTED}`、`final_status∈{PENDING,APPROVED,REJECTED}`（`PENDING` 即"未完成异议"）。`Objection` 用 `TimestampMixin`（可变流转，有 `updated_at`）；`attendance_record_id` 随考勤 `CASCADE`，`student_id` 对主数据 `RESTRICT`。`ObjectionFile` 联合主键、`file_id` 对文件 `RESTRICT`。

**清理耦合（技术方案 16.3、538/713）**：被**未完成异议**（`final_status=PENDING`）引用的材料暂停到期清理——`FileRepository.list_purge_candidates` 以 `NOT IN` 未完成异议文件子查询排除之；异议关闭后自然重新纳入候选。新建异议关联材料用与清理相同的**文件行 `FOR UPDATE` + `READY` 核验**串行化，避免"校验后新增引用而误删"。

**遗留到 P7**：报表源修订号（`report_source_revision`）对考勤类变更（更正 / 终审改判等所有影响考勤路径）的统一递增，留待报表域一次性施加，此处不单独造数（遵循冻结纪律，见 §6）。
