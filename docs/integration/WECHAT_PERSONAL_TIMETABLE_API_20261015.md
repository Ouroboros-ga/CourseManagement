# 微信小程序：云端个人课表与教务通知接口

2026-10-15。后端与 Web 已实现，小程序本轮不开发页面。生产地址为 `https://course.zsitai.xyz`，以下路径均以 `/api/v1` 开头。最终部署版本见 `docs/archive/2026-10-15/operations/P5_RELEASE_20261015.md`。

## 可直接交接的范围与版本

本文件是小程序开发者的正式接入说明，当前核心接口已上线；应用源码版本 `4b41344`，接口交接资料已随 `dev-main` 的 `8b2a6ec` 及其祖先提交提供。

本轮可以开发：学期选择、今日/周课表、课程详情、新增/编辑/删除课程、简单教务通知列表。管理端的学院配置、作息、成员管理和排班不属于本次小程序开发任务，也不要求小程序新增学院工作区选择。

**暂不能交付的按钮**：“恢复已删除课程”“仅修改这一次课程”。目前没有完整的恢复/单次例外接口，不能把 `occurrence_dates` 字段当作这些流程已经完成，也不能通过多次请求模拟原子操作。后端补齐后另发增量契约。离线编辑与自动采用教务更新也不在当前交付范围。

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
