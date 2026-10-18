# 微信小程序三 Tab 与教职工协作：产品及 API 增补规划

日期：2026-10-17。状态：**规划，新增接口未实现、未部署，不能作为当前联调契约。** 本轮仅开发后端/Web并交付端侧设计；本文不授权或表示已实现小程序页面。

主方案：[教职工协作增补](../development/STAFF_COLLABORATION_EXTENSION_20261017.md)。已有接口以现行 [API 契约](../API_CONTRACT.md)、源码及 [个人课表交接](WECHAT_PERSONAL_TIMETABLE_API_20261015.md) 核对。本文中的响应示例均为脱敏的拟定格式，不是线上返回。

## 1. 产品结构

| 模式 | Tab | 默认内容 | 明确操作 |
| --- | --- | --- | --- |
| 学生 | 课表 | 本地课表、已发布教务来源、云端整表备份 | 本人编辑；主动导入与备份/恢复，不自动覆盖 |
| 学生 | 考勤 | 本人正式考勤；志愿者可切到“查课任务” | 本人申诉；本人受派查看/提交/申请换班，两种列表不混排 |
| 学生 | 我的 | 学生档案、绑定、帮助及有效身份 | 模式切换、按现有机制解绑/退出 |
| 教工 | 课程 | 本人正式授课日程 | 修改指定日期教室；无课显示空状态和我的班级入口 |
| 教工 | 考勤 | 有授课关系则可看“我的授课”，有责任关系则可看“我的班级” | 逐记录更正或一次异议审核；不能靠角色名称推断动作 |
| 教工 | 我的 | 工号、姓名、所属学院、有效职责 | 模式切换、帮助、退出；教工解绑需新增独立业务接口后再开放 |

三 Tab 是呈现结构，底层不依赖“最高角色”。单模式自动进入，双模式记住当前账号上次选择。无效或撤销的模式不可用；界面切换不修改后端权限。管理员/负责人已有管理能力保留明确入口，不强行把管理功能变成志愿者执行任务。

志愿者在考勤 Tab 顶部能直接找到“查课任务”，并显示真实待执行提示；无任务时不能隐藏本人考勤。教师和辅导员兼任时，在同一考勤 Tab 切工作视图，无需重复登录。纯辅导员首期不将别人的课程填入“我的课程”。

具体采用现有页面路由改造还是自定义导航组件，端侧实施时依据目标微信开发者工具和实际 TabBar 能力确定；不能仅在 `app.json` 改三个文字就宣称全部多身份流程完成。

## 2. 已有能力与本次新增的区别

已只读核对本地 `dev-main=14002e4`。该仓库的小程序适配副本仍有首页/我的两 Tab、独立任务和记录页面；未据此断言小程序上游或用户正在运行的版本相同，本轮未拉取上游。

| 能力 | 处理方式 |
| --- | --- |
| 微信登录、刷新、退出、`GET /me` | 沿用已有机制；`/me` 增加可选模式/工作视图摘要，原字段兼容 |
| `GET /me/attendance`、学生申诉及本人异议 | 保持本人语义，不因为增加教工就变成管理范围读取 |
| `GET /me/inspection-tasks`、任务详情/名单/提交、换班申请 | 志愿者继续调用；不让教工通过志愿者提交接口更正正式考勤 |
| `GET /me/class-timetable`、`GET/PUT /me/timetable-backup` | 沿用本地编辑和云端整表备份；旧逐条接口保留兼容，不作为本次首选调用链 |
| `GET /me/academic-notices` | 继续简单通知列表，不增加已读/未读/忽略状态，不自动修改个人副本 |
| `GET /files/{file_id}/access` | 继续短期授权 URL；新增教工资源范围，签名不是图片加密或永久访问权 |
| 教职工绑定、授课日程、教工查课列表、更正、责任区审核 | 本次拟新增，必须等后端完成并记录部署状态后联调 |

