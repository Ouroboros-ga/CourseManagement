# 微信小程序开发者：2026-10-16 功能与接口增量

生产地址：`https://course.zsitai.xyz`；下列路径均以 `/api/v1` 开头。本文按已部署后端路由、Schema与R6真实HTTP验收整理，替代旧文档中“恢复/单次修改未实现”等描述。完整基础契约见[个人课表接口](WECHAT_PERSONAL_TIMETABLE_API_20261015.md)，精确字段见[OpenAPI](../openapi.json)。

## 1. 结论与接入范围

本轮是兼容性增量：既有微信登录、绑定、本人任务、提交、考勤、照片与异议路径继续沿用。小程序不需要学院工作区选择器，不需要实现学校作息、组织成员、范围抽查或排班管理页面。

优先适配考勤负责学院、归档状态和独立记录展示。个人课表正式来源、删除恢复及单次修改属于可增加的个人便捷功能，不阻塞既有查课/考勤功能。

归属回填属于数据变化：软工2403、网工2403继续归软件学院（测试）；其余39个行政班、74个旧任务归人工智能学院（低空技术与工程学院）。旧任务ID、考勤、照片与审核记录未更换，不需要重新绑定或迁移客户端ID。正式业务隔离/组织排班两个生产开关仍关闭；这不关闭已启用的本人云端课表与教务发布接口。

## 2. 考勤：负责学院及学期状态

`GET /me/attendance`、有权访问的 `GET /attendance/{record_id}` 增加/保留：

| 字段 | 类型 | 小程序处理 |
| --- | --- | --- |
| `task.responsible_college_id` | string或null | 任务发起管理归属；保留字符串 |
| `task.responsible_college_name` | string或null | 可展示“检查负责学院”；缺失/空值不阻断详情 |
| `task.semester_status` | string或null | 为ARCHIVED时隐藏新异议入口；服务端亦会拒绝新建 |
| `photo_file_ids` | string[] | 查课现场照片，空数组无照片；逐个申请授权链接 |

示例是部分字段，ID为演示值：

```json
{
  "id": "101",
  "task_id": "201",
  "effective_type": "LATE",
  "current_version": 1,
  "photo_file_ids": ["301"],
  "task": {
    "task_id": "201",
    "responsible_college_id": "1",
    "responsible_college_name": "人工智能学院（低空技术与工程学院）",
    "semester_status": "ACTIVE"
  }
}
```

同一学生同一天同课程允许存在不同任务负责学院的独立结果。列表以考勤记录`id`为键，不能用课程名+日期去重，也不能把两条结果合成全校统一结论。异议仍针对具体记录 `POST /attendance/{record_id}/objections`，按该记录的版本与状态处理，审核仍只有一次。

照片继续使用 `GET /files/{id}/access` 返回的`data.url`及有效期，过期重新申请；相对URL补生产地址。不能按学院ID自行拼文件路径。此功能后端已提供，不需要小程序等待管理端组织排班启用。

## 3. 新增：读取最新正式教务来源

`GET /me/timetable/official-source?semester_id=2`

该接口只读，返回当前绑定学生可见的最新已发布教务资料。与 `GET /me/timetable` 的本人云端副本分开：前者用于对比，后者用于日常显示，个人最后保存结果继续优先。

| 返回字段 | 说明 |
| --- | --- |
| `status` | AVAILABLE / NO_ENROLLMENT / NOT_PUBLISHED |
| `semester_id` | 字符串学期ID |
| `source_revision` | 不透明来源修订字符串，可用于检测变化 |
| `sources` | 发布版本、学院、发布时间及校历上下文 |
| `entries` | 本人可见的正式课程、节次、起止时刻、周次和具体日期 |

返回仍套 `{"data": ..., "requestId": ...}` 信封。NO_ENROLLMENT表示已有相关发布但没有本人课程；NOT_PUBLISHED表示尚无可用发布。空结果不是清空个人副本的指令。调用该接口不覆盖副本、不自动采用更新、不写通知已读状态。

## 4. 已补齐：本人课表恢复与单次修改

以下接口本次部署已具备，旧交接资料中的“暂不能交付”说明作废。所有操作只影响本人云端副本，不参与正式查课、排班或考勤。

