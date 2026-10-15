> 当前增量及部署边界请优先阅读[2026-10-16小程序交接](WECHAT_API_CHANGES_20261016.md)。

# 微信小程序：云端个人课表与教务通知接口

2026-10-15。后端与 Web 已实现，小程序本轮不开发页面。生产地址为 `https://course.zsitai.xyz`，以下路径均以 `/api/v1` 开头。最终部署版本见 `docs/archive/2026-10-15/operations/P5_RELEASE_20261015.md`。

## 可直接交接的范围与版本

本文件是小程序开发者的正式接入说明，当前核心接口已上线；应用源码版本 `4b41344`，接口交接资料已随 `dev-main` 的 `8b2a6ec` 及其祖先提交提供。

本轮可以开发：学期选择、今日/周课表、课程详情、新增/编辑/删除课程、简单教务通知列表。管理端的学院配置、作息、成员管理和排班不属于本次小程序开发任务，也不要求小程序新增学院工作区选择。

**2026-10-16 已更新：** 恢复删除条目、单次修改/撤销、自定义节次/颜色及最新正式来源接口均已补齐部署，详见[最新小程序接口增量](WECHAT_API_CHANGES_20261016.md)。下文保留核心课表接入契约；原“恢复/单次修改未实现”说明不再适用。离线编辑与自动采用教务更新仍不在当前交付范围。

以下为服务端能力交付；微信开发者工具编译、真机与多设备联调仍由小程序开发者验收，不能以已有后端用例通过替代。

## 业务约定

- 教务导入、管理端总课表查看均不等于发布。教师在 Web「学院与组织配置 → 教务课表发布」选择学期，预览后明确发布。
- 小程序在有效学生绑定后获取可用学期，逐学期调用初始化接口。绑定接口本身不返回课表，也不自动创建副本；小程序负责在绑定成功/进入课表页时发起初始化。
- 每名学生、每学期只有一份云端个人课表。重复初始化返回现有副本，空课表也不会重新灌入。尚未发布时稍后重试初始化。
- 初始来源是正式教学班名单关联的已发布课表，包含正式选修名单；不会按课程名称或行政班名称猜测选课。学生可以自行补充选修课。
- 本人修改优先保留。再次发布只产生相关学生的简单通知，**不覆盖、合并或自动采用教务更新**。没有通知已读、未读、忽略或采用接口。
- 个人课表不参与查课、排班、课程冲突、考勤、免到或统计。个人修改不会改动正式教务数据。

## 身份与通用响应

沿用现有微信登录、绑定和刷新机制；请求携带 `Authorization: Bearer <access_token>`。服务端从当前账号取学生身份，所有接口都不接受 `student_id`、`user_id` 或学院切换来代查他人。

成功统一为 `{"data": ..., "requestId": "..."}`。数据库 ID 均按字符串处理；个人课程 `id` 是 UUID，不能转成 Number。

| 方法 | 路径 | 参数/用途 |
| --- | --- | --- |
| GET | `/me/timetable/semesters` | 本人相关的已发布或已初始化学期，返回数组；元素包含 `id/name/status/initialized/current_version` |
| POST | `/me/timetable/initialize` | JSON `{"semester_id":"1"}`；幂等初始化，返回完整个人课表 |
| GET | `/me/timetable?semester_id=1` | 读取本人指定学期的完整云端副本 |
| POST | `/me/timetable/entries?semester_id=1` | 新增个人课程；JSON 必须带当前课表 `current_version` |
| PATCH | `/me/timetable/entries/{eid}?semester_id=1` | 修改个人课程；JSON 包含 `current_version` 与要变更的字段 |
| DELETE | `/me/timetable/entries/{eid}?semester_id=1` | **JSON 请求体** `{"current_version":3}`；不能把版本遗漏或只放在查询串 |
| GET | `/me/academic-notices?page=1&page_size=20` | 仅本人相关更新；返回 `items/total/page/page_size`，没有已读状态 |

## 个人课表返回结构

初始化、读取和所有写操作返回相同聚合结构：

```json
{
  "data": {
    "semester_id": "1",
    "status": "INITIALIZED",
    "current_version": 1,
    "source_revision": "来源指纹",
    "sources": [{"publication_id":"10","college_id":"2","version":1,"published_at":"2026-10-15T01:00:00Z","calendar":{"timezone":"Asia/Shanghai","first_monday":"2026-08-31","total_weeks":18}}],
    "entries": [{"id":"c27cebf8-43e8-47aa-9a5e-64741f162671","course_name":"示例课程","teacher":"示例教师","classroom":"教学楼101","weekday":1,"week_nos":[1,2],"start_time":"08:00:00","end_time":"09:40:00","note":"","occurrence_dates":["2026-08-31","2026-09-07"],"source_schedule_id":"20","teaching_class_id":"30","college_id":"2","class_name":"示例教学班","start_period":1,"end_period":2}]
  },
  "requestId": "example"
}
```