所有路径省略 `/api/v1`。现有 API 的原始参数和响应保持，以现行 schema 为准；下文新增字段只适用于规划中的新增接口或增量响应，不回写旧接口语义。

## 3. 身份与视图上下文

建议在 `GET /me` 现有响应内增量增加可选 `app_context`，旧客户端忽略即可：

```json
{
  "app_context": {
    "available_modes": ["staff"],
    "available_work_views": ["teaching", "responsible"],
    "authorization_revision": "opaque-revision",
    "staff": {"id": "10001", "staff_no": "000123", "name": "示例教师", "college_id": "101"}
  }
}
```

示例只是现有 `data` 内新增片段，不替代 `id/roles/permissions/pre_binding` 等字段。`authorization_revision` 是缓存失效标识，不是授权凭据。`views` 只说明能进哪个工作视图，具体课次与责任范围逐请求由卡片接口返回，不把大量学生或授课名单塞入登录响应，也不再单建 `GET /me/staff-profile`。

绑定前可选择学生/教工绑定；绑定完成后重新读取 `/me`。教工输入 `staff_no` 和明确的 `binding_code`，不能复用旧学生适配里“姓名兜底绑定码”的别名处理。教工身份不得被学生专用绑定守卫挡住；也不得借新教工身份放宽学生本人接口。

前端请求上下文至少包含账号、模式、工作视图、学期、相关范围筛选和授权修订。切换或退出时清理敏感列表及照片链接，旧异步响应不得回填到新视图。`view` 和筛选只收窄服务端范围，不接受传任意 staff_id 来切换身份。

## 4. 新增接口规划

实现状态（2026-10-18，本地 `dev-main`，未部署）：下表除标注“未实施”的行外均已实现，可对照
[API 契约](../API_CONTRACT.md) 与 [openapi.json](../openapi.json) 核对。`GET /me/staff-profile`、
`GET /me/teaching-classes`、`GET /me/teaching-classes/{id}/occurrences`、`GET /me/responsible-classes`
未实施：可用视图与身份模式在 `GET /me` 的 `app_context` 返回，本人课次与责任范围由
`GET /me/inspection-records*` 的授权谓词按任务卡片表达，小程序如确需按教学班聚合，等真实端侧诉求
出现后再补，不预先建第二套列表。已实现但未列在本表的两条：
`GET /me/attendance-records/{record_id}/versions?view=teaching|responsible` 返回某条考勤的认定历史
（版本、认定、来源、时间、备注），与卡片明细的 `view_history` 动作配套；
`GET /me/teaching-occurrences?date_from=&date_to=` 返回本人正式课次日历，与是否被抽到查课无关，
端侧“给某一节课换教室”应以它而不是查课卡片为数据源（`GET /me/teaching-classes/{id}/occurrences`
的未实施部分由这条区间查询承担）。

| 产品动作 | 拟定接口 | 关键参数/响应 |
| --- | --- | --- |
| 教工绑定 | `POST /me/staff-binding` | `staff_no`、`binding_code`；核销后重新读取身份 |
| 教工档案和职责 | `GET /me/staff-profile` | 本人档案、有效授课/责任关系摘要 |
| 我的教学班 | `GET /me/teaching-classes` | 学期、分页；返回教学班、课程及本人授课关系 |
| 我的授课日程 | `GET /me/teaching-classes/{id}/occurrences` | 日期范围、分页；返回真实课次、当前地点和地点修订 |
| 更换指定课次教室 | `PATCH /me/teaching-classes/{id}/occurrences/{occurrence_key}/location` | 新教室、地点修订；返回新修订及影响任务摘要 |
| 教工考勤卡片 | `GET /me/inspection-records` | `view=teaching/responsible`、学期、日期、教学班/责任班级、任务负责学院及分页；筛选均与授权取交集 |
| 卡片详情 | `GET /me/inspection-records/{task_id}` | 同一 `view`，仅返回获授权上下文、统计和可用动作 |
| 卡片内学生考勤 | `GET /me/inspection-records/{task_id}/attendance` | 同一 `view`、分页、状态筛选；不返回无权学生 |
| 教师更正 | `POST /me/teaching-attendance/{record_id}/corrections` | `attendance_type`、`current_version`、可选 `reason` |
| 我的责任班级 | `GET /me/responsible-classes` | 当前有效责任范围；历史查询范围由明确授权决定 |
| 我的班级异议待办 | `GET /me/responsible-objections` | 状态、学期、分页；明确返回有权审核的待处理数量 |
| 异议详情 | `GET /me/responsible-objections/{objection_id}` | 当前考勤版本、原诉求、材料 ID、可否审核及限制原因 |
| 一次审核 | `POST /me/responsible-objections/{objection_id}/review` | 沿用 `decision/final_type/comment/current_version` 语义 |
| 同范围统计/导出 | `GET /me/inspection-records/summary`、`GET /me/inspection-records/export` | 同一视图和筛选，标明统计范围与任务归属 |

