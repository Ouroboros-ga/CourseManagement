# OSS Web 直连下载实施与验收

目标：仅改后端、服务器与 Web；上传仍经后端验内容和落库，小程序不修改，默认 `/files/{id}/access` 保留应用签名下载。

基线：`29b3f5c`，本地 detached HEAD；未跟踪的远程附件不纳入提交。线上后端 `20261021-wechat-rebind-6f4299bd78`、Web `20261021-staff-binding-export-145dfe8fc1`，存储模式 local（本轮只读核对）。

## 架构与约束

- Web 显式请求 `delivery=direct`；默认 `proxy`。FileService 先校验原资源范围和文件状态，再选择链接，不新增访问权限。
- `OSS_WEB_DIRECT_ENABLED` 独立控制，未启用或 local 模式返回原代理链接；启用后只为图片签发公网 OSS V4 GET 链接。报告、非图片继续代理。
- 签名有效期最多 300 秒，且不超过文件保留截止时间；服务端使用准确的签名到期时间。强制正确 MIME 和 `private, no-store`，禁止暴露长期凭据或记录签名 URL。
- 公网签名客户端与服务器可用内网客户端分开；不使用域名字符串替换签名，不接受客户端提供桶、路径、来源或任意目标域名。
- 存储切换前，逐项复制数据库已登记且未清理的文件，核对大小和 SHA-256；保留本地副本。切换后的新上传同步保留本地镜像，保障应用及配置回退后文件仍可用。失败不能伪报上传成功。
- Web 继续使用短期内存缓存，过期重新获取；图片失败提供有界重试，不无限刷新。CSP 仅增加本次确定的桶 HTTPS 来源；OSS CORS 仅添加正式 Web Origin 的 GET/HEAD，保留原规则。

## 执行顺序

- [x] 真实云端预检：合成 PNG 临时键写/读/删、匿名拒绝、签名 GET、类型/缓存检查通过；私有桶，无 CORS 配置，正式来源将在发布时添加。不输出凭据、签名或真实照片。
- [x] 测试先行：SDK 原生签名/公网 endpoint/错误脱敏；默认代理兼容与 direct 越权/过期拒绝；镜像写删；Web 显式参数、到期和重试。
- [x] 实现：`backend/app/core/config.py`、`modules/file/{storage,service,router}.py`；Web `api/files.ts`、现有图片访问 composable/组件；部署预检/迁移工具及精确 CSP。
- [x] 验证：文件/权限 28 项、迁移/CORS/CSP 4 项、原下载边缘配置 3 项，Web 5 项及类型检查/构建通过；变更后端 Mypy 通过。新文件与 storage/router Ruff 通过，config/service 的三条超长行与 HEAD 一致。更新 API 契约、索引和 OpenAPI。
- [x] 发布：固定源码和产物清单，备份服务/环境/Nginx，迁移历史文件校验，隔离候选端口测试，安装精确 CSP 和 CORS，短暂停写完成最终迁移后成套切换；健康、公网资源、默认代理及直连合成图验收。
- [x] 记录：提交/推送 SHA、发布指针、文件完整性数量、回滚命令和未验收边界。

## 验收关键断言

1. 同一文件默认请求仍返回 `/api/v1/files/{id}/download`；Web direct 返回固定公网 HTTPS 桶域名，未授权仍 404。
2. 已到期/清理/未就绪不签发；OSS 异常脱敏返回 503，不泄漏签名或原始 SDK 异常。
3. OSS 合成图匿名拒绝、签名可读、过期拒绝；Web 预览不被 CSP/CORS 阻断。
4. 本地及 OSS SHA-256 全量一致，新上传具备本地镜像，失败不产生 READY 行；原数据库与考勤事实不变。
5. 小程序代码和下载接口默认行为不变；本轮不代表小程序真机直连验收。

## 执行结果

实现、本地验收和线上启用完成。真实云端发现禁止 `response-content-type` 覆盖（400 InvalidRequest），改用已校验的对象 MIME 后签名下载通过。另修复 RAM 角色分支错误地返回 Credentials 而非 SDK Client 的旧缺陷，有离线回归覆盖。

生产文件核验及迁移：9 个 READY 文件，24,909,709 字节，源大小与 SHA-256 均匹配；全部复制到私有 OSS，最终停写核对 `verified_local=verified_remote=9`，本地原件保留。迁移仅读取业务元数据和服务器上的文件，不向本机导出照片或学生名单，不写业务数据库。

Browser 插件未提供，使用捆绑 Playwright + Edge，本地 `http://127.0.0.1:3123`、1440×1000，全部虚构考勤与合成 PNG。实际编译页面验证显式 direct 请求、精确 CSP 下预览、连续 403 最多自动重试一次以及手动恢复；零页面错误和框架警告。证据在本地忽略目录 `tmp/oss-web-20261022/BROWSER_RESULT.json`，不等同真实用户照片或小程序验收。首次脚本因模拟路由 fallthrough 和中文关闭按钮定位失败，修正后完整重跑通过。

## 正式发布与启用（北京时间 2026-10-22）