`sources[].calendar` 是发布时的校历快照，字段以 OpenAPI/实际响应为准。`status` 为 `INITIALIZED/NOT_INITIALIZED/NOT_PUBLISHED`。未初始化时版本、来源修订为 null，数组为空。GET 不自动初始化；POST 初始化尚无发布时返回 `NOT_PUBLISHED`，不要当作可编辑的空副本。

时间解释：`published_at` 是 UTC 时间戳，显示时转北京时间；`start_time/end_time` 是 **Asia/Shanghai 当地课程时刻**，不要再次加八小时。`weekday` 周一为 1、周日为 7。正式来源的 `occurrence_dates` 已反映校历调整，非 null 时优先用这些具体日期展示，不再用周次重复推导；为 null 的自建课按学期校历、周次和星期展示。

## 新增、修改、删除

新增示例：

```json
{"current_version":1,"course_name":"个人选修","teacher":"教师姓名","classroom":"自定义地点","weekday":3,"week_nos":[1,2,3],"start_time":"18:00:00","end_time":"19:30:00","note":"个人备注"}
```

必填课程名、星期、周次、起止时刻；周次为 1–60，每份课表最多 500 条，同一天结束时刻须晚于开始时刻。可选教师、地点、备注、具体日期；自建课程正式来源标识均为 null。来源 ID、学院 ID、教学班 ID 等不能通过写入伪造。

PATCH 示例 `{"current_version":2,"classroom":"本人修改地点","note":"提醒"}`。每次成功写操作返回完整副本和递增的**整份课表版本**。修改星期/周次而未显式提供 `occurrence_dates` 时，后端清除旧的具体日期，避免继续沿用原正式课次；若产品允许自定义日期，可以显式提供 `occurrence_dates`。

多设备：写入使用最近成功读取/保存的 `current_version`；409 时重新读取并提示冲突，让用户确认后再次保存，不要拿新版本号静默覆盖。离线缓存只作显示/草稿，服务端成功结果才是云端事实。401 按现有机制串行刷新一次；403 重新核对有效绑定/学生状态；404 课程或学期不存在；422 校验失败；503 表示发布功能未开启。

## 简单通知

`items` 的字段为 `id/college_id/semester_id/version/published_at/title/message`。仅展示与本人正式名单相关且内容发生变化的发布历史；同内容重复发布不重复通知。通知表示教务更新，不能据此重初始化或覆盖个人副本。无需展示未读数、小红点或已读按钮。

## 管理端配套与接入验收

管理端由本项目负责：`POST /colleges/{cid}/academic/semesters/{sid}/publication-preview` 返回 `source_revision`；随后 POST 同前缀 `/publish`，JSON `{"source_revision":"预览返回的64位指纹"}`。需要本院 `academic.manage`；源或权限变化返回409，重新预览。小程序不调用管理接口。

开发者至少验证：绑定后初始化；重复登录不覆盖；增删改并刷新/换设备仍保留；过期版本409；教务再发布有通知但副本不变；另一学生不能读取/修改本人课程；未发布、空课表、解绑和会话过期；UTC发布时间和当地课程时刻分别显示正确。本轮后端验收使用独立 MySQL 数据库，不代表微信开发者工具或真机已验收。

## 小程序页面与调用顺序

| 页面/时机 | 调用与保存规则 | 用户可见状态 |
| --- | --- | --- |
| 绑定成功/首次进入课表 | 获取`/me/timetable/semesters`，让用户选择学期；无学期时不猜测ID | 暂无已发布课表；允许刷新，不表示账号绑定失败 |
| 进入所选学期 | GET本人课表；`NOT_INITIALIZED`时POST initialize；此后用服务端完整响应替换该学期缓存 | `NOT_PUBLISHED`显示等待教务发布；已初始化但entries为空显示个人课表为空 |
| 今日/周视图 | 展示当前云端副本，按具体日期或周次筛选；周次基准来自sources校历 | 本周无课与未初始化分开；旧学期可选择查看 |
| 课程编辑 | 保存时带整份课表current_version；成功后使用完整响应更新页面和缓存 | 409展示“其他设备已更新，请刷新后确认修改”，保留当前表单草稿 |
| 课程删除 | 确认后DELETE并携带JSON版本；成功后使用完整响应 | 不展示恢复按钮；删空后再次登录不会重新灌入正式课表 |
| 通知列表 | 分页GET academic-notices；只读展示标题、说明、学期、发布时间 | 无已读、红点、忽略或采用按钮，不因查看通知自动初始化/覆盖课表 |
| 退出/解绑/换账号 | 清理当前身份的课表和通知缓存，取消/忽略旧身份在途请求 | 新账号页面不得短暂显示旧学生内容 |

