# 后端 API 契约（身份与授权 + 基础数据 + 导入，P1 + P2 + P3 已实现）

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-21 |
| 权限基线 | [PERMISSIONS.md V1.1](./PERMISSIONS.md)（第 12 节 API 映射为权威来源） |
| 实施对照 | [PERMISSIONS_IMPLEMENTATION.md](./PERMISSIONS_IMPLEMENTATION.md) |
| 范围 | 本文只描述 **已落地并纳入真实 MySQL 测试** 的端点可执行契约（身份/授权 P1+P2、基础数据与两步原子导入 P3）；未实现端点见 PERMISSIONS.md 第 12 节标注。 |
| 代码 | `backend/app/modules/identity/{router,service,schemas,repository,wechat,deps}.py`、`backend/app/modules/audit/models.py`、`backend/app/modules/academic/{router,service,schemas,repository,models}.py`、`backend/app/modules/importer/{router,service,schemas,repository,models,permissions}.py`、`backend/app/common/parsing/{time_slots,xlsx_tabular}.py` |

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
| `VERSION_CONFLICT` | 409 | `lock_version` 乐观并发不符 |
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

## 9. 测试覆盖

真实 MySQL 集成测试（`backend/tests/integration/`）：
- `test_identity.py`：Web 登录/Cookie/CSRF/刷新轮换重放/登出/锁定/本人绑定一次性。
- `test_admin_rbac.py`：角色边界矩阵、可选权限三项、目标选择器、会话自洽、并发与审计回滚。
- `test_wechat_binding.py`：code2session 错误映射、首次登录建号与 PRE_BINDING、完整链路签发→绑定→自动授 STUDENT、同一码并发核销仅一人成功、作废与幂等、明文只回显一次且库中仅存摘要、换绑/解绑撤销旧会话、Web 管理员不受限、敏感字段不外泄。
- `test_migrations.py` / `test_seed.py`：迁移升级/回滚零漂移、单 head、种子矩阵幂等。
- `test_academic.py`：基础数据 CRUD 与错误码矩阵（学期/节次/校历/行政班/学生/课程/教学班/名单/课表/志愿者资格）、`FOR UPDATE` 真实并发（名单整体替换、志愿者资格核销恰一成功）、有效资格自动授 VOLUNTEER、审计。
- `test_importer.py`：三类导入（roster/timetable/volunteer）预览→确认两步、组合权限象限（execute/target-manage 缺一即 403）、作用域校验、周次解析（区间/单双周/越界）、错误阻断确认、引用在两步之间失效的原子回滚零副作用、过期/重复确认状态机、审计，以及"先导入资格后绑定"由 `bind_student` 反向补授 VOLUNTEER。

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
