# 管理端开发

服务入口：`https://course.zsitai.xyz/`。生产构建由 Nginx 提供，页面和 API 同源。当前重构方向见[总体设计](../../docs/development/CAMPUS_PRODUCT_ARCHITECTURE_WEB_REDESIGN_20261015.md)，进度见[实施状态](../../docs/development/IMPLEMENTATION_STATUS.md)；[首次发布记录](../../docs/archive/2026-10-15/operations/ADMIN_WEB_DEPLOYMENT_20260930.md)已归档，不能代表当前页面或部署完成情况。

```powershell
cd "D:/My project/CourseManagement/apps/admin-web"
npm.cmd run dev
```

打开 `http://127.0.0.1:3000`。当前 `vite.config.ts` 默认将 `/api` 和 `/health` 代理到 `http://127.0.0.1:8000`；`BACKEND_URL` 可覆盖目标。页面写操作作用于实际代理后端，启动前确认目标环境。

当前开发代理将本地合法 Origin 改写为本地后端 Origin，并移除响应 Cookie 的 Secure 以支持本地 HTTP；正式环境仍使用同源 HTTPS。若需要代理云端，须核对后端来源校验，不能只设置地址就推断登录已联通。以配置源码为准。

3000 端口被占用时启动直接报错，避免端口变化导致来源校验不一致。开发服务器仅监听 IPv4 回环地址，不开放局域网访问。正式部署应由 Nginx 同源代理 `/api`，`vite preview` 不使用此开发代理。

教学助手侧栏为默认关闭候选：`VITE_AGENT_CHAT_ENABLED=false`，见 [.env.example](.env.example) 和[功能及本地QA](../../docs/development/AGENT_MANAGEMENT_CHAT_UI_20261025.md)。入口变量在构建时读取，不能替代后端开关、迁移及真实腾讯云验收。
