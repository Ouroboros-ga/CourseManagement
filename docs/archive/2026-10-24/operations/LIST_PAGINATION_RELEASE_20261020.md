> 归档说明（2026-10-24）：原路径 `docs/development/LIST_PAGINATION_RELEASE_20261020.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 统一分页与查询优化发布记录

2026-10-20。用户确认正式域名 `course.zsitai.xyz` 已指向新服务器 `101.34.52.163`，测试域名已删除；本次正常 DNS 查询确认该解析。不再把新服务器标记为测试环境，旧文档中的测试入口只描述当时发布。

## 版本和范围

- 分页功能提交：`dc4b836`。已合入其他任务的最新主干更新，保留教职工临时工号、课表周次冲突修复、导入类型修复、报表视图和账号文案。
- 应用源码提交：`85c9dc547bc8c86d536b38b449637580a13a4415`，已推送 `origin/dev-main`。
- 后端与 Web 发布名均为 `20261020-pagination-85c9dc547b`，上线时间为北京时间 2026-10-20 17:55。
- 后端指针：`/opt/course-management/current` → `/opt/course-management/releases/20261020-pagination-85c9dc547b`。
- Web 指针：`/opt/course-management/admin-web/current` → `/opt/course-management/admin-web/releases/20261020-pagination-85c9dc547b`。
- 数据库版本保持 `f26a1019s007`；没有迁移、seed、业务数据导入、运行配置或业务开关变更。小程序未发布。

功能和保留的全量业务计算边界见 [查询审查](../../../development/LIST_PAGINATION_QUERY_AUDIT_20261020.md)。发布后的文档提交仅记录证据，不改变这次应用源码及 Web 构建。

## 验证

- 整合最新主干后：60 项后端定向用例、31 项前端用例、Web 类型检查与生产构建通过；7 组完全模拟 API 的浏览器流程通过。保留原有大 chunk 提示和依赖弃用告警。
- 发布前核对旧后端 538 个运行清单文件，无源码漂移；已入库的服务器兼容补丁包含于本次源码包。复制独立虚拟环境并修正启动器，依赖锁文件与原环境一致。
- 候选服务在 `127.0.0.1:18031` 验证就绪后成套切换，正式服务 `course-management` 为 active。独立核对 542 个源码/工具文件和 70 个 Web 产物 SHA-256，均匹配发布清单。
- 正常公网域名 `/health/ready` 返回 200；`/api/v1/me`、`/api/v1/inspection-tasks/export` 匿名返回 401。内网另核对任务分页和组织摘要路由匿名为 401。
- 公网 `index.html` 与其引用的 3 个入口资源哈希匹配本次构建；`nginx -t` 通过。配置指纹、迁移版本和两处发布指针独立复核一致。
- 没有使用真实登录凭证遍历业务列表，没有执行生产容量测试或宣称线上提速比例。默认 50 条、过滤和跨页选择的行为由上述定向用例及模拟交互覆盖，不将匿名 401 当作已登录业务验收。

## 回滚与证据

私有备份目录：`/var/backups/course-management/20261020-pagination-85c9dc547b`。保存前后状态、旧运行清单、发布清单、部署脚本、受限配置备份和 `rollback.py`。配置备份仅 root 可读。

- 原后端：`/opt/course-management/releases/20261019-import-weeks-98966f4a3e`。
- 原 Web：`/opt/course-management/admin-web/releases/20261020-hide-college-time`。
- 发布器失败会成套恢复旧指针并重启服务；本次成功，没有触发回滚。
- 人工回滚脚本需显式 `--apply`，同时核对当前两处指针属于本次发布；只回退应用，不恢复或降级数据库。自动审批拒绝了回滚脚本的预览执行，后续只读核对脚本语法、显式参数守卫和旧目录，未执行回滚脚本。
- 当前两个发布目录均有 `RELEASE.json`；备份目录的 `report.json` 保存候选/正式授权状态、部署时间和文件核对数量。

本地完整发布输入及模拟浏览器记录位于被 Git 忽略的 `tmp/pagination-20261020/`，不包含生产凭证或真实学生名单。
