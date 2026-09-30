# Web 管理端 W0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员在浏览器完成账号登录、会话恢复、权限驱动的导航，并读取真实任务列表和详情。

**Architecture:** `apps/admin-web` 是独立 Vue SPA，通过同源 `/api/v1` 调用现有 FastAPI。access token 仅在内存中；refresh token 由服务端的 HttpOnly Cookie 发送。HTTP 客户端负责响应信封、一次串行刷新和稳定错误码；业务列表保持本地查询状态，Pinia 只存会话与当前学期。

**Tech Stack:** Vue 3、TypeScript、Vite、Vue Router、Pinia、Element Plus、Vitest；后端 FastAPI / MySQL 不更换。

## Global Constraints

- 产品依据：根目录《查课管理系统V1.0建设说明》（V1.01 合并版）；授权依据 `docs/PERMISSIONS.md`；实际 API 依据当前 router/Service 和 `docs/API_CONTRACT.md`。
- 业务 ID 是字符串；列表分页字段为 `items/page/pageSize/total`，成功信封为 `{data,requestId}`；错误信封包含 `code/message/fieldErrors/requestId`。
- Web 登录、刷新只接收 access token；refresh 必须由 Cookie 发送，前端不读取或保存其值。access 不写 localStorage、sessionStorage、URL 或日志。
- 业务权限由 `/me.permissions` 影响导航与按钮；后端仍独立校验。`403` 展示无权限，`404` 展示不可见或不存在，`409` 提示刷新后重试。
- W0 只实现任务只读工作流；不预置假的管理审核、系统配置或周报入口。首页和菜单不把角色名称代替权限码。
- 当前已有无关未提交后端与文档改动；实施时只暂存 W0 文件。浏览器验收必须用隔离测试库和测试账号，不操作业务数据。

---

## 文件边界

- `apps/admin-web/src/api/http.ts`：唯一通用 JSON 请求与刷新逻辑，导出 `request<T>`、`setAccessToken`、`clearAccessToken`。
- `apps/admin-web/src/api/auth.ts`：登录、刷新、当前用户、登出接口。
- `apps/admin-web/src/api/tasks.ts`：任务列表和详情接口；DTO 保留服务端字符串 ID、中文状态及逾期考核字段。
- `apps/admin-web/src/stores/session.ts`：Pinia 的当前用户、登录状态、权限集合；不放业务列表。
- `apps/admin-web/src/router/index.ts`：登录守卫与页面权限元数据。
- `apps/admin-web/src/views/LoginView.vue`、`AppShell.vue`、`TaskListView.vue`、`TaskDetailView.vue`：各页面仅负责交互和呈现。
- `apps/admin-web/src/components/TaskStatusTag.vue`：当前状态与截止时考核分别显示。
- `apps/admin-web/src/api/*.test.ts`、`src/router/*.test.ts`、`src/views/*.test.ts`：测试契约、权限和核心可见行为。

### Task 1: 创建可构建的 Vue 工程

**Files:** Create `apps/admin-web/package.json`、`src/main.ts`、`src/App.vue`、`vite.config.ts`、`tsconfig*.json`、`index.html`；不修改后端。

**Interfaces:** 输出 `npm run dev`、`npm run build`、`npm run type-check`、`npm run test:unit`；开发代理 `/api` 指向本地 FastAPI，生产打包使用相对 `/api/v1`。

- [ ] **Step 1:** 在仓库根目录运行 `npm create vue@latest`，项目目录为 `apps/admin-web`，选择 TypeScript、Vue Router、Pinia、Vitest；不选 SSR、JSX 或额外状态框架。安装 Element Plus，提交锁文件。版本以生成时的锁文件固定。
- [ ] **Step 2:** 删除脚手架演示视图，保留最小 `App.vue`：

```vue
<template><RouterView /></template>
```

- [ ] **Step 3:** 在 `vite.config.ts` 增加开发代理，避免业务代码写死主机地址：

```ts
server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } } }
```

- [ ] **Step 4:** 运行 `npm run type-check`、`npm run test:unit -- --run`、`npm run build`，确认空工程在开发机可构建；只暂存 `apps/admin-web` 新文件并提交 W0 脚手架。

### Task 2: HTTP 信封与 Web 会话

**Files:** Create `src/api/http.ts`、`src/api/auth.ts`、`src/api/http.test.ts`、`src/stores/session.ts`。

**Interfaces:** `request<T>(path:string, init?:RequestInit):Promise<T>` 返回 `data`；`setAccessToken(token:string):void`、`clearAccessToken():void` 管理模块内存；`getMe():Promise<CurrentUser>` 的 `permissions` 是 `string[]`。

- [ ] **Step 1:** 先写失败测试：模拟 `fetch` 返回 401，两个并发业务请求必须只触发一次 `POST /api/v1/auth/refresh`，然后各重试一次；再用 `response.bodyUsed`/请求计数验证第二次 401 不再刷新。

```ts
const [a, b] = await Promise.all([request('/api/v1/me'), request('/api/v1/me')])
expect(refreshCalls).toBe(1)
expect([a, b]).toEqual([mePayload, mePayload])
```