教工列表是只读聚合；更正、审核、任务执行各调用自己的命令入口。未绑定或未获授权的请求不能退回全院查询。越权资源不泄露存在性，失效会话返回 401、无操作权限返回 403、不可见资源返回 404、版本冲突返回 409、字段错误返回 422；错误结构复用项目现有规范。

`occurrence_key` 由正式课次解析产生并返回，客户端视为不透明字符串，不使用课名、节次文案或数组序号拼接。覆盖合并课次和调补课，地点修订与任务锁版本分别命名，不共用一个模糊的 `version`。

共享课程返回已确认的 `academic_offering_id` 及可见的教学班视图引用，客户端不按名称自行合并课程。授课日历可按已确认共享身份展示一次，但多个学院的查课记录必须分别保留任务 ID 和负责学院；没有共享确认时保持独立。

## 5. 卡片与学生明细字段

教工卡片的拟定投影：

```json
{
  "task_id": "20001",
  "teaching_class_id": "30001",
  "occurrence_key": "opaque-occurrence-key",
  "course_name": "示例课程",
  "responsible_college": {"id": "101", "name": "示例学院"},
  "inspection_date": "2026-10-19",
  "starts_at": "2026-10-19T08:00:00+08:00",
  "ends_at": "2026-10-19T09:35:00+08:00",
  "classroom": "教学楼A-101",
  "location_revision": "opaque-location-revision",
  "attendance_state": "RECORDED",
  "scope": {"view": "responsible", "count_basis": "AUTHORIZED_STUDENT_SET"},
  "counts": {"total": 30, "NORMAL": 27, "LEAVE": 1, "LATE": 1, "ABSENT": 1},
  "allowed_actions": ["view_detail"]
}
```

`counts` 仅代表本视图有权读取的正式考勤，例中人数为虚构。未形成正式记录时 `attendance_state` 表示尚未形成考勤，`counts` 为空，不伪造正常或缺勤人数。卡片标题明确“仅统计负责班级”或“本人授课记录”。全部学院检查同时出现时，保留各自任务，不按课程名折叠掉归属。

学生明细的拟定投影：

```json
{
  "attendance_record_id": "40001",
  "task_id": "20001",
  "student_id": "50001",
  "student_no": "000000001",
  "name": "示例学生",
  "administrative_class_name_snapshot": "示例班",
  "effective_type": "ABSENT",
  "current_version": 3,
  "photo_file_ids": ["60001"],
  "allowed_actions": ["view_history", "correct"],
  "restriction_reason": null
}
```

动作按每条学生记录、当前视图与最新范围计算，不能只在整张卡片上设置一个 `can_edit`。服务端仍对写入重新鉴权。`current_version` 是该考勤记录的版本，不能拿任务版本或照片版本代替。列表、统计、详情、导出均先按相同授权范围过滤再分页。

课次开始/结束时间采用带时区的 ISO 8601；纯日期使用 `YYYY-MM-DD`，节次描述只供显示，不在前端重新推算正式时间。所有 ID 和不透明修订均按字符串传递。

