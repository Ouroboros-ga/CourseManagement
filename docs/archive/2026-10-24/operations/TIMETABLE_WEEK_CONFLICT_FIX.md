> 归档说明（2026-10-24）：原路径 `docs/development/TIMETABLE_WEEK_CONFLICT_FIX.md`。本文保留当时的修复、验证与发布记录；历史版本和待验收项按当时语义理解，当前进度见[实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 课表周次冲突误判修复

## 问题与行为

旧确认集合以班级、课程、星期、节次识别课表条目，缺少周次；同一文件内不重叠的单双周或分段周次也可能被报成“多个文件修改同一条资料”。此外，来源行号不同会使相同安排被视为内容变化。

修复限定于后端确认差异与冲突规划：

- 条目标识增加排序去重后的周次集合；课表冲突统一按同一教学班的实际周次交集、星期和节次区间核验。
- 同一普通/网格文件的相同业务安排只应用一次，返回可见 warning；不把教师、教室或周次不同的资料当作重复。
- 真正重叠继续拦截，提示课程、交集周次、星期、节次和另一个来源文件/行号；其他实体的跨文件拦截、授权、来源修订及原子事务保持原规则。
- 无新增接口字段、数据迁移、前端或小程序改动，不自动导入真实资料。

## 实施与验收

先新增 6 个失败用例复现单/双周、分段周次、重复来源行、真实重叠及跨文件分段导入，再实现修复；另补教师/教室不同不能去重的两个保护用例。

使用用户提供的 `班级课表(24-26级)` 目录中 32 份 `.xls`，在独立 SQLite 库创建隔离资料，使用与目标服务器一致的 1—12 节口径：

- HEAD 基线出现 23 条阻断，修复后全部文件通过确认集合核对。
- 确认保存 471 条上课安排；重新上传并确认仍为 471 条，无重复新增。
- 原始文件只读，真实教务内容未提交 Git，也未导入服务器业务库。

自动回归入口：`backend/tests/unit/test_import_schedule_conflicts.py`，覆盖上述 8 个场景并实际验证保存结果。其余相关导入、选修课、人员关联及解析测试一同复验。MySQL 使用本机回环独立实例中新建的随机 `*_test` 库，执行完清理该测试库及账号。

本次结果：新增 SQLite 回归 **8 passed**；独立 MySQL 8.4.11 回归 **8 passed**，已清理本轮测试库/账号并关闭测试实例。定向 ruff、mypy 与 `git diff --check` 通过。

较广测试以只读 HEAD（`4b02382`）快照和当前工作区同环境、同顺序对照：基线 **63 passed / 1 failed**，当前加入本次 8 项后为 **71 passed / 1 failed**；JUnit 失败集合完全一致，唯一既有失败为 `test_importer_course_type.py::test_bulk_import_with_course_type`，没有修改或跳过该用例制造全绿。

发布目标为 `101.34.52.163` / `test.zsitai.xyz`，采用备份、候选服务验证、后端指针切换、就绪/匿名授权/哈希检查和旧版本保留流程；保留该服务器既有健康检查及跨云存储适配。本次不执行数据库迁移或 seed。

## 发布记录（2026-10-19）

- 功能提交 `98966f4a3e3d9909d58fa863e43b8a2db04f0352` 已推送 `origin/dev-main`。
- 后端 current 已切换到 `/opt/course-management/releases/20261019-import-weeks-98966f4a3e`；旧版本 `/opt/course-management/releases/20261019-staff-onboarding-a6db3fe47c` 保留。
- 数据库保持 `f26a1019s007`，未执行迁移或 seed。发布前后均为 32 个行政班、1053 名学生、0 条正式课表、0 份教职工档案，未替用户导入原表或生成身份。
- 独立核验 538 个运行文件 SHA-256 通过。服务器原有健康、配置和存储适配三文件哈希与之前发布一致；Web 指针及环境配置指纹未变。
- 候选服务 `127.0.0.1:18022`、正式服务 `127.0.0.1:8011` 就绪检查通过；从本机通过 TLS 并定向测试服务器 IP 检查 `https://test.zsitai.xyz/health/ready` 成功，数据库为 up。匿名 `/api/v1/me` 及教职工查课记录接口均为 401。`nginx -t` 通过。
- 公网首页哈希 `17b7efa4abf2f9387427326b2d4e7b9ba3582750c2cc272e16c838c4f5a75c6e` 与原 Web 一致。入口脚本仍为 `/assets/index--aqYh9bv.js`，服务器 SHA-256 为 `0db28df85130a65375f1cdc31dae34994e40373c70ea7f6c78962e146723a6d0`。

备份：`/var/backups/course-management/20261019T125444Z.mqgmEv`，包含数据库/文件/配置/旧指针，以及 `deploy_import_weeks.py`、`manifest.json`、`report.json`、`verify_live.py`、`rollback_release.py`；原备份 `SHA256SUMS` 与发布证据 `RELEASE_SHA256SUMS` 已验证。

如需回滚，脚本仅在当前仍为本次版本时切回原临时工号功能版本并重启、检查就绪；不恢复或降级数据库，不改 Web 和配置。已检查脚本前置条件和用法，未实际执行回滚：

```bash
/opt/course-management/current/backend/.venv/bin/python \
  /var/backups/course-management/20261019T125444Z.mqgmEv/rollback_release.py --apply
```

用户测试时刷新测试入口，并重新读取原始课表进行核对确认。旧的失败预览可以移除后重传，不需要合并或编辑单双周/分段周次原表。上述 471 条为隔离验收结果，正式库仍等待用户确认导入。
