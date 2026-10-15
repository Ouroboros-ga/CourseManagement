> 历史归档：2026-10-15 整理。原路径：`docs/development/OSS_IMPLEMENTATION_PLAN.md`。本文保留当时的设计、版本或验收证据，不作为当前实施指令或线上状态。当前资料见[文档导航](../../../README.md)及[最新总体设计](../../../development/CAMPUS_PRODUCT_ARCHITECTURE_WEB_REDESIGN_20261015.md)。正文中的历史日期、命令和测试数字保留原语义。

# OSS 后端与 Web 接入计划（2026-10-13）

目标：以 ECS RAM 角色读写上海私有 OSS 桶，保留业务文件 ID、上传校验和授权；Web 预览支持短期链接刷新。由 GPT 在本会话直接执行，不委派、不部署、不修改生产数据。

架构：后端代理上传与下载，StorageBackend 实现 OSS save/read/delete/exists；local 与 object 共用应用 HMAC 下载签名。客户端不获取 OSS 凭据，也不依赖桶域名。同步 SQLAlchemy 和 OSS 调用在同步路由线程池运行。

约束：保留工作区已有差异；默认 local；启用 object 必须填写 bucket/region/HTTPS endpoint；不自动切换线上配置。已有文件迁移必须先核对、备份、复制验证后再切换，不能把新适配器视作已迁移。

- [x] 后端：先补 OSS 配置、读写删除、错误与下载签名的失败用例，再实现适配器及配置验证，锁定官方 SDK 依赖。
  - 文件：backend/app/core/config.py、backend/app/modules/file/{storage,service,router}.py、backend/tests/unit/test_oss_storage.py、backend/pyproject.toml、backend/uv.lock。
  - 契约：保留 POST /api/v1/files、GET /api/v1/files/{id}/access 和 download 响应；无签名验证器拒绝下载；上游故障返回脱敏 503。
- [x] Web：提取文件 API 和短期链接缓存；证明预览切换、点击和打开原图重新检查有效期；上传复用现有串行刷新客户端。
  - 文件：apps/admin-web/src/api/files.ts、src/composables/useFileAccess.ts、src/views/ObjectionsView.vue（只改文件预览相关增量）、tests/files.test.mjs。
  - 回归：有效期、并发请求合并、失败重试、清空后旧请求不可回写；FormData 上传不设置 JSON Content-Type。
- [x] 文档：OSS 配置与切换/回滚步骤、小程序上传/访问示例、域名与凭据边界；同步 API_CONTRACT、API_INDEX；文件三个端点 OpenAPI 路径结构与现有快照相同，未重新生成整个仓库快照。
- [x] 验证：定向测试后执行后端 unit、ruff/mypy、Web build 和文件客户端 Node 回归；浏览器以模拟接口验证预览与过期刷新。记录全库失败与真实云端未验收边界。

云端验收：RAM 角色实际绑定、桶私有、测试图片上传后桶中存在、有权限访问/无权限拒绝、伪造与过期签名拒绝、删除可重跑、报表可读；当前任务没有生产部署授权，云端验收待部署时执行。

## 本次验证结果

- 后端全体 unit：201 passed，2 条依赖弃用警告；包含 12 项新增 OSS/文件 HTTP 回归。
- 本次修改的后端 config/file 和新增测试：ruff 通过；config/file 定向 mypy（follow-imports=silent）通过，10 个源文件。
- 全库 ruff：167 项问题；全库 mypy：33 项错误，位置在报表、导入、考勤、查课等模块，不能声称全库静态检查通过。本次未修这些模块。
- Web 文件 Node 回归：3 passed；npm.cmd run build 通过，保留原分包/体积告警。
- 浏览器：Browser 插件未列出，采用已安装 Playwright + Edge。独立模拟 API 和健康检查，实际证明面板灯箱打开、有效期后重新申请链接（2 次 access）、无控制台错误。证据：tmp/oss-web-qa.cjs、tmp/oss-web-qa.png。
- Alembic：单 head b2c3d4e5f6a7；没有模型变更或新增迁移，没有操作任何数据库迁移。
- 本次跟踪文件 diff --check 通过；全工作区仍有原有 apps/wechat-miniapp/miniprogram/pages/task/detail/index.wxss:160 末尾空行，未改动它。
- 未部署、未切换现有 .env、未提交/推送、未迁移、未访问真实 OSS；MySQL 集成与微信真机未运行。
