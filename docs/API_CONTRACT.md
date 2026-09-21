# 后端 API 契约（身份与授权，P1 + P2 已实现）

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-21 |
| 权限基线 | [PERMISSIONS.md V1.1](./PERMISSIONS.md)（第 12 节 API 映射为权威来源） |
| 实施对照 | [PERMISSIONS_IMPLEMENTATION.md](./PERMISSIONS_IMPLEMENTATION.md) |
| 范围 | 本文只描述 **已落地并纳入真实 MySQL 测试** 的身份/授权端点的可执行契约；未实现端点见 PERMISSIONS.md 第 12 节标注。 |
| 代码 | `backend/app/modules/identity/{router,service,schemas,repository,wechat,deps}.py`、`backend/app/modules/audit/models.py` |

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

## 9. 测试覆盖

真实 MySQL 集成测试（`backend/tests/integration/`）：
- `test_identity.py`：Web 登录/Cookie/CSRF/刷新轮换重放/登出/锁定/本人绑定一次性。
- `test_admin_rbac.py`：角色边界矩阵、可选权限三项、目标选择器、会话自洽、并发与审计回滚。
- `test_wechat_binding.py`：code2session 错误映射、首次登录建号与 PRE_BINDING、完整链路签发→绑定→自动授 STUDENT、同一码并发核销仅一人成功、作废与幂等、明文只回显一次且库中仅存摘要、换绑/解绑撤销旧会话、Web 管理员不受限、敏感字段不外泄。
- `test_migrations.py` / `test_seed.py`：迁移升级/回滚零漂移、单 head、种子矩阵幂等。
