# 后端与 Web 统一发布验收

2026-10-14，合并独立历史 `efa62b5`（OSS、单次异议审核）与 dev-main 的学院底座、照片和北京时间修复。原 D 盘工作区未提交文件未覆盖。小程序同步见独立记录，未发布微信版本。

## 最终发布

- 后端/Web：`20261014-unified`，公网 `https://course.zsitai.xyz/`。
- 唯一 head：`f26a1014m001`，汇合 `f26a1013c002` 和 `181729fc7239`，不改旧迁移历史。
- 后端包 SHA-256：`aa21dea8cf387fab8e23764fbec00e6a09b8789f4c926442bfa00b8f3cde8d8c`。
- Web 包 SHA-256：`09dce8b00ea430eaa08bbcc04e7cd50ecdb596a115d5a13092f7be04c1c5c3d2`。
- 完整后端源码及 Vite 构建上线，结束分叉热修复发布方式。保留旧 hashed 资源以兼容已打开页面，新入口使用新构建。
- 两个学院开关保持关闭，生产仍 local 存储。新表授予运行账号限定 CRUD，审计 UPDATE 与运行账号 DDL 仍拒绝。

## 验证

- 后端完整单元测试 263 passed、四个依赖/配置弃用警告。唯一 head 回归先失败，再新增无操作 merge revision；另验证分支限定回退路径。
- Web 类型检查和构建通过，12 个 Web 回归及两个小程序同步回归通过。保留已有 Vite 警告。
- OpenAPI 130 路径/162 操作；既有 inspection alias operation ID 警告未隐藏。
- 独立临时 MySQL 容器使用生产同镜像摘要、独立 loopback 端口及限额内存。升级、候选启动、分支回退、旧应用启动、原数据一致均通过，容器及匿名卷已清理。
- 演练证据：`/opt/course-management/rehearsals/unified-bde395d4236a/result.json`。旧数据升降前后 SHA-256 均为 `a2ae9ccd488a8c4e56bb6ef115582d29dfc7bda31612d19f9295cbcc5663c2b1`。
- 生产内外 readiness、匿名 401、一次审核路径、废弃初核标记、关闭学院开关、运行账号新表读取、真实本人照片关联和签名下载通过；公网 HTML/入口资源字节与发布文件相同。
- 服务器 `UNIFIED_RELEASE.json` 保存发布结果，候选 `manifest.json` 保存逐文件摘要。

## 异常与恢复

早期共享实例演练发现 merge 降级留下学院分支，已补限定分支降级。随后测试客户端连接等待造成生产 readiness 一度超时；停止本次等待驱动/客户端后恢复，没有重启数据库或迁移生产库。根因未确认，不能归因于 MySQL 自身缺陷。改独立容器后完整通过；共享演练的两个明确测试库和账号也已清理，生产健康正常。

首轮正式发布静态检查因文本读取归一化 CRLF 误判，自动回退应用。改用原始字节比较，并对分布在不同 chunk 的审核 URL/权限分别检查后重发通过。新增 schema 保留，旧应用兼容，未恢复或重放生产业务事实。

## 备份及回退

- 迁移前备份：`/var/backups/course-management/20261014T070455Z.0nG8fD`，head `181729fc7239`。
- 重发前备份：`/var/backups/course-management/20261014T070658Z.WK0NTD`，head `f26a1014m001`。
- 旧应用指针：后端 `/opt/course-management/releases/20261014-photo-time-r2`，Web `/opt/course-management/admin-web/releases/20261014-photo-time-r2`。
- 优先只回退应用并保留扩展列/配置表，不能用旧备份覆盖发布后业务事实。若数据库必须降级，先停写核对：merge 降到 `181729fc7239`，再限定学院分支降到 `f26a1013c002@b2c3d4e5f6a7`。启用学院业务后不能照搬空配置降级。

工具 `rehearse_unified_isolated.py`、`deploy_unified_20261014.py`、`verify_unified_20261014.py` 绑定本次明确基线和目标，不作为无审核通用脚本重跑。后续破坏性升降演练优先独立数据库进程。

未执行微信编译/真机或完整登录后浏览器交互，不宣称多学院全链路隔离、灵活作息和组织排班完成。小程序全量 Node 仍有 30 failed、1 cancelled；详见 [开发者变化清单](../integration/WECHAT_DEVELOPER_CHANGES_20261014.md)。

## 用户授权的临时线上例外

统一发布完成后，最终源码核对发现 `backend/app/modules/inspection/service.py` 另有临时提前提交补丁。已核对另一会话“简化考勤异议为一次审核”的直接用户指令：开发期间只在服务器关闭后端日期限制，不修改远端代码；随后明确“只用动后端限制”。因此不覆盖、撤销或同步这段临时补丁入 Git。

当前运行进程 `CM_DEV_ALLOW_EARLY_SUBMISSION=1`，来自 systemd 临时配置而非主 backend.env。它仅绕过未来日期限制，身份、当前受派及取消任务守卫仍保留；小程序客户端门禁不变。正式源码及正式契约继续禁止提前提交。服务器恢复脚本为 `/var/backups/course-management/dev-early-submission-20261014T072349Z/restore.sh`，测试结束由用户要求恢复。

因此“统一发布来源”不代表此刻线上逐字节等于 Git：只有该文件的已核对临时测试补丁属于有意差异。服务器发布证据记录基线源码摘要、例外实际摘要、启用状态及恢复路径，不能把整体 `source_snapshot_matches` 标成 true。原 D 盘工作区还在另会话开发学籍等业务，未覆盖或发布其未提交修改。