## 6. 更正与审核的命令差异

教师直接更正：

```json
{"attendance_type":"LEAVE","current_version":3,"reason":""}
```

辅导员通过异议：

```json
{"decision":"APPROVED","final_type":"LEAVE","current_version":3,"comment":""}
```

驳回使用 `decision=REJECTED`，不传 `final_type`。两种命令复用已有领域事务、版本和审计，不能共用一个含义不明的“保存考勤”接口。重复点击不生成重复更正；收到 409 必须刷新详情并重新核对，禁止自动读取新版本后悄悄重试原决定。

本地 `api/record.js` 当前将学生申诉 `desired_type` 固定为 `NORMAL`，后续端侧适配应显式接收用户选择的目标类型。学生自己提出异议、任课教师直接更正、辅导员一次审核是三种不同命令，组件复用不能把它们接到同一个提交函数。

教师更正不自动关闭待处理异议；辅导员对外院任务只能按额外授权协助查看，不具备默认直接审核能力。重新进入详情时读取当前操作能力；前端按钮隐藏不代替后端拒绝。

## 7. 前端复用和需要新增的内容

建议后续小程序开发按以下职责拆分，不按每个角色复制一套页面：

| 层 | 建议文件或组件 | 职责 |
| --- | --- | --- |
| API | 扩展 `api/user.js`，新增 `api/staff.js`、`api/staff-records.js` | 身份、授课、教工记录与独立写入命令；保留 `task.js/record.js` |
| 上下文 | `utils/work-context.js` | 模式/视图与账号隔离、请求失效；不存服务端授权真相 |
| 组件 | `inspection-record-card` | 渲染卡片，不自行请求全局名单或判断角色权限 |
| 组件 | `attendance-roster`、现有照片预览能力 | 受限学生明细、状态、按授权获取图片链接 |
| 表单 | `attendance-correction-form`、`objection-review-form` | 可复用状态选项和样式，命令、必需版本与提交回调分别定义 |
| 页面容器 | 课程/考勤/我的及现有详情页 | 加载、分页、视图切换、导航和失败提示，消费 API 适配后的模型 |

学生本人记录、志愿者任务、教工卡片都可以使用相同的视觉组件，但通过适配层形成各自模型。志愿者“待执行/已提交”和学生“正常/迟到/请假/旷课”不是同一状态，不能强行合成一个枚举。

新卡片与详情须处理加载、无课、未查、无权、接口失败和版本冲突，不用一条“暂无数据”覆盖所有情况。文件 URL 过期可重新申请授权；无权错误不持续重试。公共短期 URL 不保存成长期业务数据。

## 8. 调用流程与本轮交付

1. 登录 → `/me` → 有效模式与视图 → 首次绑定或进入上次选择。
2. 教工课程 → 教学班/真实课次 → 修改指定日期教室 → 返回影响摘要 → 志愿者刷新任务读取新目的地。
3. 教工考勤 → 明确工作视图 → 卡片 → 授权学生子集 → 教师更正或进入责任区异议详情 → 独立命令 → 刷新卡片、明细和统计。
4. 学生课表 → 已发布正式来源/个人备份 → 本人主动操作；教工地点修改不直接写入个人备份。
5. 学生考勤 → 本人记录 → 明确申诉类型/材料 → 一次审核结果；无新增多级审批。

本轮后端/Web交付身份与关系底座、教工只读聚合、两条写入事务、地点联动及管理/本人 Web 页面。小程序交付本设计、后续实际生成的契约与示例、可用接口状态和有限联调清单；本轮不实现组件、TabBar 或真机验收。

验收采用正常流程加定向越权/冲突场景，覆盖多重身份、责任名单子集、外院审核拒绝、教师更正历史、地点变更后的新旧任务，以及旧学生/志愿者接口兼容。不得用“复用 70%”“零越权”“秒级推送”等未经测量或不具备机制支持的承诺作为验收结论。
