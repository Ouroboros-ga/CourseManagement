# 接口验收附录：已有后端、没有当前页面入口

[总入口](README.md) · [功能验收](ACCEPTANCE_CASES.md) · [测试资料](TEST_DATA.md)

本附录供 QA/维护者执行，不要求普通教师、志愿者或学生手工调用接口。所有请求尚未在本轮执行。源接口和请求结构来自已部署基准 73a69fb6d843f5eb8d31630f5340b2342d186b62 的 docs/openapi.json、实际挂载路由与服务端规则。OpenAPI 的少量旧“待审核/终审”描述是历史残留，现行业务仍为提交即生效、一次异议审核。

## 执行方法

1. 使用已有授权的 QA HTTP 客户端或测试运行器，配置测试系统 base URL 和对应角色的有效会话；Web Cookie 与小程序令牌方式不同，不能混用。无需提供 GitHub 个人 Token，也不要把登录秘密写进手册。
2. 根据 TEST_DATA 的对象映射替换路径中的 cid、sid、gid、rid、tid、task_id。所有对象必须由 QA 资料实际返回，不能把名字、学号或示例小整数当数据库 ID。
3. 以本节指定方法和完整路径发请求；JSON 写入使用 application/json，并满足下表必填字段和完整 OpenAPI 限制。GET 查询参数在路径后按契约添加。使用保留整数精度的客户端；响应 ID 按字符串存储，不经过 JavaScript Number/parseInt 截断。旧请求契约要求整数的字段按精确 JSON 整数发送。
4. 正例核对成功响应及实际复读结果；反例核对状态码、业务错误和原数据不变。401 是会话问题，403/防枚举 404 是权限范围，409 是版本/业务状态冲突，422 是输入结构不符；不能都归为历史失败。
5. 每个用例保存脱敏请求结构、实际状态、对象 ID 和结果，不保存令牌、绑定码、Cookie、完整学生名单或带签名文件链接。读写分离观察；不在失败后直接改表“补齐成功”。

下表只列必填请求字段以便定位，完整可选项、枚举和嵌套结构仍按固定提交的 OpenAPI。维护者可在本地查看该提交文件，不要以另一个工作区旧版同名文件替代。

<a id="b01"></a>

## B01　不可变版本周报

POST body：semester_id 为实际 QA 学期整数、week_no 为有效教学周、scope 为 COLLEGE，reason 选填。GET reports 带 semester_id 和 week_no；由实际返回选 report 与 version。下载 kind 可为 EXCEL、SNAPSHOT、WORD、DETAIL_WORD、STUDY_EXCEL，仍须核对该版本实际支持的产物。先下载留摘要，再改合成考勤、生成新版，验证旧文件摘要不变。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `POST /api/v1/colleges/{cid}/reports/weekly/versions` | semester_id、week_no | 无 |
| `GET /api/v1/colleges/{cid}/reports` | 无 body 必填项 | semester_id、week_no、page、page_size |
| `GET /api/v1/colleges/{cid}/reports/{rid}/versions` | 无 body 必填项 | 无 |
| `GET /api/v1/colleges/{cid}/report-versions/{vid}/download` | 无 body 必填项 | kind |