建议缓存键至少包括当前账号身份＋学期；缓存中保留current_version、sources和最后成功获取时间。访问新学期时重新读取，不把上一学期的版本带入新学期。教师发布后才有正式来源，学生端不提供“发布”操作。

## 交付检查单

- [ ] 小程序接入上述7个接口，GET/POST/PATCH/DELETE方法和参数位置与本文一致。
- [ ] 正式来源课程和个人新增课程都能显示、编辑；不改正式教学班/选课关系。
- [ ] 多设备、重复登录、删空、教务再发布保持个人最后成功保存结果。
- [ ] 401串行刷新一次，409由用户确认后重试；不静默重试写操作覆盖云端。
- [ ] 日期、当地课程时刻、UTC发布时间显示正确；没有把当地时刻再次加八小时。
- [ ] 退出/换绑/换账号清缓存并丢弃旧响应；所有ID保持字符串。
- [ ] 通知只展示；不实现尚无接口的删除恢复/单次修改。
- [ ] 回传改动提交、微信开发者工具编译结果、必要真机截图及仍未验证项；不回传真实token或完整学生名单。


## 后续待部署增量（2026-10-15）

当前工作区新增私人删除恢复、日期例外（单次修改），个人条目读取增加exceptions；通知列表增加kind=ENROLLMENT_SOURCE_CHANGED，其semester_id为null，id是enrollment:事件ID。不要将新接口视为线上可用，也不要把通知id强转数字。具体请求、展示合并规则和限制见 [增量契约第5、6节](../development/CONFIRMED_MODULES_API_20261015.md)。此前“尚未提供恢复/单次修改”只描述先前发布基线。


## 2026-10-16 可选扩展：与学院升级解耦

仅在主动开发个人课表便捷功能时接入以下接口。原有小程序任务、考勤、照片、异议功能不依赖这些扩展。

### 最新正式来源：读取最新正式教务来源

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

### 恢复与单次修改：本人课表恢复与单次修改

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

### 个人课程字段与版本

既有新增/修改接口继续使用：

- `POST /me/timetable/entries?semester_id=...`
- `PATCH /me/timetable/entries/{eid}?semester_id=...`
- `DELETE /me/timetable/entries/{eid}?semester_id=...`

新增或明确支持 `start_period/end_period`（可空，1..30）及`color`（可空，最长64字符）；用于个人显示，不更改学校作息。真实起止时间仍由`start_time/end_time`表达；新增课程依旧需课程名、星期、周次、起止时刻等原有必填字段。客户端保留不认识的返回扩展字段，不能依靠未在契约列出的自定义字段参与正式业务。

`current_version`是整份“本人+学期”课表的版本，不是单条课程版本。所有增删改、恢复和单次修改都提交最新版本；成功后以完整响应替换本地缓存。409先重新读取云端再让用户选择如何处理，不能盲目用旧内容重试。GET正式来源的`source_revision`不能代替个人副本的`current_version`。

初始化仍是 `POST /me/timetable/initialize`，body `{"semester_id":"2"}`；绑定后按学期调用。重复初始化返回已有副本，即使副本被本人清空也不重新灌入；后台再次发布不覆盖个人修改。

### 简单通知与通用兼容

`GET /me/academic-notices?page=1&page_size=20`只展示通知，`data`为items/total/page/page_size。`kind`包括ACADEMIC_PUBLICATION与ENROLLMENT_SOURCE_CHANGED；后者提示学籍来源变化，semester_id可空，id可能是`enrollment:...`，不能转数字。未知kind可显示通用title/message。

不增加已读、未读、忽略、采用、批量覆盖或微信推送接口。不要收到通知后自动重新初始化或覆盖本人课表。

沿用Bearer认证、刷新及上传规则；所有ID按字符串保留。服务器事件时刻如带Z按UTC解析；旧事件时刻无时区标记时按UTC解释，再按Asia/Shanghai显示。课程日期和本地上课起止时刻按日历/墙上时间处理，不能再加八小时。