- 功能源码 `f9d52c15f509cc0571f5dd6382d9272d390fb421` 已推送。14:13 成套上线后，实际服务账号完成新对象写读、本地镜像和真实公网域名图片显示/fetch；正式 CSP/CORS 下 `image_loaded=true`、GET200、`image/png`，无页面错误。所有测试对象均为合成 PNG，不创建 FileObject 或业务记录。
- 云端过期测试发现 SDK 对 1 秒有效期扣除签名前耗时再取整，可能生成 `x-oss-expires=0`，返回400。先补失败回归，再以 `2db7a2ed59d118542163b78b224c7a0904682441` 修正：不足2秒的 Web 请求沿用原应用代理；原生签名方法拒绝不足2秒参数。14:19 后端补丁发布完成，Web及环境未重发或修改。
- **当前后端** `/opt/course-management/releases/20261022-oss-ttl-2db7a2ed59`；**当前 Web** `/opt/course-management/admin-web/releases/20261022-oss-web-r2-f9d52c15f5`。分别经554个源码/工具文件、70个Web产物哈希验证，运行进程cwd指向最终后端。
- **生效开关** `FILE_STORAGE_BACKEND=object`、`OSS_WEB_DIRECT_ENABLED=true`、`OSS_LOCAL_MIRROR_ENABLED=true`。公开入口仍为 `https://course.zsitai.xyz`。默认 `/access` 仍为代理，Web显式请求direct。新文件的本地镜像必须保留到另行确认回退策略，不能当作无用备份删除。
- **CORS** 仅新增正式来源的GET/HEAD规则；桶仍private，匿名GET403。**CSP** 两个HTML入口仅增加精确桶HTTPS来源到img-src/connect-src；API原same-origin及下载路由CORP例外均保留。源站使用宝塔管理的Nginx，测试后应 `nginx -s reload`，不能用未启用的systemd nginx unit。
- 正式公网index及3个入口资源哈希、健康200、`/me`及两种access匿名401、旧下载CORP与no-store边界通过。公网Edge在真实CSP/CORS下直接读取合成图通过；5秒签名先200、等待到期后403，合成对象及本地镜像均删除。最终后端再次运行云端预检通过。
- 最终回归：文件/权限29项、迁移/CORS/CSP4项、原边缘配置3项共36项通过；Web5项、类型检查和生产构建通过。保留既有Pydantic/TestClient弃用提示与大chunk提示；未将其称为零告警。首次受限HTTP/临时目录测试挂起或失败的运行已终止，成功统计取正常权限重跑结果。
- 数据库版本保持 `f26a1019s007`，无数据库迁移、业务数据修复或小程序源码变更。本轮未使用真实登录用户逐张打开照片，也不代表小程序真机直连验收；相关资源授权由原服务逻辑及隔离HTTP回归验证。

### 首次发布回退与恢复说明

首次发布 `20261022-oss-web-f9d52c15f5` 在配置切换后，因错误使用 `systemctl reload nginx` 中止；回退脚本也在同一步中止。随后已人工执行 `nginx -t && nginx -s reload`，重启原后端，确认公网ready及原应用/Web指针恢复后，才使用独立r2目录重发。启动窗口曾观察到502，后续健康恢复及最终公网验证通过，不能声称零停机。首次目录保留 `ATTEMPT_RESULT.json` 标记失败，**不使用该目录的旧回退脚本**。

发布前还发现线上图片MIME纠偏源码及测试未更新旧清单；逐份与Git HEAD核对，确认已在本次候选中保留。归档的CRLF/LF差异按文本归一哈希校验，仅这两份已核实文件采用例外；其余源码严格逐字节校验，不覆盖未知线上补丁。

### 回退入口

环境、站点、CORS原配置及完整回退资料：`/var/backups/course-management/20261022-oss-web-r2-f9d52c15f5/`；有效期补丁回退资料：`/var/backups/course-management/20261022-oss-ttl-2db7a2ed59/`。以下命令本轮仅检查了说明模式，未对成功版本执行回退：

```bash
# 仅撤回有效期补丁：保留OSS启用及当前Web。
python3 /var/backups/course-management/20261022-oss-ttl-2db7a2ed59/rollback.py --apply

# 完整退回本地存储及本轮前应用/Web：先执行上一步，再执行以下命令。
python3 /var/backups/course-management/20261022-oss-web-r2-f9d52c15f5/rollback.py --apply
```

完整回退恢复环境、站点、原CORS及两端指针，并使用真实Nginx重载；无需回退数据库。迁移对象保留在私有OSS，本地原件及新上传镜像支持原版本继续读取，勿先删镜像。回退前仍需核对当前发布指针，若已有后续发布则重新评估，不盲目运行固定版本脚本。

本地脱敏证据：`tmp/oss-web-20261022/DEPLOYMENT_RESULT.json`、`TTL_DEPLOYMENT_RESULT.json`、`PUBLIC_EVIDENCE.json`、`LIVE_BROWSER_RESULT.json`、`CLEANUP_RESULT.json`。短期测试URL私有文件已删除，凭据与实际照片不入库。
