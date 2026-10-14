# 微信小程序：云端个人课表与教务通知接口

2026-10-15。后端与 Web 已实现，小程序本轮不开发页面。生产地址为 `https://course.zsitai.xyz`，以下路径均以 `/api/v1` 开头。最终部署版本见 `docs/P5_RELEASE_20261015.md`。

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