| 方法 | 路径（均需query `semester_id`） | 请求/返回 |
| --- | --- | --- |
| GET | `/me/timetable/deleted-entries` | 返回`data.current_version`和`items:[{entry,deleted_at}]` |
| POST | `/me/timetable/entries/{eid}/restore` | JSON `{"current_version":7}`；恢复原条目ID，返回完整副本和新版本 |
| PUT | `/me/timetable/entries/{eid}/exceptions/{day}` | 保存该原始日期的一次停课/调课/教室等修改；见下例 |
| DELETE | `/me/timetable/entries/{eid}/exceptions/{day}` | JSON `{"current_version":8}`；撤销单次修改，恢复基础课程在该日的安排 |

`eid`为个人条目UUID字符串，`day`为原本上课的日期`YYYY-MM-DD`。即使调到别的日期，后续编辑/撤销仍使用原始day。day必须属于原个人课程，目标日期必须在本学期内。

仅修改一次教室及日期：

```http
PUT /api/v1/me/timetable/entries/{eid}/exceptions/2026-10-19?semester_id=2
Content-Type: application/json

{"current_version":7,"target_date":"2026-10-20","classroom":"A202","cancelled":false}
```

仅停课一次：`{"current_version":7,"cancelled":true}`。可同时设置`course_name/teacher/classroom/start_time/end_time/note`。返回条目`exceptions`为`[{date,target_date,cancelled,values}]`；显示时先展开基础日期，再按原始date应用例外，取消项不展示，调课展示到target_date，不能在原日和新日重复展示。

已有单次修改时，直接修改该课程的weekday/week_nos/occurrence_dates会返回409，需先撤销单次修改后再调整重复日期规则。删除课程为可恢复删除；可恢复条目上限500条、活动课程上限500条，容量不足按409提示，不自动清空旧记录。

## 5. 个人课程字段增量与版本

既有新增/修改接口继续使用：

- `POST /me/timetable/entries?semester_id=...`
- `PATCH /me/timetable/entries/{eid}?semester_id=...`
- `DELETE /me/timetable/entries/{eid}?semester_id=...`

新增或明确支持 `start_period/end_period`（可空，1..30）及`color`（可空，最长64字符）；用于个人显示，不更改学校作息。真实起止时间仍由`start_time/end_time`表达；新增课程依旧需课程名、星期、周次、起止时刻等原有必填字段。客户端保留不认识的返回扩展字段，不能依靠未在契约列出的自定义字段参与正式业务。

`current_version`是整份“本人+学期”课表的版本，不是单条课程版本。所有增删改、恢复和单次修改都提交最新版本；成功后以完整响应替换本地缓存。409先重新读取云端再让用户选择如何处理，不能盲目用旧内容重试。GET正式来源的`source_revision`不能代替个人副本的`current_version`。

初始化仍是 `POST /me/timetable/initialize`，body `{"semester_id":"2"}`；绑定后按学期调用。重复初始化返回已有副本，即使副本被本人清空也不重新灌入；后台再次发布不覆盖个人修改。

## 6. 简单站内通知与通用兼容

`GET /me/academic-notices?page=1&page_size=20`只展示通知，`data`为items/total/page/page_size。`kind`包括ACADEMIC_PUBLICATION与ENROLLMENT_SOURCE_CHANGED；后者提示学籍来源变化，semester_id可空，id可能是`enrollment:...`，不能转数字。未知kind可显示通用title/message。

不增加已读、未读、忽略、采用、批量覆盖或微信推送接口。不要收到通知后自动重新初始化或覆盖本人课表。

沿用Bearer认证、刷新及上传规则；所有ID按字符串保留。服务器事件时刻如带Z按UTC解析；旧事件时刻无时区标记时按UTC解释，再按Asia/Shanghai显示。课程日期和本地上课起止时刻按日历/墙上时间处理，不能再加八小时。

## 7. 小程序最小联调清单

1. 同课程两条不同考勤ID均保留，展示各自负责学院，照片和异议指向原记录。
2. 归档学期的新异议按钮不可用；照片签名过期可重取，跨账号不复用缓存。
3. 发布后初始化副本；本人改动后再发布，GET正式来源能看新资料，GET本人副本保留个人改动。
4. 删除后恢复保留原eid；一次调课只在目标日出现，撤销后恢复原日；验证一次409冲突。
5. 通知两种kind可展示；不产生已读/未读/自动采用流程。

后端R6已验证真实HTTP链路与正式来源读取。微信开发者工具、真机照片预览和个人课表日期展开仍由小程序开发者联调；本次没有修改小程序页面或调用微信订阅消息。
