> 归档说明（2026-10-24）：原路径 `docs/development/AUDIT_LOG_VIEWER_RELEASE_20261020.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 全校操作日志查看页发布记录

2026-10-20，北京时间 23:52 成套切换后端与管理端两处指针。无迁移、无 seed、无运行配置与业务开关变更、无业务数据写入，小程序未发布。

## 范围

- 后端：审计读取投影补齐操作者姓名与账号名（`AuditReadService._actors`，一次批量查询本页 actor_user_id），详情补 `reason`；全局列表 `page_size` 默认 50。账号已注销时投影为 `null`，不再让整页失败。
- 管理端：新增 `/dashboard/audit`「操作日志」页（日期窗口、动作、对象类型与对象 ID 筛选、字段级前后值抽屉）。刻意使用原始 `request` 而非 `workspaceHttp`，避免 `business_scoped` 打开时把全校入口静默改写成当前学院。
- 管理端：账号与权限文案统一为「超级管理员」角色 + 「管理员／平台管理员」两档能力，角色标签表收敛为 `role` 表真实存在的五个角色。

## 版本

- 应用源码提交：`b29b3ebee29fb3aeadd7ee4c737d421883f9a421`（`b29b3ebee2`），已推送 `origin/dev-main`。该提交是 `12801b3` 主干与本批三个提交（`c9cf4f5`、`341d58a`、`785fcd0`）的合并结果。
- 后端与 Web 发布名均为 `20261020-audit-viewer-b29b3ebee2`。
- 发布前指针（两处相同）：`releases/20261020-pagination-563cf0bc38`、`admin-web/releases/20261020-pagination-563cf0bc38`，目录保留。
- 发布包：`/var/tmp/cm-audit-viewer-b29b3ebee2-inputs/`，`backend.tar.gz` SHA-256 `5a56b1f722687ab5ace5a9e045f5432e3eaadb72081be1e847c491954e905c99`，`web.tar.gz` SHA-256 `9cb7dfcf9019e5fa6ac24fa63bb10a4363958453b9c00a1d4a9226e6f9c66450`；本地与服务器分别计算，逐字节一致。
- 数据库版本保持 `f26a1019s007`；`/etc/course-management/backend.env` SHA-256 `e906579e…f53163`，切换前后一致。
- 发布器复用上一批的成套发布脚本（候选探针 + 失败自动回退 + `rollback.py`），仅改发布名、候选单元名、候选端口 `18032` 和探针路径；输入与脚本副本存于 `/var/backups/course-management/20261020-audit-viewer-b29b3ebee2/`。

## 发布前源码漂移核对

以 `git archive` 产出发布包，与线上旧发布的 `RELEASE.json` 清单逐文件比对：

- 线上清单 542 键，本次后端 541 个 `backend/` 文件全部存在对应项，`only in mine: []`，即线上没有只在服务器上、仓库里缺失的文件。
- 内容差异 3 个：`backend/app/modules/audit/service.py`（本批改动）、`backend/tests/unit/test_scoped_audit.py`（本批改动）、`backend/tests/unit/test_list_pagination.py`（`12801b3` 仅测试格式提交，线上尚未包含）。应用运行源码相对线上只变化审计服务一个文件。

## 验证

- 发布前门禁：`npm run build`（含 `vue-tsc`）通过；`node --test tests/*.test.mjs` 134 项中 129 通过、5 失败；`pytest tests/unit` 799 通过、16 失败；`mypy app` 61 项、`ruff check app tests` 若干——全部为合并前既有失败，见下节。本批自身用例全绿：`tests/unit/test_scoped_audit.py` 2 项、管理端 `audit-log`/`accounts`/`college-admin-scope`/`transition-root-invariant` 共 13 项。
- 候选实例以 `course-management` 用户运行于 `127.0.0.1:18032`，`/health/ready` 就绪后匿名探针 7 条全部 401：`/api/v1/me`、任务分页与导出、学院志愿者组学期摘要、`/api/v1/audit-logs`（含时间窗）、`/api/v1/audit-logs/1`、`/api/v1/colleges/1/audit-logs`。
- 成套切换后正式服务 `course-management` 为 `active`，同一组探针在 `127.0.0.1:8011` 复核为 401；独立核对 585 个后端/工具文件与 72 个 Web 产物 SHA-256 匹配发布清单；`nginx -t` 通过。
- 公网核对：`/health/ready` 200 且 `database: up`（`remote_ip=101.34.52.163`）；`index.html` 为 `no-store` 且其 SHA-256 与本地构建一致（`d9203fc6…d526`）；入口 chunk `assets/index-DxpPQQm3.js` 200（1088137 B）；新页 chunk `assets/AuditLogView-B9N5hsX5.js` 200；`/api/v1/audit-logs` 带时间窗匿名返回 401 而非 404。
- 旧页签不失效：上一版 chunk `assets/index-D4crFopM.js`、`assets/index-D7noPouE.js` 仍 200；新 Web 发布目录 assets 260 个（旧目录 211 个已带过来，哈希同名者不重复覆盖）。
- 未验证：没有真实登录凭证，未做登录后「操作日志」页的实际点击与筛选验收，也没有用生产数据核对 `actor_name`/`actor_username` 的真实投影结果；这两项需人工登录管理员账号确认。未做容量测试。

## 既有失败门禁的归属（本次未引入，也未修复）

- 管理端 5 项失败全部在 `tests/workspace-pages.test.mjs`，原因都是测试替身映射缺少新引入的组合式函数：`useDisplayPage`（3 项）、`useRoute`、`useDispatchOptions`。该测试文件自 `93c1505` 起未被任何一侧改动，失败与本批无关。
- 后端 16 项失败为共有历史：在合并基线 `4a63c03` 的独立工作树用同一虚拟环境运行完整 `tests/unit` 得 18 失败 / 784 通过，本次主干为 16 失败 / 799 通过——主干新提交修好了其中 2 项（`test_scoped_authorization_lifecycle` 两项），没有新增失败。HEAD 与 `origin/dev-main` 的后端差异只有本批的审计两个文件，因此这批失败不来自本批。
- 其中 `test_campus_configuration.py` 的 5 项是学院范围断言（教师可见非本学院课程类型），`test_permission_policy.py` 的 2 项是权限码数量与默认矩阵期望，需要单独一批来判断是实现缺陷还是测试期望过期，不应通过放宽断言制造全绿。

## 回退

```bash
ln -sfn /opt/course-management/releases/20261020-pagination-563cf0bc38 \
  /opt/course-management/current.audit-rollback
mv -T /opt/course-management/current.audit-rollback /opt/course-management/current
ln -sfn /opt/course-management/admin-web/releases/20261020-pagination-563cf0bc38 \
  /opt/course-management/admin-web/current.audit-rollback
mv -T /opt/course-management/admin-web/current.audit-rollback /opt/course-management/admin-web/current
systemctl restart course-management
```

备份目录内的 `rollback.py` 需显式 `--apply`，会先核对两处当前指针确属本次发布再回退。只回退应用，数据库版本 `f26a1019s007` 无需处理（本次未执行迁移）。
