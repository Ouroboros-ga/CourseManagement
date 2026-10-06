# Web 管理端首次发布

2026-09-30，访问入口 `https://course.zsitai.xyz/`。Vue 静态产物由 Nginx 提供，`/api/` 与 `/health/` 继续代理原 FastAPI 服务，不新增 Node 生产进程、不修改业务库。

## 发布内容

用户推送已核实：`a538e1b` 为后端/小程序/部署基线，`eadecba` 为管理端基线。本次在 `eadecba` 的工作区基础上追加三处上线修复：生产未登录跳转 `/login`、清空预填账号密码、补齐 Vite 环境类型声明。修复和 Nginx 静态部署配置尚未提交或推送，本轮未操作 Git 提交。

生产构建 `npm.cmd run build` 通过，构建前后源码 SHA256 无变化，源码记录 `tmp/deployment/admin-web-source-20260930.json`。静态包 `tmp/deployment/admin-web-20260930-01.tar.gz`，SHA256 `2174c7533b5c0206b9287cf05030a381d45407bebfc400210920aa9fd7eeb0d1`，上传后摘要匹配。

服务器版本目录 `/opt/course-management/admin-web/releases/20260930-01`，指针 `/opt/course-management/admin-web/current`。目录 0755、文件 0644，Nginx 可读；前端与后端版本独立。原 Nginx 配置保存在 `/etc/course-management/course-management.conf.before-admin-web-20260930`。

API 使用同源相对路径，正式 Cookie 仍为 Secure/HttpOnly；本地 Vite 代理不进入生产产物。SPA 深链接回退到 index.html，HTML 不缓存，带哈希的 assets 缓存一年；未知 API 与缺失 assets 返回 404，不回落 HTML。

## 验收

- 生产登录保护测试先在原版本失败，修复后通过；登录输入框无预填凭证。
- 公网 Playwright/Edge：深链接访问跳转登录、账号登录、刷新恢复会话、Secure/HttpOnly Cookie、登出后跳转登录通过。Browser 插件未提供，使用已有 Playwright 和本机 Edge，无额外浏览器安装。
- 登录页和工作台截图已检查，未发现空白页、框架报错或资源加载失败。截图在 `tmp/deployment/admin-web-cloud-login.png`、`admin-web-cloud-dashboard.png`。
- 后端 HTTPS 冒烟再次通过：ready/live、未登录 401、登录、认证读取、非法 Origin 403、刷新、登出、文档关闭。
- Nginx 配置检查通过，未知 API 和 assets 404，HTML no-store、assets 正确 JS 类型及缓存。

## 功能边界

这是当前管理端工作台的部署，不能视为全部管理功能完成。排班、审核、周报等页面仍存在演示数据和模拟操作，业务 API 的完整端到端联调尚未完成；页面上的人数、课次、到课率等原型数字不代表正式数据库事实。不要据此认定任务已真实下发或审核已落库。

登录和会话链路使用正式后端。已联通的业务接口会实际影响正式数据库。本轮浏览器测试只登录、读取、刷新和登出，没有下发任务或修改考勤。

主 JS 约 1.06MB（gzip 约 350KB），Vite 提示 chunk 超过 500KB；构建没有报错。后续可按实际使用拆分 UI 依赖，不在首次部署中大改前端结构。

## 回退

首次静态发布无更早 Web 版本；恢复备份的 Nginx 配置，执行 `nginx -t`，通过后 `systemctl reload nginx` 即可回到只提供 API 的状态。保留当前前端版本目录，后端与数据库无需回退。后续前端发布切换 admin-web/current 指针，旧版本保留用于回退。

微信登录仍按用户决定关闭，校园应用及 PostgreSQL 仍保持停用。
