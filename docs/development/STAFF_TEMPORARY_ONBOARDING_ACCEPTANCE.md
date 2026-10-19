# 教职工临时工号：本地验收

验收日期：2026-10-19。基线：`dev-main` / `75d8a9a`。本文件记录本地候选状态，不表示已提交、推送或发布。

## 实现结果

- 后台 CLI 支持 `preview / confirm / export / set-real-number`，操作说明见 [临时工号流程](STAFF_TEMPORARY_ONBOARDING.md)。没有新增 Web 或小程序页面。
- 从有效正式课表、行政班责任文字及外部责任表提取逐来源候选；明确核对所属学院、同一人分组、已有档案关联或跳过。重复确认返回同一回执；源资料变化拦截；关系冲突整批回滚。
- 新建稳定档案及易输入临时工号，不预建 Web 用户名、口令或角色。绑定码导出沿用一次性/时效/摘要规则，写文件失败回滚；导出不会覆盖已有文件。
- 小程序既有工号加绑定码接口兼容临时号；补充真实工号保留原档案、微信账号、任职和历史。普通临时教师的 Web 登录、刷新和既有 Web 会话均受服务端限制；既有管理员保留登录。
- 新增可空字段迁移 `f26a1019s007`，基于 `f26a1019d001`。回滚旧应用时保留新增字段；有临时号时不允许删列降级。

## 本次验证

1. 最终 SQLite/接口定向回归：**102 passed，1 skipped**。跳过的是只允许 MySQL 执行的行锁竞争用例；它已在下述最终 MySQL 补验中通过。
2. 独立本机 MySQL **8.4.11**（回环 `13316`）首轮：**50 passed**，覆盖初始化、导入、已有绑定竞争；最终补验：**3 passed**，覆盖同一计划并发确认只建一次、命令全流程、责任区原表及工号保留。两轮均在随机新建 `*_test` 库运行，执行完已清理该轮数据库与账号，不对业务库运行破坏性夹具。
3. MySQL 迁移往返、ORM metadata 对比通过；Alembic 单一 head 为 `f26a1019s007`。本地真实业务库未执行此迁移。
4. 本次新增/定向文件 ruff 通过；后台命令、初始化/来源模块、绑定与补关联模块 mypy 通过。全量静态检查与只读 HEAD 快照对照：ruff **516 → 516**，mypy **50 → 50**，按文件/错误码/消息比较无新增。已有全量告警不声明为通过。
5. `git diff --check` 通过；OpenAPI 仅同步三个既有字段的说明，契约与索引同步。

复验命令（backend 目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_staff_onboarding.py tests/unit/test_staff_identity.py tests/unit/test_import_person_links.py tests/unit/test_staff_importer.py tests/unit/test_staff_management.py tests/unit/test_staff_migration.py tests/unit/test_login_password_cost.py tests/unit/test_administrator_account_policy.py tests/unit/test_responsibility_original_format.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m mypy app/cli app/modules/importer/staff_onboarding.py app/modules/importer/staff_onboarding_source.py app/modules/importer/person_reconciliation.py app/modules/identity/staff_binding.py --no-incremental
.\.venv\Scripts\python.exe -m alembic heads
```

Windows 沙箱限制会令 TestClient 的 asyncio 本地 socketpair 初始化挂起；允许本地套接字后测试通过，未通过修改测试绕过业务验证。测试依赖现有弃用警告保留。

## 交付边界

本地验收完成时尚未提交、推送或部署。用户随后确认发布，已完成提交、推送并部署到 `101.34.52.163`；实际版本、迁移、备份、线上核验及回滚路径见 [发布记录](STAFF_TEMPORARY_ONBOARDING_RELEASE.md)。本文件中的测试数量仍仅代表本地验收。

没有导入真实教务数据、没有向真实教师签发凭证，也没有验证微信真实 code2session/真机流程。真实数据进入后，仍需先运行后台提取并核对；不是上传课表即自动建号授权。

真实工号目前以明确档案 ID 和版本逐项补充，不含批量映射导入。导出文件系统与数据库不是跨介质原子事务；异常中断后的文件须核验，不把未完成文件发给教师。