- [ ] **Step 2:** 测试登录使用 `credentials:'include'`，body 只有 `username/password`；响应中不期待 `refresh_token`，登出清空内存令牌。错误测试区分 `401`、`403`、`409 VERSION_CONFLICT`、`422 fieldErrors` 和 `204` 空响应。
- [ ] **Step 3:** 实现 `request`：加当前 access 的 Authorization；所有请求使用 `credentials:'include'`；仅首次 401 请求共用模块级 `refreshPromise`；刷新不经同一拦截器再次递归；刷新失败清空 access 并通知 session 进入未登录。返回 `payload.data`，204 返回 `undefined`。公开 `ApiError` 的 `status/code/message/fieldErrors/requestId`。
- [ ] **Step 4:** 实现 `auth.ts` 的 `login(username,password)`、`refresh()`、`getMe()`、`logout()`；Pinia `session.restore()` 先调用 refresh 再读 `/me`，`session.signIn()` 登录后读 `/me`，`session.signOut()` 调用登出并清本地状态。刷新请求为空 body，绝不从 JS 读取 Cookie。
- [ ] **Step 5:** 运行 `npm run test:unit -- --run`、`npm run type-check`；用隔离 API 的测试账号手动验证浏览器刷新后仍可恢复会话，跨站 Origin 被拒绝。只暂存此任务文件并提交。

### Task 3: 登录页、导航和权限守卫

**Files:** Create `src/views/LoginView.vue`、`src/views/AppShell.vue`、`src/router/index.ts`、`src/router/permissions.ts`、`src/router/permissions.test.ts`。

**Interfaces:** `canAccessRoute(permissions:readonly string[], required:string):boolean`；任务列表与详情要求 `inspection.read`。其他业务菜单待对应波次完成后注册。

- [ ] **Step 1:** 写失败测试：没有 `inspection.read` 的账号看不到任务导航且直接进入任务路由会被挡；具有该权限的账号可进入；已登录访问登录页跳转任务页。权限从 `/me` 更新后重新计算，不缓存角色推断。

```ts
expect(canAccessRoute(['inspection.read'], 'inspection.read')).toBe(true)
expect(canAccessRoute(['statistics.read'], 'inspection.read')).toBe(false)
```

- [ ] **Step 2:** 登录表单提供账号、密码、提交中/错误提示；错误只显示服务端可展示消息，不渲染 HTML。AppShell 显示当前用户名和已授权菜单，登出后跳登录页。
- [ ] **Step 3:** 路由初次加载等待 `session.restore()`；权限不足的菜单隐藏、深链导航进入 403 页面。`403` 是 UX，所有业务 API 仍依赖后端授权。
- [ ] **Step 4:** 运行单测、类型检查和构建；浏览器切换教师/负责人测试账号，确认菜单随权限变化。只暂存本任务文件并提交。

### Task 4: 只读任务列表与详情

**Files:** Create `src/api/tasks.ts`、`src/api/tasks.test.ts`、`src/views/TaskListView.vue`、`src/views/TaskDetailView.vue`、`src/components/TaskStatusTag.vue`、`src/views/TaskListView.test.ts`。

**Interfaces:** `listTasks(query:{page:number;page_size:number;semester_id?:string;inspection_date?:string;week_no?:number;inspection_type?:string;include_canceled?:boolean})` 调用 `GET /api/v1/inspection-tasks`；`getTask(id:string)` 调用详情。状态直接使用 API 的 `status`，不根据日期在浏览器计算。

- [ ] **Step 1:** 先写 DTO/交互测试：列表只发送后端实际支持的筛选参数；分页变化请求下一页；点击详情保持字符串 ID；`已逾期` 任务若 `deadline_assessment` 有历史结算则同时展示两者。服务端返回 404 时呈现不可见提示，不显示旧任务缓存。

```ts
expect(query).toEqual({ page: 1, page_size: 20, semester_id: '12', include_canceled: true })
expect(task.id).toBe('9007199254740993')
expect(task.status).toBe('已逾期')
```

- [ ] **Step 2:** 任务列表展示周次、日期、节次、班级、课程、受派人、当前状态与异常人数；后端 DTO 若没有可证明的异常人数，展示 `—`，不得伪造 `0`。加入分页、加载、空状态及错误重试。
- [ ] **Step 3:** 详情展示名单快照、当前截止时间、独立的截止考核、`lock_version`（仅供后续写入使用）；权限不包含名单读取时不请求 `/students`。不在该任务加入分配或取消按钮。
- [ ] **Step 4:** 运行单测、类型检查、生产构建，并以隔离 MySQL + 不同角色账号完成 Web 浏览器只读流程；记录请求/响应与权限边界。只暂存本任务文件并提交。

## W0 出口与后续

出口是“管理员能登录、刷新、按权限查看真实任务”，而非全管理端完成。必须有真实浏览器的 Cookie/CSRF、刷新、权限撤销、分页及任务详情证据；仅 Vitest 通过不算联调。W1–W5 的独立工作流、后端缺口和产品边界见 `docs/ADMIN_WEB_ROADMAP.md`。
