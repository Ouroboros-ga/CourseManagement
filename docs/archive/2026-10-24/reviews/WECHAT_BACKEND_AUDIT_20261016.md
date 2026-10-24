> 归档说明（2026-10-24）：原路径 `docs/integration/WECHAT_BACKEND_AUDIT_20261016.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 小程序与后端接口核查（2026-10-16）

> 后续决定：以小程序的本地课表＋完整快照备份流程为准。下文接口不存在的事实仍成立，但原要求小程序改为逐条编辑的建议作废；改由后端补兼容入口。最新[备份契约](../../../integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md)已更新；三个路由操作已随37e4440部署，迁移f26a1016b001。本页保留核查时的历史事实。

状态：后端基线 `594d8c7`；本轮修复和回归在当前工作区，当时尚未提交、推送或部署；本次后续修复已提交并随37e4440部署。小程序远端只读核对 `Mo-Qiong/wxsign@6d93c8de65dff02036b0994e5d5f7346eb87be4e`，未向该仓库写入；本仓库适配副本仍以来源记录中的旧同步版本为基础。

## 结论与已修复问题

没有发现学生/志愿者本人接口新增必填 `college_id` 的问题。绑定只提交学号和绑定码；其他本人数据从登录账号绑定的学生取得；志愿者任务从本人受派关系取得。学院范围和来源字段由后端处理，小程序不需要选择学院，也不能用客户端学院字段扩大访问范围。

| 优先级 | 问题与影响 | 当前处理 |
| --- | --- | --- |
| P1 | 最新小程序调用三个不存在的路由操作：`GET /me/class-timetable`、`GET /me/timetable-backup`、`PUT /me/timetable-backup`；个人课表初始化、云备份和恢复会 404，失败后退到本地空课表可能掩盖问题 | 后端已补兼容并部署，保留客户端请求格式 |
| P2 | 后端个人课表开放自定义字段时，允许 PATCH 注入 `id`、`source_schedule_id`、`teaching_class_id`、`college_id` 等，破坏个人条目标识/来源，可能导致之后修改失败 | 已修复：写入拒绝服务端标识、来源、班级名称和 `exceptions`；单次修改继续走专用接口。它不曾授予正式业务权限 |
| P2 | PATCH 只保留固定字段，第二次修改会丢失之前保存的 `custom_tag` 等私人扩展字段 | 已修复：保留原有私人扩展，仍禁止改写来源字段 |
| P2 | 本仓库较旧的小程序副本提交学生/照片 ID 时转为 `Number`，大于安全整数的 ID 被截断 | 已改为字符串并回归；最新 wxsign 已有同样修正，不要求其重复修改 |
| 接入缺口 | 最新 wxsign 没有调用 `/me/academic-notices`，因此后端已有的简单教务通知不会显示 | 待小程序接入，仅展示列表，不增加已读/未读状态 |

## 核查时已有的逐条接口（保留兼容）

以下记录核查时已有能力，不再作为新版小程序备份的必接清单。所有路径带 `/api/v1` 前缀。新备份方案见 [个人课表接口](../../../integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md)。现有逐条模型不能直接当作 `schedule_data` 整表备份使用。

1. `GET /me/timetable/semesters` 获取本人可用学期；学期 ID 保持字符串。
2. 首次进入某学期，`POST /me/timetable/initialize`，JSON 只需 `semester_id`。已有云端副本原样返回，不覆盖个人修改；`NOT_PUBLISHED` 表示尚无正式发布，不能提示为“初始化成功”。
3. `GET /me/timetable?semester_id=...` 读取云端 `entries` 和 `current_version`。本地可以缓存，但云端是跨设备保存依据。
4. 新增用 `POST /me/timetable/entries`，修改用 `PATCH /me/timetable/entries/{eid}`，删除用 `DELETE /me/timetable/entries/{eid}`。均在查询参数带学期 ID，JSON 带最新 `current_version`；修改只提交可编辑字段，不回传完整响应对象中的来源字段。
5. 保存后采用响应中的新版本；409 提示刷新，不能静默覆盖其他设备修改。恢复和单次变更接口继续可用。
6. `GET /me/timetable/official-source?semester_id=...` 仅查看最新已发布来源；`GET /me/academic-notices` 展示简单通知；两者都不自动覆盖私人副本。

最新小程序继续采用“本地完整快照→延时整表上传→云备份恢复”，后端新增适配层；无需改为上述逐条调用，也无需为学院升级增加学院选择或学生端管理字段。

## 实际验证范围

- 写入保护先复现失败：7 个来源/标识输入用例原先均未拒绝；修复后通过。自定义字段仍支持。
- 本地无数据库契约回归：9 项通过，包括 OpenAPI 检查本人入口没有必填学院路径/查询/请求字段；定向 Node 回归 3 项通过；变更后端文件 Ruff 与 Git 空白检查通过。
- 服务器现有 MySQL 的临时独立库、真实 Uvicorn 与 HTTP：2 项测试通过，41.11 秒；涵盖两院教师/学生/志愿者，个人初始化及读取/增删改、扩展字段连续保存、来源字段拒绝、学期选择、通知、本人任务/详情/名单、换班申请/查询、上传照片、待换班仍可提交、本人历史提交、考勤照片、异议及审核；原跨院照片拒绝和管理范围回归保留。
- 测试入口：`backend/tests/unit/test_personal_timetable_contract.py`、`test_personal_timetable.py::test_personal_custom_fields_and_periods`、`test_campus_r6_e2e.py`、`apps/wechat-miniapp/tests/upstream-sync-20261014.test.mjs`。
- 服务器结果：`/opt/course-management/rehearsals/miniapp-audit-20261016/R45_MYSQL_RESULT.json`；临时测试库已删除，未写入生产库；没有启动本地 MySQL。
- 登录/绑定/刷新完成代码及输入契约核查；真实 HTTP 验收采用账号密码登录，没有验证真实微信 `wx.login/code2session`、真实学生绑定码核销、开发者工具和真机页面，不将其称为微信全端验收通过。

## 数据和版本边界

生产只读核查仍有一条已启用资格缺少学生班级/学院归属；当前 25 条未撤销受派关联的账号没有绑定学生。后端按正式身份拒绝缺少学生或有效资格的提交属于正确校验，应核实这些是否为历史测试数据；本轮不擅自绑定、补学院或改变任务。它们与“请求必须传 `college_id`”不同。

现有生产正式业务隔离和组织排班开关仍关闭。本次隔离 HTTP 验收开启它们验证后端路径；生产开关与存量数据未调整。本次后续发布已补齐备份路由并上线修复；客户端缓存、学期和通知接入仍需核对，不能把后端测试通过理解为小程序真机全功能已验收。