预期和常见错误与 [AC-B01](ACCEPTANCE_CASES.md#b01) 同步；本轮状态为未执行。

<a id="b02"></a>

## B02　本人课表和站内教务通知

按各 GET 的 semester_id 查询条件读取本人资料。initialize 用 QA 学期字符串 ID；先读取 current_version，再新增一条合成课，保存后复读。新增字段 course_name、weekday、week_nos、start_time、end_time、current_version 按契约填写。重新发布官方教务后再次读取本人内容和 notices，个人内容不得隐式重置。使用另一学生会话，不能读写第一个人的副本。云端备份格式按 BackupWrite，不把本地缓存当已保存。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `GET /api/v1/me/timetable/official-source` | 无 body 必填项 | semester_id（必填） |
| `POST /api/v1/me/timetable/initialize` | semester_id | 无 |
| `GET /api/v1/me/timetable` | 无 body 必填项 | semester_id（必填） |
| `POST /api/v1/me/timetable/entries` | course_name、weekday、week_nos、start_time、end_time、current_version | semester_id（必填） |
| `GET /api/v1/me/timetable-backup` | 无 body 必填项 | semester_id |
| `PUT /api/v1/me/timetable-backup` | semester_id、schedule_data | 无 |
| `GET /api/v1/me/academic-notices` | 无 body 必填项 | page、page_size |

预期和常见错误与 [AC-B02](ACCEPTANCE_CASES.md#b02) 同步；本轮状态为未执行。

<a id="b03"></a>

## B03　学院独立作息与校历方案

读取当前版本后，在独立未来日期构造 effective_from、periods、calendar、grid_slot_mapping；按 TimeConfiguration 预览。发布必须用相同资料及新返回 revision（TimePublish）；存在受影响任务时先核对，再决定 confirm_existing_tasks，不默认设为 true。复读未来课次、历史快照与影响项。学校模板读取/采用及多个作息方案接口在同一 OpenAPI 下 time-versions/profiles 和 school-time-templates，当前普通 Web 未挂载对应学院页。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `GET /api/v1/colleges/{cid}/academic/semesters/{sid}/time-versions` | 无 body 必填项 | 无 |
| `POST /api/v1/colleges/{cid}/academic/semesters/{sid}/time-versions/preview` | effective_from、periods | 无 |
| `POST /api/v1/colleges/{cid}/academic/semesters/{sid}/time-versions/publish` | effective_from、periods、revision | 无 |

预期和常见错误与 [AC-B03](ACCEPTANCE_CASES.md#b03) 同步；本轮状态为未执行。

<a id="b04"></a>

## B04　志愿者本人不可用

本人 POST body：本人 student_id、semester_id 均为字符串，starts_at/ends_at 为带时区 ISO 时间，reason 选填。必须先记录新申请 ID 和 lock_version；撤回提交当前 lock_version，status 默认为 CANCELED，note 选填。不得将管理端 decision 地址当志愿者本人审批入口。再由独立管理身份按 T17 办理另一条申请验证批准后的排班约束。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `GET /api/v1/colleges/{cid}/groups/{gid}/me/unavailability` | 无 body 必填项 | semester_id（必填）、page |
| `POST /api/v1/colleges/{cid}/groups/{gid}/me/unavailability` | student_id、semester_id、starts_at、ends_at | 无 |
| `POST /api/v1/colleges/{cid}/groups/{gid}/me/unavailability/{rid}/withdraw` | lock_version | 无 |

预期和常见错误与 [AC-B04](ACCEPTANCE_CASES.md#b04) 同步；本轮状态为未执行。

<a id="b05"></a>

## B05　教职工本人绑定

使用本人微信登录会话，body 同时提供合成 staff_no 与管理员签发的一次性 binding_code。绑定码仅在运行时输入，不保存到报告或命令历史。成功后读取本人身份和工作范围；用另一合成工号配原码应失败且不产生关系。管理端签发入口已存在，缺的是本人小程序表单。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `POST /api/v1/me/staff-binding` | staff_no、binding_code | 无 |

预期和常见错误与 [AC-B05](ACCEPTANCE_CASES.md#b05) 同步；本轮状态为未执行。

<a id="b06"></a>

## B06　本人权限来源

用本人会话请求指定 QA 学院。与 /api/v1/me 的有效权限及实际业务读取/写入结果对照；撤一项合成授权后刷新。外院无权来源不得暴露。当前 PermissionSources 组件没有可达入口。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `GET /api/v1/colleges/{cid}/permission-sources/me` | 无 body 必填项 | 无 |

预期和常见错误与 [AC-B06](ACCEPTANCE_CASES.md#b06) 同步；本轮状态为未执行。

<a id="b07"></a>

## B07　通用考勤版本

rid 为合成考勤记录 ID，不是任务 ID。读取版本，再按 T27 更正并复读；应增加版本，旧值保留。用未授权学生或外院管理身份请求同一 ID，应拒绝。教工本人局部历史页面 T32 使用另一个本人受限接口，不能据此认定通用版本页已实现。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `GET /api/v1/colleges/{cid}/attendance/{rid}/versions` | 无 body 必填项 | 无 |

预期和常见错误与 [AC-B07](ACCEPTANCE_CASES.md#b07) 同步；本轮状态为未执行。

<a id="b08"></a>

## B08　任务名单冻结版本

先读取任务最新 lock_version 及当前名单。在允许执行前更正状态，POST student_ids 为完整合成学生整数 ID 集合，lock_version 为所见任务版本，reason 选填。复读任务与版本，验证成员与人数。保留旧版本再提交作为 409 反例；确认失败没有改变当前名单。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `GET /api/v1/colleges/{cid}/inspection-tasks/{task_id}/roster-versions` | 无 body 必填项 | 无 |
| `POST /api/v1/colleges/{cid}/inspection-tasks/{task_id}/roster-versions` | lock_version | 无 |

预期和常见错误与 [AC-B08](ACCEPTANCE_CASES.md#b08) 同步；本轮状态为未执行。

<a id="b09"></a>

## B09　任务执行组变更

预览 body：target_group_id 为目标组整数 ID、lock_version 为当前任务版本。确认 body 在原资料上加预览 revision，reason 选填。必须记录 will_revoke_assignment、requires_new_assignment。确认后原受派撤销、待办调班申请失效，按 T21 另行排班。确认前修改一项合成来源后提交旧 revision，应冲突且不改变组。

| 方法及路径 | 必填请求字段 | 查询参数 |
| --- | --- | --- |
| `POST /api/v1/colleges/{cid}/inspection-tasks/{tid}/execution-group/preview` | target_group_id、lock_version | 无 |
| `POST /api/v1/colleges/{cid}/inspection-tasks/{tid}/execution-group/confirm` | target_group_id、lock_version、revision | 无 |

预期和常见错误与 [AC-B09](ACCEPTANCE_CASES.md#b09) 同步；本轮状态为未执行。
