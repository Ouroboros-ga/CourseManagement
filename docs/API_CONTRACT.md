## 2026-10-24 本人申诉进度（候选）

新增GET `/api/v1/me/objections/{objection_id}/progress`，原Bearer及实际本人绑定，不接受客户端指定身份。返回办理阶段及正式状态，不返回内部任务或AI建议；归档/撤回历史仍只限本人。功能标记关闭404，GET不登记任务或改写结论。当前REST快照358路径/421操作。字段和端侧适配见[本人进度合同](integration/WECHAT_OBJECTION_PROGRESS_20261024.md)，小程序页面、真机及真实ADP/MySQL未验收。

## 2026-10-24 申诉预审管理（本地候选）

新增学院预审策略GET/PUT、单条申诉最新预审状态GET、安全重试POST。路径及请求见[预审管理接口](development/OBJECTION_PRECHECK_MANAGEMENT_API_20261024.md)。沿用Bearer、实际教务角色和原学院/责任区范围，重试追加记录且要求旧云实例已确认结束；未知执行不盲目重发，归档学期只读。终审服务端约束、意见与终审表单及学院策略页面已有候选；真实ADP和MySQL仍待验收，默认关闭、未部署。详见[终审衔接](development/OBJECTION_PRECHECK_FINAL_REVIEW_20261024.md)及[学院开关](development/OBJECTION_PRECHECK_POLICY_UI_20261024.md)。

管理API批次普通REST OpenAPI候选为357路径/420操作；当时增加3路径/4操作，无删除路径。智能体工具继续使用独立小型合同，不把此快照视为生产已启用清单。

## 2026-10-21 学生资料与教工查课修复

2026-10-24 工具网关本地候选：默认关闭的 HTTP `/api/v1/agent-tools/v1/calls/{tool_name}` 与 MCP `/mcp/agent-tools`，复用运行身份和现有领域权限。交互入口支持6个只读／状态／探针工具，AUTOMATION/change另有2个绑定申请的换班工具、AUTOMATION/objection另有3个绑定申诉的预审工具；以及登录后的 `/api/v1/assistant/tasks` 创建、查询、取消；无公网运行凭据签发接口。专用合同见[工具网关合同](TOOL_GATEWAY_CONTRACT.md)及[小型 OpenAPI](agent-tools.openapi.json)。需迁移到 `f26a1024a009`；未联调腾讯云或部署，不能沿用历史生产路由数字推断已启用。

GET `/me` 增加 `student_no/college_name` 及 `app_context.student`，按本人绑定ID和当前日期学籍读取；无绑定为null，不改变角色、权限或教师摘要。GET `/me/inspection-records` 修复跨任务来源关联，旧误放行的卡片不再可见，详情/名单同样拒绝；`starts_at/ends_at` 明确附带UTC偏移，新增 `start_period/end_period`。详情见 [小程序接口修复交接](integration/WECHAT_ME_STAFF_FIX_20261021.md)。没有新增路径或迁移。

## 2026-10-21 管理端考勤分组

- 新增 GET `/api/v1/attendance/groups` 与 `/api/v1/colleges/{cid}/attendance/groups`。前者仅供旧全校管理模式；正式学院模式继续关闭旧入口。后者复用 `attendance.read`、学院与资源范围，任职本人入口和学生小程序入口不扩权。
- `group_by=task|administrative_class`，默认 task；`semester_id/page/page_size/effective_type` 与原管理列表一致，默认50组。课次按具体任务ID分组，合班课、重复任务与不同负责学院不按课程名混并。行政班按名单中的历史ID分组，不关联当前学籍猜补；未知ID单列“历史班级待核对”。班级标签取已有历史名称，不据当前班级改写。
- 分组和管理列表共享新增过滤：`start_date/end_date`（含首尾）、`keyword`（姓名/学号/历史班级/课程/教学班/教室）、`administrative_class_id`、`unknown_class`、`abnormal_only`；原 `course_type_id/group_id/teaching_class_id` 维度继续可用。日期倒置返回422；过滤只收窄原授权范围。
- 返回 `items/total/page/page_size/group_by/summary`。total为组数；summary及各组含 `record_count/task_count/normal_count/late_count/absent_count/leave_count`，按完整筛选范围的当前有效考勤计算。记录数不是学生去重人数，不生成缺乏依据的应到分母或出勤率；状态/仅异常过滤会先筛记录，再计算汇总。
- 课次项含 `task_id/course_name/teaching_class_name/inspection_date/start_period/end_period/classroom/volunteer_name`；执行人取最后通过提交的账号对应姓名，无可靠提交时明确待核对。行政班项含 `administrative_class_id/class_name`；null ID可用 `unknown_class=true` 下钻。
- 管理列表/详情增加 `administrative_class_id/administrative_class_name`。历史名单优先取最后通过提交的 roster_version，无通过提交时回退任务版本；名单唯一连接避免多版本放大计数。学生个人响应不新增学院或管理字段，照片仍使用既有授权签名入口。

Web按课次默认展示；行政班进入该班各次查课，再打开名单与照片，名单按需分页。新Web与后端需成套发布，细节与状态见 [实施记录](archive/2026-10-24/operations/ATTENDANCE_GROUPING_20261021.md)。

## 2026-10-21 排班预览展示资料

`POST /api/v1/colleges/{cid}/groups/{gid}/inspection/assignment-plans/preview` 的响应新增 `data.display`，原请求和确认提交契约不变，不新增路由或权限。

- `group_name/semester_name`：本次执行组、学期名称。
- `tasks`：以字符串任务 ID 为键，值包含 `course_name/teaching_class_name/classroom/inspection_date/start_period/end_period`；来源为已通过原范围校验的目标任务快照。
- `volunteers`：以字符串账号 ID 为键，值包含 `name/student_no/administrative_class_name`。仅查询本次拟派发人员，单次批量列投影，不返回完整候选池或账号敏感字段。班级为当前档案班级，不作为历史考勤快照或排班输入。
- `display` 仅供展示，不写入冻结确认集合，不参与 revision，也不增加 `assigned` 项字段。确认仍提交原 `plan_id/revision/confirmations`，按精确任务、人员及警告校验。预览不创建正式受派。
- Web 支持拟派发/未分配分栏、姓名/学号搜索与每页50项展示。筛选与翻页不改变计划、总派发数；取消、零分配或上下文过期不提交。新 Web 与后端建议成套发布；旧响应缺少展示资料时明确显示“姓名暂不可用”，不把编号冒充姓名。

实现、验证与部署状态见 [排班预览改版记录](archive/2026-10-24/operations/ASSIGNMENT_PREVIEW_REDESIGN_20261021.md)。

> **2026-10-19 查课与组织修复候选（尚未部署）：**
> - `GET /api/v1/inspection-course-occurrences` 及学院别名新增可选 `course_type_id`；`POST .../smart-sample` 同名字段可选。按数据库课程类型 ID 筛选，不按课程名猜测；类型进入精确课次范围和修订摘要，确认时重算，过期选择拒绝。旧调用不传字段仍保持原范围。
> - 组织模式的课次查询/推荐向执行组校验传递 semester_id，使用学期有效规则；组织排班关闭时，显式传 execution_group_id 返回 409，不能悄悄忽略组并使用旧全院候选池。
> - `GET /api/v1/colleges/{cid}/academic/students` 接受 `is_volunteer=true/false`，须同时提供 semester_id；WHERE 条件在分页/计数前生效，并与原学院/行政班范围取交集。
> - 组成员、支援、请假、组织学期准备、负责人交接和权限来源的管理接口保留学院配置/正式业务开关与各动作授权，不再要求实际作息/组织排班开关。抽查、生成组织任务、排班和独立作息入口保留原运行守卫。
> - 删除没有成员/任务/学期准备/授权引用的志愿者组时，可同时清理其未使用配置和类型引用；保留删除前快照及原发布审计。成员等已有业务引用时返回409。课程类型原有内置标识/引用保护和任务正式考勤/截止事实保护继续有效，不新增强制擦除历史入口。
> - 本轮无数据库迁移、无小程序接口破坏性变化、无生产数据回填或开关修改。

> **2026-10-16 个人课表兼容发布：** 新增 GET `/api/v1/me/class-timetable`、GET/PUT `/api/v1/me/timetable-backup`，以小程序本地编辑＋完整快照备份为准；不新增必填学院或current_version。原逐条接口保留，迁移头f26a1016b001，应用源码37e4440。具体字段、空备份及多设备覆盖边界见[现行课表交接](integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md)。

> **2026-10-16学生端兼容收口：** `GET /me/attendance`及学生的`GET /attendance/{id}`恢复升级前考勤结构，不含负责学院/semester_status。管理端学院接口保留这些字段。个人课表新增接口为可选能力；本次学院/Web升级不要求小程序修改路径、增加学院参数或页面。后文旧版小程序学院展示建议由本条替代。

> **2026-10-16 实际发布：** 后端/Web已部署，结构头 `f26a1016b001`；配置、院级教务、教务发布已开，正式业务隔离及组织排班未开。下文旧批次“未部署”是历史描述，当前边界以[实施状态](development/IMPLEMENTATION_STATUS.md)为准。

> 文档定位：已有 API 与按日期保留的兼容契约。当前进度见[实施状态](development/IMPLEMENTATION_STATUS.md)，新增重构设计中的拟议能力不代表已开放接口。正文历史段落的“尚未部署”、旧迁移号及测试数字仅描述其当时批次；实际请求核对挂载路由、schema 和运行配置。

## 2026-10-20 统一分页与查询优化（已于正式服务部署）

- 共用分页默认值统一为 `page=1&page_size=50`，显式传入的旧页大小继续有效。列表总数在授权范围和筛选之后计算，不能用本页长度替代总数。
- 任务列表及学院别名新增 `keyword/status/pending_change` SQL 筛选及完整窗口 `summary`；`GET /inspection-tasks/export` 导出完整筛选结果，忽略页码。关键字、日期、状态只影响列表 `total`，周/学期待办摘要保留原窗口。
- 提交审核列表新增 `keyword/result` 和窗口摘要。授课/责任关系支持 `paged=true` 并附带姓名、工号、班级名；原数组调用兼容。负责人目标支持分页、关键字和角色/候选筛选；本页资格、账号、可选权限可通过受限 ID 集合批量读取。
- `GET /colleges/{cid}/volunteer-groups/semester-overview` 批量返回所选学期的真实规则与参考日成员数；人数不代表最终可排班人数。
- 正式课表列表新增分页。指定行政班时仍按日期学籍核算，报表与抽查仍保留完整业务快照；前端分页不改变统计、整批确认或排班的业务范围。
- 遗留资格 GET 不再隐式创建账号/角色或提交事务，资格维护和绑定写流程负责开通。

完整参数、兼容边界与各页取数方式见 [统一列表与查询整改](development/LIST_PAGINATION_QUERY_AUDIT_20261020.md)。新前端依赖新后端，应成套发布、成套回滚；本轮没有数据库迁移或生产开关变更。

# 2026-10-15 R2/R3 本地开发增量

本节代码已在2026-10-16的R6发布中提交并部署；生产相关入口仍受实际业务开关约束。没有新增数据库表或迁移。原接口及旧 bulk 保持兼容。

## 工作台与日期学籍

- GET `/api/v1/colleges/{cid}/overview?semester_id=...`：要求学院配置启用，按每项真实动作与资源上限返回 `college_id/semester_id/semester_status/as_of/items/runtime/scheduling_note`。`items` 的每项包括 `id/label/count/status/scope_label/destination`；状态为 `ACTION_REQUIRED/COMPLETE/AVAILABLE/EMPTY`。没有权限的项省略，不能把省略解释为零。受限组只统计可见组；成员是当日有效成员去重，资格是本学期当日学籍与资格核对，不代表具体任务可排班人数。
- GET `/api/v1/colleges/{cid}/academic/students` 增加可选 `as_of=YYYY-MM-DD`：使用该日半开区间学籍归属，继续执行本院 student.read。返回学生附加 `as_of/enrollment_source/enrollment_snapshot`，班级、学院与学籍状态按当日事实；姓名、学号仍为当前标识。显式日期不以当前班级补造缺失历史。不传日期继续查当前档案并兼容无时间线的旧当前记录。其他资源不接受日期学籍筛选。
- GET `/api/v1/objections` 与 `/api/v1/colleges/{cid}/objections` 增加可选 `semester_id`；通过所属任务筛选，列表和 total 共用范围，不改变一次审核与详情授权。旧调用不传参数仍可跨学期查询。
- GET `/api/v1/inspection-tasks` 及学院别名增加可选 `needs_attention=unassigned|roster`，仅筛选未取消任务，分别为无当前受派、需要核对名单。可与 semester_id 和分页组合；已有任务可见性不变。

## 明确导入确认集合

前提：学院配置及正式业务开关已启用。每个目标均在事务内重新核对 `import.execute + 对应目标管理动作`。现有 multipart POST `/api/v1/colleges/{cid}/imports` 继续仅创建预览草稿；单文件限制 10 MiB。标准表、行政班名单、网格课表记录可定位的实际来源行，网格同时记录原工作表与列。学号保持字符串，源文件 SHA-256 仅作来源识别，不替代正式数据差异核对。

1. POST `/api/v1/colleges/{cid}/imports/confirmation-set/preview`，JSON `{ "batch_ids": ["123", "124"] }`。一次 1—20 个不同预览，同一学期（行政班基础名单独立于学期），变更项总量不超过 `IMPORT_MAX_ROWS`（默认 5000）。只读正式资料、返回核对结果，不执行正式写入。
2. 响应包括 `revision/batch_ids/files/can_confirm/limits/impact_note`。每个文件有 `id/filename/target/summary/issues/changes`；差异有 `action=CREATE|UPDATE|UNCHANGED`、`entity/key/before/after/source`。来源包括文件、可用的工作表/行/列；合并名单按学号定位。问题按 `severity/message/filename/row/field` 展示。阻断问题会使整个集合不可确认；移除文件后必须重新核对。
3. POST `/api/v1/colleges/{cid}/imports/confirmation-set/confirm`，JSON `{ "batch_ids": ["123", "124"], "revision": "预览返回的64位哈希" }`。锁定授权学院、学期及具体批次，核对正式来源和选择集合，复用不自行提交的底层写入，所有正式写入、批次状态与审计一次提交。响应为 `status=CONFIRMED/batch_ids/files`，文件结果带 summary。
4. 正式来源、集合变化或预览过期/失效返回 409；存在内容阻断项返回 422。预览过期或已失效需重新上传。任意后续文件写入失败时，整个集合回滚，草稿保持可核对状态。完全相同集合与 revision 的成功请求重试返回已有结果；子集或混合已确认文件不作为新集合放行。
5. 新向导中的教学班名单、选修名单为补充语义，未出现的人不删除，学籍驱动名单仍要求走学籍流程。同集合重复文件跳过；重新上传对照当前事实，已有相同课表不再追加。多个文件修改同一资料、集合内课表重叠、与旧课表冲突或缺少周次均阻断。不能确定替换对象的时间/地点变化先通过课程维护或停补课处理，不自动删旧课表。归属变化走交接，不通过导入转班。
6. 导入不等于正式发布，也不覆盖学生个人副本。依赖资料按“先行政班与学生、再课表与选课、再资格”分批确认，不承诺解析时跨未确认草稿自动建立外部引用。

旧 `/imports/bulk` 是逐文件预览并确认：前面的成功文件不会因后续失败回滚。Web 将它标记为旧兼容入口，不能用它冒充新集合事务。标准长表旧算法漏保存周次及漏递增数量的问题已修复，仅影响后续执行，不自动修复历史数据。

# 2026-10-15 P5 交付增量

云端个人课表实际接口与业务语义见 [微信小程序接口](integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md)，发布验收见 [P5 发布记录](archive/2026-10-15/operations/P5_RELEASE_20261015.md)。以下保留历史契约；与该增量冲突时以本轮已验收接口为准。通知仅展示，没有已读/采用；绑定完成后由客户端调用初始化。

# 后端 API 契约（身份、基础数据、导入、查课、提交、考勤、异议、统计与版本化周报）

## 2026-10-14 开发增量：明确发布、云端私人课表和简单通知

当前工作树实现，尚未部署。新迁移 `f26a1014p001` 接已发布的合并 head `f26a1014m001`；默认 `ACADEMIC_PUBLICATION_ENABLED=false`。院级正式发布还需学院配置和基础数据范围模式启用，不能与旧全局教学写入口并行开放。

正式发布与管理总课表查询分离。POST `/colleges/{cid}/academic/semesters/{sid}/publication-preview` 返回 `source_revision/current_version/schedule_count/student_count/changed`；随后 `/publish` 接受 `{source_revision}`。均要求本院 `academic.manage`，提交锁学院和源数据；源、授权或已发布版本变化返回 409。相同内容确认返回 `changed=false`，不产生新发布或重复通知。未发布修改不改变初始化来源；名单、时刻、周次和校历冻结，不能把同班选修并集当作本人课程。

绑定后先 GET `/me/timetable/semesters`，再 POST `/me/timetable/initialize`（`{"semester_id":"101"}`）。初始化按学生＋学期唯一，已有副本（包括删空）返回原内容；未发布返回 `NOT_PUBLISHED` 且不创建副本。GET `/me/timetable?semester_id=101` 读取本人最后保存的云端内容，未初始化返回 `NOT_INITIALIZED`。成功初始化状态 `INITIALIZED`，含 `current_version/source_revision/sources/entries`；来源校历是复制内容，不随教务变更移动个人时间。

个人课程 API 均带 semester_id 查询参数：POST `/me/timetable/entries`、PATCH/DELETE `/me/timetable/entries/{eid}`。写请求必填 current_version，旧版本返回 409；条目 ID 为 UUID 字符串。新增示例：`{"current_version":1,"course_name":"本人选修","weekday":1,"week_nos":[1,2],"start_time":"07:00:00","end_time":"07:30:00","note":""}`。可改名称、教师、教室、星期、周次、时刻、备注；拒绝 student_id、college_id 或来源标识等所有权字段。删除体 `{current_version}`。成功返回整份个人内容与新版本；课程重叠不按查课规则拒绝保存。

GET `/me/academic-notices?page=1&page_size=20` 返回 `items,total,page,page_size`，项含 `id,college_id,semester_id,version,published_at,title,message`。仅本人相关内容变化时展示，移出正式名单者仍收到该次提示。没有已读/未读、忽略、采用或微信推送，通知不修改个人副本。

私人课表仅供本人便利使用，管理员无代读/代改入口。每次核对真实账号、学生状态与绑定；私人保存不写正式课表、名单、任务、考勤或报表修订。单次课程例外和整表恢复尚未实现，不宣称已提供。

院级考勤/异议见接口索引；`CAMPUS_BUSINESS_SCOPED_ENABLED` 默认关闭，其他模块未全部接入前不得启用。启用后旧全局考勤管理/更正与异议审核拒绝；本人路径仍限定本人。新版异议改判权限必须来自同一学院，不能拼合外院能力。

## 考勤现场照片与 Web 时间（2026-10-14）

- `/api/v1/me/attendance`、管理考勤列表及单条详情的每条考勤新增 `photo_file_ids: string[]`；无照片为 `[]`。仅返回文件 ID，不暴露 object_key 或裸下载地址。
- 照片来自该任务已通过审核的提交，要求学生存在于该提交的名单版本。正常出勤同样可查看；不依赖只记录异常学生的 `source_submission_item_id`。任务正常约束只允许一条通过提交；异常历史数据存在多条时选最后通过的 attempt。此字段表示任务现场材料，不是考勤改判版本的独立照片快照。
- 学生持有 `attendance.read`、已完成绑定、账号有效且拥有该任务的正式考勤时，可对这些现场照片调用 `/api/v1/files/{id}/access`。服务端重新查询账号绑定和业务关联；他人、未关联、待审、驳回或非现场照片不获得这条新增授权。原上传者/志愿者/审核者权限保留。
- 文件保留期及状态检查继续适用，过期或已清理返回 `FILE_EXPIRED`。返回的短期签名链接在有效期内可使用，解绑后不能申请新链接；既发出的链接不即时撤销。照片 ID 保留以区分“无照片”和“历史材料已过期”。
- 旧 API 的无时区 datetime 明确为 UTC。Web 异议、提交审核、换班申请及绑定码时间统一转换为 `Asia/Shanghai`；显式 `Z`/偏移按实际时刻转换，不重复加 8 小时。校历日期和课节时间保持原语义。
- 无数据库迁移，小程序界面及真机照片显示需另行联调。本地副本不能作为第三方当前小程序已适配字段的证明。

## 院级基础数据接入（2026-10-13，逐入口实施）

需配置及院级基础数据开关同时启用，默认关闭。接口使用 `/api/v1` 前缀和统一信封，对外 ID 为字符串。

| 路径 | 契约 |
| --- | --- |
| `/colleges/{cid}/academic/{kind}` | GET，分页及关键词/学期/行政班过滤；返回 `items,total,page,page_size` |
| `/colleges/{cid}/academic/{kind}/{rid}` | GET，外院和未知归属 404 |
| `/colleges/{cid}/academic/administrative-classes` | POST，服务端决定学院；未知所有权字段 422 |
| `/colleges/{cid}/academic/administrative-classes/{rid}` | PATCH，必填 `ownership_version`，陈旧 409；可空字段显式 null 清除，名称/状态不得为 null |
| `/colleges/{cid}/academic/teaching-classes/{rid}/roster` | GET / PUT；PUT 必填学生 ID 字符串集合与归属版本，范围整批校验、变更和审计同事务 |

kind 为 `administrative-classes/students/teaching-classes/schedules/courses/semesters/qualifications`。课程/学期是学校共享只读目录，其余按学院和父链；资格 GET 无身份副作用。新增院级动作 `academic.read/manage`、`student.read/manage`、`volunteer.read`，不得跨学院拼接；当前 manage 接入行政班及名单写入，其他写入尚未提供。

`CAMPUS_ACADEMIC_SCOPED_ENABLED=true` 拒绝旧 academic 私有/管理及独立课表导出，保留学校共享只读目录。其他模块全链路隔离仍未完成，`business_ready=false`，不得据此开放第二学院正式业务。

## 2026-10-13 更新：学生考勤异议一次审核

本节替代旧初核/终审两阶段说明。`POST /api/v1/objections/{id}/review` 使用原 `ObjectionFinalReviewRequest`：decision=APPROVED/REJECTED，current_version 必填；通过须提供 final_type，备注选填。学生负责人、教师管理员、超级管理员默认具有 `objection.final_review`；更正考勤仍需 `attendance.correct`。批准在同一事务更正考勤、追加 OBJECTION_FINAL 版本、记录审核人及审计、推进报表源修订。考勤版本冲突与重复审核仍返回 409。

`final_status` 为唯一处理状态：PENDING/APPROVED/REJECTED，分别对应待审核/审核通过/审核驳回。列表支持 final_status 与分页，响应增加 final_reviewed_username 和 final_reviewed_display_name，审核人 ID 仍为字符串。旧 initial_* 字段仅保留历史，不是待办步骤；旧 initial-review 入口返回 409 STATE_CONFLICT 提示刷新客户端，旧 final-review 兼容一次审核事务。

已有数据库发布前执行 Alembic 181729fc7239，或按标准 seed 同步默认角色权限。2026-10-13 已完成线上迁移及权限核验，见 RELEASE_ACCEPTANCE.md 的本次发布记录。


| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-27（按当前代码修订） |
| 权限基线 | [PERMISSIONS.md V1.1](./PERMISSIONS.md)（第 12 节 API 映射为权威来源） |
| 当前实施对照 | [实施状态](development/IMPLEMENTATION_STATUS.md)；旧本地权限实施文档不再作为仓库入口 |
| 范围 | 描述当前 `main.py` 已注册的 P1–P7、管理补全与 2026-10-17 教工协作 API；P7 统计与版本化周报见附录 F，教工契约见“教工协作增量契约”。实际完整路径及 329 个路径、390 个操作见 [API_INDEX.md](./API_INDEX.md)，机器可读 schema 见 [openapi.json](./openapi.json)。管理补全综合回归进行中；正式学校模板与真实微信前端联调仍待验收，教工入口尚未部署。 |
| 代码 | `backend/app/modules/identity/{router,service,schemas,repository,wechat,deps,staff_binding,staff_deps,staff_scope}.py`、`backend/app/modules/audit/models.py`、`backend/app/modules/academic/{router,service,schemas,repository,models,staff_router,staff_service,staff_schemas,staff_repository,staff_rules}.py`、`backend/app/modules/importer/{router,service,schemas,repository,models,permissions,staff_adapter}.py`、`backend/app/modules/inspection/*`（含 `staff_record_{router,query,schemas}.py`）、`backend/app/modules/attendance/*`、`backend/app/modules/file/*`（含 `staff_access.py`）、`backend/app/modules/objection/{router,service,schemas,repository,models,permissions}.py`、`backend/app/modules/report/`（含 `staff_export.py`）、`backend/app/common/parsing/{time_slots,xlsx_tabular}.py` |

## 1. 通用约定

- 前缀：业务 API 均为 `/api/v1`（`/health/*` 除外）。
- 成功响应信封：`{"data": <载荷>, "requestId": "<uuid>"}`。`requestId` 同时以响应头 `X-Request-Id` 返回，并写入审计与日志关联。
- 错误响应信封：`{"code", "message", "fieldErrors", "requestId"}`。`code` 为稳定业务错误码；`fieldErrors` 为字段级补充（可空对象）。不返回堆栈或数据库内部信息。
- ID 一律以字符串对外暴露（BIGINT 防 JS 精度丢失）。
- 版本字段命名按各域 schema：身份授权的角色替换与个人可选授权请求用 `lockVersion`（Pydantic alias），对应响应为 `lock_version`；查课人工分配、取消、名单改版、日截止修改及应到人数调整请求均用 `lock_version`；考勤更正与异议终审请求用 `current_version`。前端须按对应接口模型传参，不能全局转换。
- 访问令牌：`Authorization: Bearer <access_token>`，有效期 15 分钟（`ACCESS_TOKEN_EXPIRE_MINUTES`）。每次请求都回查会话有效性，不单纯信任 JWT 签名。
- 刷新凭证传输分两条路径（技术方案 7.1）：
  - Web：`refresh` 经 `HttpOnly`、`SameSite=Lax`、`Path=/api/v1/auth` 的 Cookie 下发（`Secure` 生产必须开启）；响应体只含访问令牌，绝不含 `refresh_token`。`/auth/refresh` 走 Cookie 时叠加 CSRF 校验。
  - 原生/小程序：无 Cookie 语义，`refresh` 在 JSON 请求/响应体中往返。

## 2. 令牌传输契约速查

| 端点 | 客户端 | refresh 来源 | refresh 去向 | 响应体含 refresh？ | Set-Cookie？ |
|---|---|---|---|---|---|
| `POST /auth/web/login` | Web | — | 响应头 Set-Cookie | 否 | 是 |
| `POST /auth/wechat/login` | 小程序 | — | JSON 体 | 是 | 否 |
| `POST /auth/refresh` | Web | 请求 Cookie | 响应头 Set-Cookie | 否 | 是 |
| `POST /auth/refresh` | 小程序 | JSON 体 | JSON 体 | 是 | 否 |
| `POST /auth/logout` | Web | — | 清除 Cookie | 否 | 是（清除） |

## 3. 端点明细（身份 / 会话）

### 3.1 `POST /auth/web/login` — 账号密码登录（公开）

请求：`{"username": string, "password": string}`
成功 `200`：`data = {access_token, token_type:"bearer", expires_in}`；并下发 refresh Cookie。
错误：`401 UNAUTHENTICATED`。账号不存在与口令错误统一返回“账号或密码错误”，两条路径均执行 Argon2 校验以降低时序枚举风险；不保证网络响应耗时完全相同。“账号未启用”仅在口令正确后返回。`429 STATE_CONFLICT`（连续失败触发锁定）。

### 3.2 `POST /auth/wechat/login` — 微信登录（公开，P2）

请求：`{"code": string}`（`wx.login` 临时凭证，1–512）。
前置：`WECHAT_LOGIN_ENABLED=true`，否则 `403 FORBIDDEN`。
行为：`code2session` 换取 `openid` → 按 `appid+openid` 定位账号；不存在则自动创建"无口令、无角色"账号并写入 `wechat_identity`。签发 `WECHAT` 会话。首次登录（无 `student_id` 且无角色）→ `need_binding=true`，会话处于 PRE_BINDING 受限态。
成功 `200`：`data = {access_token, token_type, expires_in, refresh_token, need_binding}`。
错误：`401 UNAUTHENTICATED`（code 非法/已用）；`502 UPSTREAM_UNAVAILABLE`（微信超时/上游错误/响应不可解析/无有效 openid）。
安全：响应/审计/日志绝不含 `session_key`、`appid`、`secret`。

### 3.3 `POST /auth/refresh` — 刷新（轮换 + 重放检测）

无请求体（Web，从 Cookie 取值）或 `{"refresh_token": string}`（原生）。
成功 `200`：Web 返回 `{access_token, token_type, expires_in}` 并轮换 Cookie；原生返回含 `refresh_token` 的令牌对。
错误：`401 UNAUTHENTICATED`（缺凭证 / 无效 / 过期 / 重放旧凭证触发全族撤销）；`403 CSRF_FAILED`（Web 路径 Sec-Fetch-Site=cross-site 或 Origin 不在白名单）。
不变量：每次刷新旧凭证即时失效；检测到已撤销凭证被再次使用即撤销整个刷新族。

### 3.4 `POST /auth/logout` — 登出（需访问令牌）

成功 `204`（无响应体）；撤销当前会话并清除 Web refresh Cookie。

### 3.5 `GET /me` — 当前身份（需访问令牌）

成功 `200`：`data = {id, username|null, display_name, status, roles[], permissions[], binding_required, app_context}`，外层仍为 `{data, requestId}`；OpenAPI 明确公开该响应模型。
`binding_required=true` 即 PRE_BINDING 受限态（`student_id` 为空且无任何角色）。Web 管理员即使无 `student_id`，因持有角色而不进入该态。
`need_binding` / `binding_required` 均保留旧学生流程语义，不能单独用来判断教职工是否需要绑定学号。实际可用身份读取 `/me.app_context`：`modes` 为 `student` / `staff` 的可用集合，`default_mode` 为默认模式或 `null`，`administrator` 为管理身份摘要，`staff` 为有效教职工档案及 `views.teaching` / `views.responsible` 摘要。无任课或责任区的有效教职工仍有 `staff` 模式；摘要不授予资源读写权限。
`permissions` 为「角色权限 ∪ 两项个人可选授权」的实时并集，每次现取不缓存。

#### 教职工绑定兼容与可靠性

`POST /colleges/{cid}/staff/export-binding-tokens`：需要本院 `staff.manage`。请求 `{staff_ids?: string[], keyword?: string, days_valid?: integer}`；有效期默认 30 天，允许 1—90 天。未传 `staff_ids` 时，按本院、在职、未关联账号及工号/姓名关键词筛选全部分页；传入时必须为 1—500 个不同且有效的字符串 ID，不可同时传关键词。范围为空、超 500 人或选中外院/停用/已关联人员，整批拒绝，不静默截断。返回 XLSX 文件，`Cache-Control: no-store`，列为工号、姓名、所属学院、一次性绑定码、有效期截止（北京时间）。共用学生绑定码表格样式与下载工具，工号与码均为文本。后端锁定档案、复核归属，整批签发与审计在文件构建成功后统一提交；构建失败回滚，不记录明文码。既有单人签发有效期和核销接口不变；重复签发不自动撤销旧码、不授予管理角色。

`POST /me/staff-binding` 继续使用 `{staff_no, binding_code}`，不新建第二个账号或授予管理角色。不同档案可出现相同短码，核销结合工号定位，持锁后复核；同档案签发避免复用历史短码，有限重试失败返回 `409 STATE_CONFLICT`。历史已失效的重复码不遮蔽唯一有效码；仍有多个有效匹配时返回 `422 VALIDATION_ERROR`，不任取一条。原有不同短码的有效期和多码语义不变。核销采用账号→档案→凭证锁序，签发和作废也先锁档案再锁凭证。

### 3.6 `POST /me/student-binding` — 本人绑定学生（PRE_BINDING）

请求：`{"student_no": string, "binding_code": string}`。
成功 `200`：`data = {student_id, student_no, name}`。同事务核销一次性码、写 `student_id`、自动授予 STUDENT、`lock_version+=1`、追加审计。
错误：`404 NOT_FOUND`（账号/学号不存在）；`422 VALIDATION_ERROR`（码无效 / 码与学号不匹配）；`409 STATE_CONFLICT`（码已用 / 码过期 / 账号已绑定 / 学生已被他人绑定）。
并发：对同一码的并发核销以绑定码行 `SELECT … FOR UPDATE` 串行，仅一人成功，另一人 `409`。

2026-10-21 补充：认领已有学生账号时，只允许唯一微信身份的空白账号迁入，目标必须启用且未被其他微信占用，不含教师管理员/超管或教工档案。只迁移有效微信会话；已撤销会话不复活，源Web会话撤销，源账号不删除。迁移后旧JWT的sub/sid不再匹配，客户端使用原刷新凭证换取目标UID令牌，或重新微信登录。原学生UID下的任务、提交和角色不搬迁。

### 3.7 `DELETE /me/student-binding` — 微信重新绑定

成功 `200` 仍返回 `{revoked_sessions, lock_version}`。写事务内重新核验当前会话，保留原学生账号的 `student_id`、角色、可选授权和业务事实，只把唯一微信身份移至新建的无口令/无角色空白账号，并撤销原账号全部会话。客户端清理旧令牌、重新微信登录后进入绑定流程。无学生身份、微信身份不唯一、包含管理或教工身份返回409；会话已撤销返回401。历史错误归属不会由此自动恢复。

## 4. 端点明细（授权管理闭环，P1）

### 4.1 `GET /role-assignment-targets` — 角色分配目标选择器

守卫：`role.assign`。成功 `200`：`data = {items:[{id, username|null, display_name, status, roles[], lock_version}], assignable_roles[]}`。`assignable_roles` 为操作者可手工管理的角色（超管三类管理角色；教师仅 `STUDENT_AFFAIRS_MANAGER`；均不含 STUDENT/VOLUNTEER）。

### 4.2 `PUT /users/{user_id}/roles` — 完整替换角色集合

守卫：`role.assign` + 角色差集边界。请求：`{"roles": string[], "lockVersion": int>=0, "reason"?: string}`。
成功 `200`：`data = {roles[], lock_version}`（实际角色与新版本）。
错误：`403 FORBIDDEN`（缺权限 / 越界 / 保护角色 / 试图手工授 STUDENT·VOLUNTEER）；`404 NOT_FOUND`（目标不可见）；`422 VALIDATION_ERROR`（未知角色 code）；`409 VERSION_CONFLICT`（版本不符）。
行为：撤销负责人角色时同事务清除其个人可选授权（不自动恢复）。请求模型刻意不含 password/status/permissions，防账号编辑旁路。

### 4.3 `GET /optional-permission-targets` — 可选权限目标选择器

守卫：`optional_permission.manage`。成功 `200`：`data = {items:[{id, display_name, status, permissions:[{code, enabled}], lock_version}], configurable_codes[]}`。仅返回持有 `STUDENT_AFFAIRS_MANAGER` 的账号；两项默认关闭。

### 4.4 `PUT /users/{user_id}/optional-permissions/{code}` — 逐人开关

守卫：`optional_permission.manage` + 两项许可清单。请求：`{"enabled": bool, "lockVersion": int>=0, "reason"?: string}`。`code ∈ {statistics.read, objection.initial_review}`。`report.read`/`report.generate` 属负责人默认权限。
成功 `200`：`data = {code, enabled, lock_version}`。
错误：`403 FORBIDDEN`（缺权限 / 自我提权）；`404 NOT_FOUND`；`422 VALIDATION_ERROR`（非两项 code / 目标非负责人）；`409 VERSION_CONFLICT`。
生效：下一次请求立即体现（不使用长期权限缓存）。

## 5. 端点明细（绑定码管理 / 换绑，P2）

统一守卫：`identity.binding.manage`。

### 5.1 `POST /students/{student_id}/binding-tokens` — 签发一次性绑定码

请求：`{"reason"?: string}`。
成功 `200`：`data = {token_id, student_id, plaintext_code, expires_at}`。`plaintext_code` **仅此响应回显一次**，库中只存 sha256 摘要；有效期由 `BINDING_TOKEN_VALID_MINUTES`（默认 60）控制。
错误：`403`（缺权限）；`404 NOT_FOUND`（学生不存在）。

### 5.2 `POST /binding-tokens/{token_id}/revoke` — 作废未使用绑定码

请求：`{"reason"?: string}`。
成功 `200`：`data = {token_id}`。
错误：`403`；`404 NOT_FOUND`；`409 STATE_CONFLICT`（码已核销，不可作废）。已作废重复调用幂等返回 `200`。

### 5.3 `POST /users/{user_id}/student-binding-reset` — 换绑 / 解绑（线下核验后）

请求：`{"new_student_no"?: string|null, "reason"?: string}`。`new_student_no` 为字符串则换绑到该学号；`null`/省略则解绑。
成功 `200`：`data = {user_id, student_id|null, revoked_sessions, lock_version}`。
行为：同事务锁定操作者与目标（按 ID 固定顺序），改绑保持/授予 STUDENT，解绑收回 STUDENT，并撤销目标全部有效会话（下一次请求需重新登录）。
错误：`403`；`404 NOT_FOUND`（学号不存在）；`409 STATE_CONFLICT`（该学生已被其他账号绑定，或账号已有受派/提交历史而试图清除或更换学生归属）。有查课历史时应使用微信重新绑定流程；尚未投入该业务的原管理纠错流程保留。

## 6. PRE_BINDING 受限会话语义（PERMISSIONS.md 1.6）

PRE_BINDING 是会话状态，不是角色：仅当账号 `student_id` 为空 **且** 无任何角色时成立。
- 放行白名单：`GET /me`、`POST /me/student-binding`、`POST /me/staff-binding`、`POST /auth/refresh`、`POST /auth/logout`（登录类不算业务白名单）。
- 教职工本人入口不使用学生守卫：`/me/inspection-records*` 与教工材料访问逐请求核对有效档案，
  因此已关联档案的受限会话可以读取本人范围；`require_binding_complete` 继续只保护学生本人接口。
- 刷新只能延续该受限态，不能因旧令牌曾含角色而获得管理入口。
- 功能权限守卫（`require_permission`）天然拦住受限用户的业务访问（其 `permissions` 为空）；`require_binding_complete` 为「依赖本人 student_id」的接口再加一道纵深。
- Web 管理员不受此态影响（持有角色）。

## 7. 错误码字典

| code | HTTP | 语义 |
|---|---|---|
| `VALIDATION_ERROR` | 422 | 输入/业务规则不满足（未知角色、非两项 code、码无效等） |
| `UNAUTHENTICATED` | 401 | 未登录、令牌/会话失效、凭证无效或重放 |
| `FORBIDDEN` | 403 | 缺功能权限、越权边界、自我提权、功能未开放 |
| `CSRF_FAILED` | 403 | Cookie 写接口跨站校验未通过 |
| `NOT_FOUND` | 404 | 资源不存在或对操作者不可见 |
| `STATE_CONFLICT` | 409 | 状态冲突（已绑定、码已用/过期、账号锁定 429 亦复用此码） |
| `VERSION_CONFLICT` | 409 | `lock_version` 乐观并发不符；异议终审改判时考勤版本 ≠ 发起版本亦返回此码（不覆盖他人新认定） |
| `DUPLICATE_ACTIVE_OBJECTION` | 409 | 同一考勤已存在未完成异议（`final_status=PENDING`），并发下锁考勤行串行化恰一成功（P6） |
| `OBJECTION_WINDOW_CLOSED` | 409 | 超过可配置异议窗口（`OBJECTION_WINDOW_DAYS`）再对考勤提异议（P6） |
| `FILE_EXPIRED` | 410 | 访问已清理（`PURGED`/`PURGE_PENDING`）或超保留期的材料（P5，技术方案 16.3） |
| `UPSTREAM_UNAVAILABLE` | 502 | 微信 code2session 超时/上游错误/响应异常（P2） |
| `INTERNAL_ERROR` | 500 | 兜底内部错误（不回显细节） |

## 8. 配置项（环境注入，P2 新增）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WECHAT_LOGIN_ENABLED` | `false` | 微信登录总开关；关闭时 `/auth/wechat/login` 返回 403 |
| `WECHAT_APPID` | — | 小程序 appid，身份唯一键之一；不入响应/日志 |
| `WECHAT_SECRET` | — | code2session 密钥；仅进程内使用，绝不外泄 |
| `WECHAT_CODE2SESSION_URL` | `https://api.weixin.qq.com/sns/jscode2session` | 出站换取地址 |
| `WECHAT_TIMEOUT_SECONDS` | `5.0` | 出站超时，避免抖动拖垮同步线程池 |
| `BINDING_TOKEN_VALID_MINUTES` | `60` | 一次性绑定码有效期 |
| `BINDING_TOKEN_MAX_FAILED` | `5` | 绑定码失败次数上限（预留） |
| `IMPORT_PREVIEW_TTL_MINUTES` | `30` | 导入预览批次有效期；超时确认置 EXPIRED 并返回 409 |
| `IMPORT_MAX_ROWS` | `5000` | 单文件解析行数上限，超限预览返回 422 |
| `OBJECTION_WINDOW_DAYS` | `7` | 学生对某条考勤可提异议的窗口天数（自考勤生成时刻起算）；`0` 表示不限窗口（部署未定异议期时的保守值）（P6） |
| `OBJECTION_MAX_FILES` | `5` | 单条异议可关联的证明材料数上限，超限创建返回 422（P6） |

## 9. 测试覆盖

真实 MySQL 集成测试（`backend/tests/integration/`）：
- `test_identity.py`：Web 登录/Cookie/CSRF/刷新轮换重放/登出/锁定/本人绑定一次性。
- `test_admin_rbac.py`：角色边界矩阵、可选权限清单、目标选择器、会话自洽、并发与审计回滚。
- `test_wechat_binding.py`：code2session 错误映射、首次登录建号与 PRE_BINDING、完整链路签发→绑定→自动授 STUDENT、同一码并发核销仅一人成功、作废与幂等、明文只回显一次且库中仅存摘要、换绑/解绑撤销旧会话、Web 管理员不受限、敏感字段不外泄。
- `test_migrations.py` / `test_seed.py`：迁移升级/回滚零漂移、单 head、种子矩阵幂等。
- `test_academic.py`：基础数据 CRUD 与错误码矩阵（学期/节次/校历/行政班/学生/课程/教学班/名单/课表/志愿者资格）、`FOR UPDATE` 真实并发（名单整体替换、志愿者资格核销恰一成功）、有效资格自动授 VOLUNTEER、审计。
- `test_importer.py`：三类导入（roster/timetable/volunteer）预览→确认两步、组合权限象限（execute/target-manage 缺一即 403）、作用域校验、周次解析（区间/单双周/越界）、错误阻断确认、引用在两步之间失效的原子回滚零副作用、过期/重复确认状态机、审计，以及"先导入资格后绑定"由 `bind_student` 反向补授 VOLUNTEER。
- `test_inspection_*.py`（P4/P5）：任务生成预览→确认、排班改派、调班申请、取消/名单改版/截止结算、志愿者提交、审核通过生成考勤、考勤读取范围/更正/应到人数调整；含 `threading.Barrier` 真实 MySQL 并发不变式（改派/核销/审核与取消互斥等恰一成功）。
- `test_file_upload.py` / `test_file_purge.py`（P5）：上传尺寸/类型/保留期固化、按资源归属访问与签名下载；到期清理状态机 `READY→PURGE_PENDING→PURGED`、底层删除失败留 `PURGE_PENDING` 不改判、重跑幂等、系统触发空操作者审计。
- `test_objection.py`（P6）：创建守卫/归属防枚举/诉求与当前一致 422/未完成异议去重 409/窗口超期 409/材料校验 422 与合法关联；读取 OWN vs MANAGE、负责人默认无路径 403 及授予初核后派生管理读取（关闭即失去）、详情越界 404；初核不改考勤、重复 409；终审驳回不改、通过改判并追加 `OBJECTION_FINAL` 版本、陈旧/他人新认定 `VERSION_CONFLICT`、重复 409、负责人无终审 403；同一考勤并发创建恰一成功；未完成异议暂停其材料到期清理、关闭后重新纳入并清理。

## 附录 A：P3 基础数据端点（`/api/v1/academic`）

守卫以功能权限为准（`require_permission`）；写操作均在服务端会话取操作者、同事务追加 `AuditLog`、`SELECT … FOR UPDATE` 串行化父资源。ID 一律字符串出入。

| 方法 路径 | 守卫 | 关键错误码 |
|---|---|---|
| `POST/PATCH /semesters[/{id}]`、`GET /semesters[/{id}]` | 写 `academic.manage` / 读 `academic.read` | `409`（code 重复、归档后写子资源）、`422`（结束早于开始、非法状态） |
| `PUT/GET/DELETE /semesters/{id}/period-definitions[/{no|id}]` | `academic.manage` / `academic.read` | `422`（`period_no` 越界 1..20、时刻逆序）；节次号以路径为权威，请求体可省略 |
| `POST/GET/DELETE /semesters/{id}/calendar-overrides[/{oid}]` | `academic.manage` / `academic.read` | `422`（补课缺来源星期）、`409`（同日期唯一） |
| `POST/PATCH/GET /administrative-classes[/{id}]` | `academic.manage` / `academic.read` | `409`（class_code 重复） |
| `POST/PATCH/GET /students[/{id}]`、`GET /students` | 写 `student.manage` / 读 `student.read` | `404`（行政班不存在）、`409`（学号重复）、`422`（非法状态） |
| `POST/PATCH/GET /courses[/{id}]` | `academic.manage` / `academic.read` | `409`（course_code 重复） |
| `POST/PATCH/GET /teaching-classes[/{id}]` | `academic.manage` / `academic.read` | `404`（课程不存在）、`409`（同学期同课同码重复、非活跃学期） |
| `GET/PUT /teaching-classes/{id}/students`（名单整体替换） | `student.read` / `student.manage` | `404`（含不存在学生）；PUT 语义为整体替换并去重 |
| `POST/PATCH/GET/DELETE /course-schedules[/{id}]` | `academic.manage` / `academic.read` | `422`（周次越界、结束早于开始）、`404`（教学班不存在、删除后读取） |
| `PUT/GET /volunteer-qualifications` | `volunteer.manage` / `volunteer.read` | `404`（学生不存在）；启用且学生已绑定则同事务自动授 VOLUNTEER，停用不回收 |

## 附录 B：P3 两步原子导入（`/api/v1`）

设计（技术方案 19、PERMISSIONS.md 12.5）：上传解析只暂存为 `import_batch`（规范行入 `payload_json`、统计入 `summary_json`、结构化问题入 `error_json`），确认阶段不再依赖原文件，仅重校验外部引用后整批单事务落库、**单次提交**。明文文件不入库。

组合权限：执行导入 = `import.execute` **且** 目标资源 `manage`。目标映射 roster→`student.manage`、timetable→`academic.manage`、volunteer→`volunteer.manage`。路由级 `ImportExecuteDep` 早拦（缺 execute → 403），服务事务内重读有效权限纵深复核（缺 target-manage → 403）。模板下载仅需 target-manage。

预览→确认状态机：

```
(上传) --POST /imports--> PREVIEW --POST /{id}/confirm--> CONFIRMED（终态，重复确认 409）
                              |                 ^-- 有 error 项 --> 422（拒绝确认）
                              |-- 过期 --> EXPIRED（确认时置位并 409）
```

| 方法 路径 | 守卫 | 说明 |
|---|---|---|
| `GET /import-templates/{target}` | target-manage | 返回 `{target, scope_fields, columns[], example_rows[]}`；`target∈{roster,timetable,volunteer}`，未知 422 |
| `POST /imports`（multipart） | import.execute（+服务纵深） | 表单：`file`(xlsx)、`target`、`semester_id?`、`teaching_class_id?`、`replace=false`。`replace` 默认 `false`，且**不会**整体覆盖：`roster`/`elective_course` 一律按补充/差异确认执行，未出现在文件中的现有成员保留；显式传 `replace=true` 时预览返回 `warnings[].code="roster_additive_only"` 说明实际语义，减少成员须走学生数据差异预览与学籍异动流程。成功 `200`：`data={id,target,status:"PREVIEW",semester_id,teaching_class_id,summary,errors[],warnings[],expires_at,can_confirm}`。非法/损坏 xlsx→422；行数超 `IMPORT_MAX_ROWS`→422；作用域缺失→422、作用域资源不存在→404；写审计 `import.batch.preview` |
| `GET /imports/{id}` | import.execute（+纵深） | 复用预览视图；批次不存在 404 |
| `GET /imports/{id}/errors` | import.execute（+纵深） | 返回 `{errors[], warnings[]}`（按 severity 拆分） |
| `POST /imports/{id}/confirm` | import.execute（+纵深） | 成功 `200`：`data={id,target,status:"CONFIRMED",summary}`（并入创建计数）。`409`（已确认 / 非 PREVIEW / 已过期）；`422`（存在 error 项、两步之间外部引用失效、周次超学期范围）。**任一失败整批回滚、业务零副作用**；成功写审计 `import.batch.confirm` |

`can_confirm` = `status==PREVIEW` 且无 error 级问题且未过期。确认对批次行 `SELECT … FOR UPDATE`，并锁定父作用域（roster 锁教学班→其学期须 ACTIVE；timetable/volunteer 锁学期须 ACTIVE，归档 409）。

各目标落库语义：roster 对目标教学班整体替换名单（学号→ID，缺任一即写前 422）；timetable 按课程代码 get-or-create 课程、按 `(学期,课程,教学班码)` get-or-create 教学班，再建课表与生效周（`1-16`、`单周/双周`、`1,3,5`、`第x-y周` 等组合，越界/倒置为 error）；volunteer 按 `(学期,学生)` upsert 资格行，`enabled` 且学生已绑定则即时补授 VOLUNTEER（幂等，`lock_version+=1`）。

"先导入资格后绑定"对称：导入阶段资格已启用但学生尚未绑定，则仅落资格行；待该生后续 `POST /me/student-binding` 绑定时，`bind_student` 检测到其持有 ACTIVE 学期下启用中的资格，反向补授 VOLUNTEER（与正向补授对称）。

## 附录 C：P4 查课任务生成与排班（`/api/v1`）

数据前缀 `/api/v1`，Inspection 路由独立挂载。令牌双路径与错误字典同第 2、7 节。ID 一律字符串出入；所有写操作在服务会话取操作者、事务内 `SELECT … FOR UPDATE` 串行化、末尾单次 `commit`、同事务追加 `AuditLog`。

### C.1 任务生成（预览 → 生成两步，`inspection.generate`）

体育课不作为被查课程：预览与生成跳过体育课；历史体育查课任务的人工/自动分配均拒绝，原因码为 `COURSE_NOT_INSPECTABLE`。体育课仍保存在学籍课表中，正常参与志愿者本人课程冲突判定。当前课程名称识别采用明确别名及序号变体（例如“体育板块”“大学体育1”），不以任意包含“体育”二字排除理论课程。

`POST /inspection-tasks/preview` 与 `POST /inspection-tasks/generate` 共用 `InspectionGenerateRequest`：`semester_id`、`inspection_type∈{COURSE,MORNING_STUDY,EVENING_STUDY}`、时段选择 `week_nos` **或** `date_from/date_to`（至少其一，越学期 422）、`COURSE` 需 `teaching_class_ids`、`MORNING_STUDY` / `EVENING_STUDY` 需 `administrative_class_ids`+`start_period`+`end_period`（`end>=start`）；`require_photo`、`reason`。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /inspection-tasks/preview` | `inspection.generate` | **只读**：返回 `{task_count,new_task_count,existing_task_count,date_count,student_total,within_limit,sample[]}`，`finally` 必 `rollback`，零写库。校历 `STOP` 日跳过、`MAKEUP` 取来源教学周及星期（`source_teaching_week` 可选，缺省兼容原实际周；`source_teaching_weekday` 必填） |
| `POST /inspection-tasks/generate` | `inspection.generate` | 事务内锁学期（`FOR UPDATE`）串行化同学期并发；按 `task_key` 幂等物化新任务 + 名单版本 `v1` + 成员快照 + 缺失查课日的 `SubmissionDeadlineDay/Version v1`（默认时刻本地转 naive-UTC），**整批单事务单次提交**；计划任务数超 `INSPECTION_GENERATE_MAX_TASKS` 在写入前 422。归档学期 409。审计 `inspection.task.generate` |

生成后读取：`GET /inspection-tasks`、`GET /inspection-tasks/{id}`、`GET /inspection-tasks/{id}/students`（名单，`inspection.roster.read`+可见性范围）、`GET /me/inspection-tasks`（强制本人受派范围）。数据范围：管理角色全部可见、志愿者仅本人受派（`resolve_scope`，管理范围优先）。

### C.2 排班与改派（Wave 3a，`assignment.manage`）

硬约束（技术方案 11.2，人工与自动同判、不允许旁路）：账号为启用志愿者、本学期资格有效、避开本人行政班被查名单（本班回避）、与本人课表时段不冲突、与本人其他受派任务时段不冲突（按完整起止节次重叠比较）。配置上限 `ASSIGNMENT_MAX_TASKS_PER_DAY` 和 `ASSIGNMENT_MAX_TASKS_PER_WEEK` 默认 `0`=不限，启用后均为不可绕过的硬约束；周上限按自然周一至周日累计有效受派，包含目标范围外的同周任务。学期公平负载不抵扣当前周名额。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `PUT /inspection-tasks/{task_id}/assignment` | `assignment.manage` | 人工分配/改派：`AssignmentSetRequest{volunteer_user_id,lock_version,reason?}`。锁层级先取 `(志愿者,日期)` 日期锚点（含换人时新旧双方），再锁任务行；已取消 409 `STATE_CONFLICT`、`lock_version` 不符 409 `VERSION_CONFLICT`、硬约束不过 422 `VALIDATION_ERROR`+`fieldErrors.reason_code`；受派 upsert（`assign_method=MANUAL`，改写则 `assignment.lock_version+=1`）、`task.lock_version+=1`；审计 `assignment.manual_set`（含 before/after 快照） |
| `POST /assignments/auto` | `assignment.manage` | 自动排班：`AutoAssignRequest{semester_id, task_ids \| inspection_date \| date_from/date_to, candidate_user_ids?, reason?}`（至少提供一项；同时提供时按 `task_ids` > `inspection_date` > `date_from/date_to` 选择，`date_to>=date_from`）。学期锁内使用新连接快照批量加载候选，按动态稀缺优先、公平容差、时间与楼簇增量成本生成计划，最多进行有界单步换位。Phase B 单事务批量加锁任务及当前资格输入，复核整份计划后一次 flush 落库（`assign_method=AUTO`）。全成全败，一任务一受派；审计 `assignment.auto_run`。返回 `{target_task_count,assigned_count,unassigned_count,assigned[],unassigned[{task_id,reason_code,message}]}` |

排班原因码分两条链：人工分配失败在 `fieldErrors.reason_code` 给出 `COURSE_NOT_INSPECTABLE`、`NOT_VOLUNTEER`、`NO_QUALIFICATION`、`OWN_CLASS_CONFLICT`、`SELF_CLASS_AVOID`、`TASK_TIME_CONFLICT`、`DAY_TASK_CAP`、`WEEK_CAP_EXCEEDED` 等当前检查首个命中原因；已取消任务在前置状态检查报 `409 STATE_CONFLICT`，不是常规候选拒绝项。自动排班 `unassigned[].reason_code` 在静态候选筛选阶段可给出 `COURSE_NOT_INSPECTABLE`、`NOT_VOLUNTEER`、`NO_QUALIFICATION`、`OWN_CLASS_CONFLICT`、`SELF_CLASS_AVOID`；候选存在但排不下时可给出 `TASK_TIME_CONFLICT`、`DAY_TASK_CAP`（规划器内部 `DAY_CAP_EXCEEDED` 在 API 转换）、`WEEK_CAP_EXCEEDED`。空候选池回退 `NO_QUALIFICATION`。同一任务可能有多个候选各自不同失败原因，返回值是确定性选出的一个解释，不能解读为全部候选的完整诊断。自动目标在查询时已过滤取消和已受派任务；提交前任务版本或候选输入变化时整批 `409 ASSIGNMENT_CONFLICT`，调用方须重试。

### C.3 并发不变式（技术方案 15）

全局锁层级：`(志愿者, 日期)` 锚点 → 任务 → …，一律升序取得。人工改派先锁新旧志愿者当日锚点、自动排班 Phase B 先锁全部计划锚点再按 id 升序锁任务，减少交叉等待；仍需处理数据库死锁导致的事务回滚。周上限启用时扩展锁定新旧志愿者整周的七个日期锚点，防止异日并发分别通过周名额检查。落库阶段的时段冲突重查用 `SELECT … FOR SHARE` 锁定读（`list_assignments_for_volunteer_on_date(for_update=True)`）——REPEATABLE READ 快照读会错过并发方刚提交的受派，锁定读绕过旧读视图，确保"同一志愿者同日重叠时段至多一条受派"。集成测试以独立连接 + `threading.Barrier` 双线程验证：恰好一条落库、另一方在锁内重验被拒（`VALIDATION_ERROR`/`VERSION_CONFLICT`/死锁回滚均可）。

### C.4 调班申请（Wave 3b，志愿者发起 / 管理人员处理）

语义边界：志愿者对**本人当前受派**发起调班诉求并留痕；`APPROVED/REJECTED` 仅迁移申请状态，**不隐式改派**——真正的换人仍走 `assignment.manage`（申请模型无替补志愿者字段，避免审核即换人的越权副作用）。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /assignment-change-requests` | `assignment.change_request` | `ChangeRequestCreateRequest{assignment_id,reason}`。"当前受派人"边界：受派不存在 404、非本人受派 403；任务已取消 409 `STATE_CONFLICT`；同受派已有 `PENDING` 再发起 409。成功建 `PENDING` 行，返回 `ChangeRequestResponse`（回填 `task_id`）。审计 `assignment.change_request.create` |
| `GET /me/assignment-change-requests` | `assignment.change_request` | 志愿者读取**本人**申请（无论角色强制 `request_user_id=本人`），分页 + 可选 `status` 过滤 |
| `GET /assignment-change-requests` | `assignment.change_review` | 管理视图读取**全部**申请，分页 + 可选 `status` 过滤 |
| `POST /assignment-change-requests/{request_id}/review` | `assignment.change_review` | `ChangeRequestReviewRequest{decision∈{APPROVED,REJECTED},comment?}`。`SELECT … FOR UPDATE` 锁申请行，仅 `PENDING` 可处理（否则 409）、申请不存在 404；置 `status/processed_by/processed_at/comment`。审计 `assignment.change_request.review`（before/after 状态） |

响应 `ChangeRequestResponse`：`{id,assignment_id,task_id,request_user_id,reason,status,processed_by,processed_at,comment,created_at,updated_at}`。

申请并发不变式：同一 `PENDING` 申请被两连接同时处理时，申请行 `FOR UPDATE` + "非 `PENDING` 即 409"保证**恰好一次转态**、另一方被拒；`approve` 后受派人 `volunteer_user_id` 保持不变（集成测试断言无隐式改派）。

### C.5 取消 / 名单改版 / 截止配置 / 截止时结算（Wave 3c）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /inspection-tasks/{task_id}/cancel` | `inspection.cancel` | `TaskCancelRequest{reason,lock_version}`。`SELECT … FOR UPDATE` 锁任务，不存在 404、已取消 409 `STATE_CONFLICT`、版本不符 409 `VERSION_CONFLICT`。**锁内先按当前适用旧截止版本幂等结算锁定既有逾期事实**，再置 `canceled_at/canceled_by/cancel_reason`、`lock_version++`。审计 `inspection.task.cancel`。返回任务 DTO（`status=已取消`） |
| `POST /inspection-tasks/{task_id}/roster-versions` | `inspection.roster.manage` | `RosterVersionCreateRequest{student_ids,reason,lock_version}`。锁任务，已取消 409、版本不符 409；学生含不存在/非在读 → 422 `fieldErrors{missing_student_ids,inactive_student_ids}`。生成 `roster_version+1` 新版本、冻结学生快照（学号/姓名/班名/年级），更正 `expected_count_current`、`lock_version++`。审计 `inspection.roster.revise` |
| `GET /inspection-tasks/{task_id}/roster-versions` | `inspection.roster.read` | 叠加任务可见性范围（志愿者仅本人受派，否则 404）；返回 `[{version_no,reason,created_by,member_count,created_at}]` |
| `GET /submission-deadlines/default` | `submission_deadline.read` | 只读反射部署配置的全局默认提交截止时刻（本地墙上时钟 `HH:MM`）+ `utc_offset_hours` + 说明。**改默认值属部署/配置动作、无写接口**，仅影响后续新建日截止，不追溯改写既有（技术方案 13.1、冻结纪律） |
| `GET /submission-deadlines/days?semester_id&date_from&date_to` | `submission_deadline.read` | 某学期日截止列表（可选日期范围），每项含 `task_count`（当日未取消任务数） |
| `GET /submission-deadlines/days/{inspection_date}?semester_id` | `submission_deadline.read` | 单日截止；无记录 404 |
| `GET /submission-deadlines/days/{inspection_date}/versions?semester_id` | `submission_deadline.read` | 该日截止版本历史（`version_no/deadline_at/changed_by/reason/created_at`） |
| `PUT /submission-deadlines/days/{inspection_date}?semester_id` | `submission_deadline.manage` | `DeadlineDayUpdateRequest{time(HH:MM),reason,lock_version(ge1)}`。锁日截止行，学期/记录不存在 404、版本不符 409。`time` 非法 → 422 `fieldErrors{time}`。**改期前先对该日未结算任务按旧截止版本幂等结算锁定既有事实**；若新截止早于当日最晚任务结束时刻 → 422 `fieldErrors{reason_code:DEADLINE_BEFORE_TASK_END,latest_task_end}`（无节次时刻定义时不阻断）。成功 `version++` 并写 `SubmissionDeadlineVersion` 历史。审计 `submission_deadline.day_update`（before/after 截止值以 ISO 字符串入库） |
| `POST /submission-deadlines/settle` | `submission_deadline.manage` | `DeadlineSettleRequest{semester_id,inspection_date?,task_ids?,limit(默认500,≤2000)}`。有界同步结算，不依赖页面访问。对未结算任务逐个 `FOR UPDATE` 锁行后幂等生成 `task_deadline_assessment`。返回 `{semester_id,considered,settled,already_settled,not_due,results[{task_id,result}]}`。审计 `submission_deadline.settle` |

截止时考核结果 `result ∈ {VALID_SUBMISSION, OVERDUE_UNEXECUTED, CANCELED}`：截止前已取消 → `CANCELED`；服务端时间严格超过适用截止（等值仍按时）且未取消 → `OVERDUE_UNEXECUTED`；未到期 → 不生成快照（`deadlineAssessment=null`）。`VALID_SUBMISSION` 留待 P5 提交域填充。任务视图回填 `deadline_at/deadline_version_id/deadline_assessment`。

任务当前态五态精判（`_derive_status`，技术方案 12）：`canceled_at → 已取消`；（P5）审核通过提交 → 已完成；（P5）待审核提交 → 待审核；`utcnow() > 当日 deadline_at → 已逾期`；否则 `待执行`。`已完成/待审核` 为提交域注释钩子。

结算/改期并发不变式：`settle` 与 `cancel`/`day_update` 均在任务行（或日截止行）`FOR UPDATE` 锁内先结算再变更，`_settle_assessment` 对已存在快照返回 `SKIP`（幂等）；两连接同时结算同一到期任务时，任务锁串行化 + 已有快照检查保证**恰好一行 `task_deadline_assessment`**（集成测试 `threading.Barrier` 双线程验证）。改晚截止不清除已结算的 `OVERDUE_UNEXECUTED`（截止时事实不可被普通业务改写）。

## 附录 D：P5 文件 / 提交 / 审核 / 考勤 / 到期清理（`/api/v1`）

数据前缀 `/api/v1`。令牌双路径与错误字典同第 2、7 节；ID 一律字符串出入。写操作事务内 `SELECT … FOR UPDATE` 串行化、末尾单次 `commit`、同事务追加 `AuditLog`（到期清理系统作业除外，见 D.5）。

### D.1 文件域（Wave 5b，技术方案 16）

文件无独立功能权限，访问按"业务资源归属"放行。`FILE_STORAGE_BACKEND=local` 使用本地目录，`object` 使用私有阿里云 OSS（受限服务端凭据或 ECS RAM 角色，需 OSS_BUCKET/OSS_REGION/HTTPS OSS_ENDPOINT）。上传仍经后端校验；默认访问返回应用 HMAC 下载地址，保持现有小程序兼容。Web 显式使用 `delivery=direct`：仅当 `OSS_WEB_DIRECT_ENABLED=true`、object 模式且为图片时，服务端完成相同授权/状态校验后签发公网 OSS V4 GET 链接，最长 300 秒，不超文件可访问期限；链接响应禁止缓存。其他情况仍返回原代理地址。对象键只存在于不可避免的短期签名 URL 路径，接口不额外提供裸键、长期地址或秘密访问密钥；签名 URL 在到期前可复用，不提供即时撤销保证。新上传/迁移固化正确 MIME，签名覆盖 `Cache-Control=private,no-store`，不覆盖该桶禁止的 Content-Type。旧文件须迁移核验后才切换，`OSS_LOCAL_MIRROR_ENABLED=true` 保留新文件本地镜像并在清理时同步删除。最新配置、验收与回退见 [OSS Web 直连实施](development/OSS_WEB_DIRECT_DOWNLOAD_20261022.md)；旧说明仅供历史参考。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /files` | 登录＋绑定完成（multipart） | 客户端允许 `category ∈ {SUBMISSION_PHOTO,OBJECTION_PROOF,TEMP}`，不接受导入/报表类别。PRE_BINDING 受限会话 403。字段为 `file`、`category`；服务端随机 `object_key`（绝不用原名作路径）、纯解析器读头校验尺寸/像素/类型，超限 422；默认单文件 10 MiB。同步路由线程池运行数据库与 OSS 操作，最多读限额＋1 字节。存储写成功才落 `READY` 行与 `file.upload` 审计，返回字符串 `id`；OSS 故障返回脱敏 503 `UPSTREAM_UNAVAILABLE`，不自动回退本地。`expires_at` 按类别保留期固化，`retention_policy_version` 记命中版本 |
| `GET /files/{file_id}/access` | 资源归属 | 可选 `delivery=proxy（默认）或 direct`；不接受其他值。不可见/不存在统一 404 防枚举；已清理/到期 → `FILE_EXPIRED`；未就绪（`UPLOADING/FAILED`）→ 409。返回 `url/method/expires_in/expires_at`，直连最长 300 秒；`Cache-Control: private, no-store`。未开启直连/本地模式/非图片/可用期不足2秒维持代理，避免SDK将1秒取整为0秒的无效签名 |
| `GET /files/{file_id}/download` | 仅签名 | **不再鉴权**（技术方案 16.2：不即时撤销已发链接），校验 HMAC 签名 + 过期时间戳 + 对象未清理；无签名验证器也拒绝。已清理/到期 `FILE_EXPIRED`，签名无效/当前秒≥过期时间 403；OSS 对象不存在 404，上游故障 503。返回 private/no-store、nosniff 和 UTF-8 文件名。Web/小程序重新打开材料应按有效期申请新链接，不能永久缓存 |

生产网关签名下载路由允许跨源图片加载及无凭据GET：输出 `Cross-Origin-Resource-Policy: cross-origin`、`Access-Control-Allow-Origin: *`、`Access-Control-Allow-Methods: GET, OPTIONS`；OPTIONS在Nginx返回204，不读取文件、不验证或核销签名。实际GET仍校验短时HMAC。无跨源Cookie/Authorization支持，HEAD未声明支持。下载的成功与错误响应均private/no-store。`/access`、上传及其他接口不使用这项例外；后端直连安全头仍是原基线。

`can_access`：上传者本人恒可访问自己的 `READY` 材料；已挂到提交的材料，持 `submission.review` 者经任意提交链接可得、仅持 `submission.read` 的志愿者只能经本人受派提交访问。

### D.2 查课提交（Wave 5c，`submission.create` / `submission.read`）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /inspection-tasks/{task_id}/submissions` | `submission.create` | `SubmissionCreateRequest{result∈{NORMAL,ABNORMAL},abnormal_items[{student_id,attendance_type,note?}],file_ids[]}`。守卫链：`_require` 锁操作者并重读权限 → PRE_BINDING 403 → 账号 `ACTIVE` → 持 `VOLUNTEER` 角色（仅持权限码无角色 403）→ 任务 `FOR UPDATE` 且未取消 → `assignment.volunteer_user_id==actor`（非本人受派 403）→ 本学期志愿者资格 → 无开放提交（否则 409 `STATE_CONFLICT`）→ 结论一致性（NORMAL 带明细 / ABNORMAL 无明细 → 422）→ 异常学生须在本任务当前名单版本且无重复（422 `fieldErrors{duplicate_student_ids,not_in_roster_student_ids}`）→ 附件校验（要求照片却空 / 超 `FILE_MAX_FILES_PER_SUBMISSION` / 非 `READY`/非本人/类别不符/已过期 → 422）。写前幂等结算锁"截止时"事实，冻结 `deadline_version_id`，`attempt_no=max+1`，插 `PENDING` 提交 + 异常明细 + 提交文件关联，`task.lock_version++`，审计 `submission.create` |
| `GET /me/submissions` | `submission.read` | 强制 `volunteer_user_id=本人`（`OWN_SUBMISSION` 范围），分页 |
| `GET /submissions/{id}` | `submission.read` | 读他人/越界提交统一 404 防枚举；本人可读 |
| `GET /management/submissions` | `submission.review` + 管理角色 | 审核工作台列表；按 `semester_id`、`date_from/date_to`、`task_id`、`review_status` 筛选，`submitted_at DESC,id DESC` 稳定分页；返回任务摘要、提交结论/异常、名单版本和照片文件 ID |
| `GET /management/submissions/{id}` | `submission.review` + 管理角色 | 管理详情；可读他人提交，返回任务快照、异常名单显示信息和照片文件 ID；不返回对象存储 key 或长期下载地址。照片仍经既有文件访问接口授权读取 |

不变式"至多一个待审核/审核通过"：存在 `PENDING|APPROVED` 提交时再次提交 → 409；真实并发恰好一成一拒（任务 `FOR UPDATE` 串行化）。

### D.3 提交即生效与本人纠错（`submission.create`）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /submissions/{submission_id}/revise` | `submission.create`（仅本人） | DEC-01 本人纠错：修改并重新提交。请求体同 `POST /inspection-tasks/{task_id}/submissions`。窗口起点是该任务**首次成功提交**时刻，改版不重置；时长取 `SUBMISSION_CORRECTION_WINDOW_MINUTES`（默认 120，`0` 关闭本人纠错），由服务端自身 UTC 时钟判定。锁序：先探提交（不加锁，缺失 404）→ `get_task_for_update`（任务先于提交）→ 再 `FOR UPDATE` 提交行及考勤行；保护事实用当前读复核。旧 attempt 置 `submission_state=SUPERSEDED` 并回填 `superseded_by_submission_id`，`review_status` **保持 `APPROVED` 不变**（考勤、名单、归档、统计等读取以它判断"已形成正式结论"）；新 attempt 为 `ACTIVE`，就地改写当前有效考勤并追加版本行，原提交、异常明细与照片全部保留。非本人提交 ID→404（不泄露存在性）；窗口已过 / 任务已取消 / 该提交已非 `ACTIVE`→409；该任务考勤已存在 `CORRECTION` 或 `OBJECTION_FINAL` 版本、或存在任何已发起异议（含未结案、终审驳回、维持原认定的通过）→409，本人不得覆盖管理员认定。旧提交失效、新提交、替代指针、考勤版本和审计在同一事务单次提交；任何校验或写入失败完整回滚。返回新 `SubmissionResponse`；审计 `submission.revise` 与 `submission.create` 各一条 |
| `POST /submissions/{submission_id}/withdraw` | `submission.create`（仅本人） | DEC-01 本人撤回：请求体 `{reason?(≤512)}`。资格判定与 `/revise` 完全同一条（同一锁序、同一窗口、同一"管理员已处理即不得覆盖"闸门）。提交置 `submission_state=WITHDRAWN` 并写 `withdrawn_at`/`withdraw_reason`，`review_status` **保持 `APPROVED` 不变**；该任务当前有效考勤整体转 `effect_state=WITHDRAWN`、`current_version++`，并各追加一条 `source_type=WITHDRAWAL` 版本行。**行不删除**（`attendance_record_version` 是不可变历史，`objection.attendance_record_id` 为 ON DELETE CASCADE），原始提交、异常明细与照片继续可读。撤回不擦除截止时事实：`TaskDeadlineAssessment` 原样保留。撤回后该任务回到"尚无有效结论"——`map_submission_flags_by_task_ids` 与 `has_approved_submission` 转 `False`，取消任务的闸门随之重新打开，本人可在窗口内通过普通提交入口重新提交；已有提交历史时该入口同样检查首次提交窗口与管理员/异议保护，窗口关闭或配置为 0 返回 409，首次逾期补交仍保留（同一结论也要重新生效，考勤行按 `unique(task_id, student_id)` 复用，不新插）。返回 `SubmissionResponse`；审计 `submission.withdraw`；`SourceRevisionService` 修订号递增，周报下次计算不再计入该结论 |

管理读取与本人读取保持两条独立路径。**查课提交没有人工审核闸口**：`45e850b` 起志愿者提交即 `APPROVED` 并同事务生成正式考勤，`POST /submissions/{id}/review` 与 `POST /management/submissions/batch-review` 已于 2026-10-22 删除（生产库当时 3 条提交全为 `APPROVED`，无历史 `PENDING` 遗留）。`submission.review` 权限保留，但现在只用于管理读取与提交材料可见性（`file/service.py`），不再对应任何写操作；`DEFAULT_ROLE_PERMISSIONS["STUDENT_AFFAIRS_MANAGER"]` 仍含该权限，属未裁定项。

考勤事实唯一约束 `unique(task_id, student_id)`；提交与取消互斥（都锁任务，恰一成功，绝不"既取消又生成考勤"，集成测试 `threading.Barrier` 断言 `canceled XOR has_attendance`）。存在**当前有效** `APPROVED` 提交（考勤已成立）后取消任务 → 409 `STATE_CONFLICT`（技术方案 51）；本人撤回使该 `APPROVED` 不再"当前有效"，取消闸门按 `submission_state=ACTIVE` 判定而重新打开，历史提交与考勤版本仍保留。

### D.4 考勤读取 / 更正 / 应到人数调整（Wave 5d）

数据可见性（PERMISSIONS.md 6.3）：`attendance.read` 全五角色持有，但 **SA/TA/SAM=全院 `MANAGE` 范围、VOLUNTEER+STUDENT=仅本人 `SELF_STUDENT`**。

在此之上有第二条独立轴：志愿者撤回后，该任务的考勤行转 `effect_state=WITHDRAWN` 并对**全部 ORM 读取默认隐身**（`attendance/effect_scope.py` 的 Session 监听器给每条查询加谓词，覆盖实体查询、只选列、聚合、join 进其他实体、IN 子查询、`aliased()` 与 `session.get()`）。因此 `GET /attendance*`、`GET /me/attendance`、统计与报表、异议可申诉判定、任务取消/删除守卫看到的都是"没有这条结论"，而不是"有一条已撤回的记录"；管理更正与学生对已撤回结论提异议都会得 404。显式放行（`see_withdrawn()`）只用在历史可达、证据鉴权与级联清理路径：撤回后本人仍能读自己那份现场照片，已撤回行仍阻止学期归档、任务物理删除、换组、换地点与学生物理删除。原生 SQL 不经该监听器，新增原生读取需自带 `effect_state='EFFECTIVE'`。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `GET /me/attendance` | `attendance.read` | 强制 `student_id=本人`；无绑定学生 403 |
| `GET /attendance` | `attendance.read` | 仅 `MANAGE` 范围可列（非管理范围 403）；分页 + `task_id/semester_id/effective_type` 过滤 |
| `GET /attendance/{record_id}` | `attendance.read` | 越界（非管理读他人、本人无该记录）统一 404 防枚举 |
| `GET /attendance/{record_id}/versions` | `attendance.read` | 同读取范围门禁，返回不可变版本历史 |
| `POST /attendance/{record_id}/corrections` | `attendance.correct` | `AttendanceCorrectionRequest{attendance_type,reason(1–512),current_version(ge1)}`。`AttendanceRecord` 行 `FOR UPDATE`，`current_version` 不符 → 409 `VERSION_CONFLICT`；改 `effective_type` + `current_version+=1`，**追加** `AttendanceRecordVersion(source=CORRECTION,source_id=record.id,changed_by=actor)`（不可变多态来源）。审计 `attendance.correct` |
| `PATCH /inspection-tasks/{task_id}/expected-count` | `attendance.expected_count_adjust` | `ExpectedCountUpdateRequest{expected_count_current(ge0),reason(1–512),lock_version(ge0)}`。锁任务，已取消 409、版本不符 409 `VERSION_CONFLICT`；`expected_count_current < 该任务非 NORMAL 考勤数` → 422 `fieldErrors{expected_count_current,abnormal_count}`。仅改 `expected_count_current`（`expected_count_snapshot` 冻结不动）、`lock_version++`；审计 `attendance.expected_count_adjust`（before/after 人数） |

`AttendanceRecord` 仅 `CreateTimeMixin`（记录无 `updated_at`，更正以版本行追加留痕）；`AttendanceRecordVersion` 不可变多态来源 `source_type ∈ {SUBMISSION,CORRECTION,OBJECTION_FINAL}`、`source_id` 无外键。响应不含 `updated_at`。

### D.5 到期材料清理（Wave 5e，部署定时脚本）

**不在 API 进程内起独立定时器**（技术方案 66）。清理由部署侧定时任务（cron / 任务计划）执行 `deploy/scripts/cleanup_expired_files.py`，复用 `FileService.purge_expired_files`，逐文件独立事务提交、可重跑幂等：

状态机（技术方案 16.1/16.3）：到期 `READY` → 先落库 `PURGE_PENDING`（持久化清理意图，崩溃可恢复）→ 删底层对象，成功才置 `PURGED` 记 `purged_at`；底层删除失败**保留 `PURGE_PENDING`** 待下次运行、绝不改判为已清理；对象已缺失视作清理完成。访问侧已 `PURGED`/`PURGE_PENDING`/已过期文件一律 `FILE_EXPIRED`。审计 `file.purge` 由**系统触发**（`actor_user_id=NULL`，`reason=retention_expired`，before/after 记状态）。已 `PURGED` 者不再入选候选，重复运行无副作用。`expires_at`/`retention_policy_version` 落库后不随配置改动无审计地缩短旧材料期限。

## 附录 E：P6 异议域（`/api/v1`）

数据前缀 `/api/v1`。令牌双路径与错误字典同第 2、7 节；ID 一律字符串出入。写操作事务内 `SELECT … FOR UPDATE` 串行化、末尾单次 `commit`、同事务追加 `AuditLog`。全局锁层级（技术方案 15）：考勤 → 异议——创建**先锁考勤行**再在其保护下查重与落异议；终审**先锁考勤、再锁异议**（`populate_existing` 重读）；初核不改考勤故仅锁异议行（对缺席层跳过）。

**读取路径的特殊性（PERMISSIONS.md 7.6 / 8.2 / 8.3）**：异议"管理读取"并非靠 `objection.read`，而是路由用 `require_any_permission(objection.read | objection.initial_review | objection.final_review)` 早拦后，由 Service 依有效权限解析范围——持 `initial_review` 或 `final_review` 之一 = `MANAGE`（全学院）；仅持 `objection.read` 且能解析出有效 `student_id` = `OWN`（只见本人）；二者皆无或 `read` 却无学生绑定 = `NONE`。学生工作负责人默认**不持** `objection.read`（矩阵"条件派生"），仅当被授予可选项 `objection.initial_review` 后才派生出 `MANAGE` 读取来源，关闭初核即失去（`attendance.read` 不提供替代证明读取）。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /attendance/{record_id}/objections` | `objection.create` | `ObjectionCreateRequest{desired_type∈{NORMAL,LEAVE,LATE,ABSENT},reason(1–512),file_ids[](≤50)}`。守卫链：`_require` 锁操作者并重读权限 → 解析本人 `student_id`（无绑定 403）→ `AttendanceRecord` 行 `FOR UPDATE`（他人生成/不存在统一 404 防枚举）→ 窗口校验（`utcnow() > created_at + OBJECTION_WINDOW_DAYS` → 409 `OBJECTION_WINDOW_CLOSED`，`0`=不限）→ 诉求 == `effective_type` → 422 → 同考勤有 `final_status=PENDING` 未完成异议 → 409 `DUPLICATE_ACTIVE_OBJECTION`。材料校验：去重后须 ≤ `OBJECTION_MAX_FILES`（超 422），逐个 `get_for_update` 核验仍 `READY`、类别 `OBJECTION_PROOF`、`uploader==本人`、未过期（任一不符 422，与到期清理同锁协议串行化）。落 `Objection`（记 `base_attendance_version=record.current_version`）+ `ObjectionFile` 关联，审计 `objection.create` |
| `GET /objections` | `objection.read \| initial_review \| final_review`（任一） | Service 解析范围：`MANAGE` 全量 / `OWN` 加 `student_id=本人` 谓词 / `NONE` 403。分页 + `attendance_record_id/final_status/initial_status` 过滤 |
| `GET /objections/{objection_id}` | 同上（任一） | 越界/不可见与不存在统一 404 防枚举；`MANAGE` 可读任意、`OWN` 仅本人 |
| `POST /objections/{objection_id}/initial-review` | `objection.initial_review` | `ObjectionInitialReviewRequest{decision∈{PASSED,REJECTED},comment?(≤512)}`。锁异议行，`initial_status≠PENDING` → 409 `STATE_CONFLICT`；置状态/处理人/时刻/意见，**绝不改考勤**，审计 `objection.initial_review` |
| `POST /objections/{objection_id}/final-review` | `objection.final_review` | `ObjectionFinalReviewRequest{decision∈{APPROVED,REJECTED},final_type?(∈全集),comment?,current_version(ge1)}`。先探异议（不加锁，缺失 404）→ `AttendanceRecord` `FOR UPDATE` → 异议 `FOR UPDATE` 重读；`final_status≠PENDING` → 409。`REJECTED` 不改考勤。`APPROVED` 须给 `final_type`（缺 422）；`final_type≠effective_type` 即"更正"，须另持 `attendance.correct`（否则 403），且 `current_version==record.current_version`（不符 409 `VERSION_CONFLICT`，不覆盖他人新认定），通过则同事务改 `effective_type`、**以当前版本起版** `current_version=record.current_version+1`、**追加** `AttendanceRecordVersion(source=OBJECTION_FINAL,source_id=objection.id)`；判定与当前认定相同时不改考勤、不校验版本。审计 `objection.final_review`（before/after 含考勤，after 记 `attendance_changed_since_filing` 与 `base_attendance_version`）|

状态机：`initial_status∈{PENDING,PASSED,REJECTED}`、`final_status∈{PENDING,APPROVED,REJECTED}`（`PENDING` 即"未完成异议"）。`Objection` 用 `TimestampMixin`（可变流转，有 `updated_at`）；`attendance_record_id` 随考勤 `CASCADE`，`student_id` 对主数据 `RESTRICT`。`ObjectionFile` 联合主键、`file_id` 对文件 `RESTRICT`。

**清理耦合（技术方案 16.3、538/713）**：被**未完成异议**（`final_status=PENDING`）引用的材料暂停到期清理——`FileRepository.list_purge_candidates` 以 `NOT IN` 未完成异议文件子查询排除之；异议关闭后自然重新纳入候选。新建异议关联材料用与清理相同的**文件行 `FOR UPDATE` + `READY` 核验**串行化，避免"校验后新增引用而误删"。

**周报考勤源修订**：`report_source_revision` 对影响考勤汇总的写路径（审核生成考勤、应到人数调整、人工更正、异议终审有效改判）在同一业务事务内递增。任务生成/取消、改期与逾期结算不改变周报考勤汇总，不作为修订触发条件。详见附录 F。

## 附录 F：P7 统计与版本化周报域（`/api/v1`）

数据前缀 `/api/v1`。令牌双路径与错误字典同第 2、7 节；ID 一律字符串出入。`statistics.read` 为负责人可选项；`report.read` 与 `report.generate` 为负责人默认权限，超管和教师亦具备。`statistics.read` 不由周报权限派生。统计和周报沿用管理范围门禁；学院行级隔离 V1.0 尚未落地账号↔学院归属，当前按单学院管理范围处理。

无 worker/队列/Redis/MQ/集群（技术方案 §66、DEVELOPMENT_PLAN 66）——周报为**受限同步执行**，规模超限在写产物前拒绝。

### F.1 统计只读（W7a）

| 端点 | 守卫 | 说明 |
|---|---|---|
| `GET /statistics/attendance` | `statistics.read` | 入参 `semester_id(ge1)` 必填、`week_no(ge1)` 或 `date_from/date_to` 二选一（互斥必居其一，非法经路由捕获转 422）、`include_tasks?`。返回聚合：仅计「有 APPROVED 提交且未取消」任务的当前有效考勤；待审核异常不计正式缺勤；分母≤0 → 该维度 `rate=null` 且 `statistics_available=false`（不冒充 0%/100%）；先累加分子分母再相除，非班级百分比平均；班级维度按 `TaskRosterMember.class_name_snapshot` 分组，`expected_count_current≠snapshot` 且无分班明细推导则该任务 `class_ratio_available=false` 不均摊 |
| `GET /statistics/incomplete-tasks` | `statistics.read` | 分页未完成清单，`semester_id` + 周次/日期窗 + `only_current_incomplete?`。**两指标分别命名输出、不混名**：「当前未完成」= 未取消且无 APPROVED 提交（当前状态派生）；「截止时未完成」= `TaskDeadlineAssessment.result==OVERDUE_UNEXECUTED`（快照事实）；CANCELED 不纳入未完成 |

范围/门禁：路由 `require_permission(statistics.read)`；Service `_lock_actor` + 事务内重读有效权限纵深复核（复用 attendance/objection 既有 `_require` 模式）。聚合口径与 W7c 周报同源单一真相（`report/aggregation.py`）。

### F.2 版本化周报（W7c）

表：`report`（逻辑周报主记录，联合唯一 `(semester_id,week_no,scope)`；数据库为后续预留 `CLASS` 枚举，但 V1 API 仅允许 `COLLEGE`；`latest_version_no`、`latest_updated_at`）；`report_version`（版本化不可覆盖，联合唯一 `(report_id,version_no)`，`source_revision`/`rule_version`/`template_version`、`snapshot_file_id`/`excel_file_id` 对 `file_object` SET NULL、`status∈{GENERATING,PUBLISHED,FAILED}`、`attempt_token`、`generated_by` 对 `user_account` SET NULL）。迁移单头 `2658519d48fa`（down=`9443750a1ff5`），零漂移可逆。

| 端点 | 守卫 | 说明 |
|---|---|---|
| `POST /reports/weekly/versions` | `report.generate` | `WeeklyVersionCreateRequest{semester_id(ge1),week_no(ge1),scope="COLLEGE",reason?(≤512)}`；`CLASS` 请求在进入版本分配前返回 422。**三阶段有界同步**：①短事务对 `report` 行 `SELECT … FOR UPDATE` 串行化 `version_no` 分配 + SAVEPOINT 保护 get-or-create + 登记 `GENERATING` 行（`attempt_token`）；陈旧 `GENERATING` 可带 token 条件接管，否则冲突。②一致性只读快照，仅汇总已审核通过任务的当前有效考勤；命中任务数超 `REPORT_GENERATE_MAX_TASKS` → 422，已有 `GENERATING` 版本转 `FAILED`。③事务外产出 JSON 明细快照 + Excel（考勤总览、班级考勤及考勤明细，不含任务总数、未完成或逾期统计）。④独立短事务条件发布，登记两个 `REPORT_FILE`，晚到重复回滚并安全删孤儿。审计 `report.version.start` / `report.version.publish` |
| `GET /reports/{report_id}/versions` | `report.read` | `report_id(Path ge1)`。返回按版本号降序排列的逻辑周报全部版本；各 `items[].behind_source` 按该版本源修订号比较，顶层 `latest_behind_source` 取降序列表中第一个 `PUBLISHED` 版本比较（跳过更新的 `GENERATING`/`FAILED`）；`rule_outdated`、`template_outdated` 按各版本快照值与当前 Settings 比较。`latest_version_no` 是最新分配号，可能属于失败版本；`latest_updated_at` 是最近发布时刻。另含 `current_source_revision/rule/template` |
| `GET /report-versions/{version_id}/download` | `report.read` | `version_id(Path ge1)`、`kind∈{EXCEL,SNAPSHOT}="EXCEL"`。仅 `PUBLISHED` 可下载（否则 409），底层已清理/超期 `FILE_EXPIRED`（410）。返回附件流（`Content-Disposition`），非统一 `success` 包裹 |

**源修订范围**：审核通过生成考勤、应到人数调整、考勤更正、异议终审有效改判，在业务事务内推进所属学期周次的源修订号。任务新建/取消、逾期结算及仅改截止时刻本身不改变周报考勤汇总，不推进周报源修订。`behind_source` 比较当前源与版本快照；旧周报版本不会被覆盖。固定格式 Word 文档属于后续交付，当前下载格式为 Excel 或 JSON 快照。

**清理关系（W7d 确认）**：`REPORT_FILE` 走自有归档期限（默认 365 天，非临时件短周期），未到期不被清理误删、确到期者按 `READY→PURGE_PENDING→PURGED` 同一状态机清理；归档期过后对应 `report_version` 下载返回 `FILE_EXPIRED`（410）。列表中的 `snapshot_available`/`excel_available` 仅检查该版本为 `PUBLISHED` 且记录了相应 `file_id`，不查询文件实时状态或有效期；即使为 true，仍可能已经过期或清理，应以实际下载响应为准。

### F.3 运行交付（W7d）

到期清理部署脚本 `deploy/scripts/cleanup_expired_files.py`（复用 `FileService.purge_expired_files`，cron/任务计划触发、逐文件独立事务、可重跑幂等，见 D.5）已确认对 `REPORT_FILE` 类别生效。备份恢复与压测验收见运维手册 `docs/RUNBOOK_BACKUP_RESTORE.md`、`docs/RUNBOOK_LOADTEST_ACCEPTANCE.md`（规模/阈值/RPO/RTO 均为待学院确认的占位，未给数字不臆造）。

### F.4 相关配置（全部走 Settings/env，冻结纪律）

| env | 默认 | 含义 |
|---|---|---|
| `REPORT_RULE_VERSION` / `REPORT_TEMPLATE_VERSION` | 1 / 1 | 公式/模板版本，生成时盖章入版本行，变更驱动陈旧提示 |
| `REPORT_GENERATE_MAX_TASKS` | 5000 | 单次生成聚合任务上限，超限写产物前 422 |
| `REPORT_GENERATE_TAKEOVER_STALE_SECONDS` | 600 | `GENERATING` 可接管陈旧阈值 |
| `FILE_RETENTION_REPORT_FILE_DAYS` | 365 | 报表产物独立归档期限 |
| `OBJECTION_WINDOW_DAYS` / `OBJECTION_MAX_FILES` | 7 / 5 | （P6）异议窗口与附件上限 |


## 2026-09-29 补充：人工原因统一选填

取消任务、名单改版、日截止调整、应到人数调整、调班申请、考勤更正和学生异议的 `reason` 均可省略或传空字符串，最长 512 字符。上述原必填字段省略时规范化为空字符串，兼容现有非空数据库列；客户端不要传 `null`。其余原本可选的原因字段保持原契约。操作者、时间、版本和变更记录仍由服务端记录；业务必填项、权限检查及乐观锁不放宽。自动排班失败原因码属于系统诊断，不受人工原因选填规则影响。

## 2026-09-29 补充：管理基础接口（本地代码已落地，待综合验收）

- 负责人默认具备 `academic.read`、`volunteer.read`、`import.execute`、`course_schedule.import/export`、`inspection.generate/cancel`、`assignment.manage`、`report.read/generate`；个人可选项仅 `statistics.read` 与 `objection.initial_review`。授予 `STUDENT_AFFAIRS_MANAGER` 必须有有效学生绑定；解绑/停用学生撤销该身份、个人授权与旧会话。教师不能创建或停用教师账号。
- `GET /academic/teaching-classes` 新增 `administrative_class_id` 筛选。`GET /inspection-course-occurrences` 以 `semester_id,date_from,date_to,teaching_class_ids,page,page_size` 查询，返回候选 `items`、`total`、全范围 `selection_revision` 和 `selection_scope`。精确模式的 preview/generate 请求须原样回传 `selection_scope`、`selection_revision`，并传最多 500 个 `occurrences[{course_schedule_id,inspection_date}]`；旧周次/日期范围模式与精确模式互斥。服务端重建并验证课次，范围过期返回 409 `SELECTION_STALE`。generate 结果增加 `tasks[{task_id,created,status,assignment_id}]` 和 `assignable_task_ids`；自动排班只传本次可排 ID。
- `POST /inspection-tasks/{id}/restore` 用 `inspection.generate` 守卫和 `lock_version`；仅未开始、无提交/考勤/截止考核、课表与名单快照仍兼容的取消任务可恢复。恢复后为未分配，旧 assignment 标记 `revoked_at` 留历史。学生停用也只撤销未来尚未执行且无事实的受派，保留历史与截止事实。
- `GET/POST /teacher-accounts`、`PATCH /teacher-accounts/{id}`、`POST /teacher-accounts/{id}/password-reset` 仅超管；创建同时赋教师角色，停用和重置口令撤销会话，不回显口令。`POST /me/password-change` 适用于本人密码账号。写入遵守版本冲突与最后超管保护。
- `GET /course-schedules/export` 需要 `course_schedule.export`，按学期及可选教学班导出最多 10000 行 XLSX；列为教学班、课程、教师、周次、星期、开始节次、结束节次、教室。当前模型没有任课教师字段，教师列为空；文本列强制字符串以避免公式执行。
- `GET /reports` 需要 `report.read`，仅列学院记录，支持学期/周次过滤与分页；`latest_version_id/no/created_at` 取最新已发布版本，`source_changed` 比较当前考勤源修订。周报内容只含考勤汇总，`CLASS` 请求 422，下载格式按该版本实际产物及当前 API schema 选择。
- `GET /audit-logs` 和详情仅 `audit.read`；列表时间窗最多 31 天、每页最多 100 条，按操作者、动作和资源筛选；详情 before/after 使用字段白名单，不返回密码、令牌或证明正文。列表每行返回 `actor_name` 与 `actor_username`，账号已注销时为 `null` 而不是让整页失败；详情另返回 `reason`。`business_scoped=true` 时全局入口只允许 `SUPER_ADMIN`，其他账号必须走 `GET /colleges/{cid}/audit-logs`，后者的范围由固定学院身份或有效 `ScopedGrant` 决定，不读全局权限。管理端入口是 `/dashboard/audit`「操作日志」，按 `audit.read` 显示。这些响应是 `dict[str, object]` 信封，`docs/openapi.json` 只能记为 `additionalProperties: true`，字段含义以本条为准。


## 学院配置底座契约（2026-10-13）

默认关闭，迁移 `f26a1013c001` 后可在开发环境启用 `CAMPUS_CONFIGURATION_ENABLED=true`。学院配置说明见 [配置底座](archive/2026-10-15/design/CAMPUS_CONFIGURATION_GUIDE.md)，阶段边界见 [实施计划](archive/2026-10-15/plans/CAMPUS_IMPLEMENTATION_PLAN.md)。

- 新工作区返回学院 ID、有效配置能力、授权/配置修订与 `business_ready=false`；该字段明确旧业务尚未接入。
- 学校、学院和院级授权仅有效超管可维护；其他账号只按同学院、同动作、有效期完整子句访问，负责人不自动得权。看不到学院/资源返回 404；已有可见范围但缺动作返回 403。
- 资源 ID 为字符串；路径仅接受合法正 BIGINT。类型和组的 PATCH/DELETE、组配置发布及授权撤销携带 `lock_version`，旧版本 409；未知所有权字段 422。
- 类型稳定 code 服务端生成，改名不改 ID/code；院内规范化名称唯一，有历史配置引用不能硬删除。组默认草稿，发布不会自动启用。
- 范围发布必填非空 `course_type_ids`，`class_mode` 支持 `ALL_AUTHORIZED` 或 `SPECIFIC`（指定本院班级）；冲突规则独立保存，另一受派冲突首期只允许 BLOCK。范围与规则一次发布，版本历史不覆盖；JSON 原样再发布可用，但指定班级通过 class_ids 提供，支援通过独立授权接口提供。
- 授权起止 HTTP 时间必须带时区，内部统一 UTC；有效动作白名单为 `academic.course_type.read/manage`、`volunteer.group.read/manage`、`volunteer.member.manage`（接入中）、`volunteer.config.publish`。动作应使用完整 code，read/manage 的范围不能跨院组合。
- 成功继续返回 `{data, requestId}`，业务错误继续采用统一 envelope；未迁移/未启用时新接口 503。新组和类型不参与旧抽查/排班，不能据配置保存成功认定正式业务验收通过。

### 存量学院归属核对（扩展阶段）

仅服务端复核后的有效超管可使用，受同一配置开关控制。

| 接口 | 用途 |
| --- | --- |
| `GET /campus/ownership/unresolved/{kind}` | `administrative_class/teaching_class/import_batch/report` 待确认资源；`after_id` 游标，`limit` 1—200 |
| `POST /campus/ownership/preview` | `mappings` 按资源类型提供 `{资源ID字符串: 学院ID字符串}`，最多 2000 项；返回修订、关联变化、冲突及未确定数量 |
| `POST /campus/ownership/apply` | 提交相同映射和预览 `revision`；数据/关联/学院变化返回 409，冲突整批拒绝，写入和审计同事务 |

这些接口使用 `/api/v1` 前缀。已确定归属不能通过回填迁院。课表、任务沿完整父链传播，学院文本不自动映射；部分父链未知不当作完整证据。查询或写入后 `business_ready` 仍为 false，不能由回填成功认定旧业务访问隔离完成。

## 2026-10-14 实际时间、组范围与报表边界

- `CAMPUS_SCHEDULING_ENABLED` 默认 false；实际作息和组业务 HTTP 入口还要求配置/基础数据/正式业务模式开启。本轮不能据新入口通过开启多学院生产。
- 作息发布请求为 effective_from、periods、calendar、confirm_existing_tasks；先预览，发布另带 revision。节次 1—60、本地分钟精度、同日不重叠；校历日期及来源周次须在学期内。已有未来任务保持原快照，需要明确确认；版本不可覆盖。
- `class_mode` 支持 ALL_AUTHORIZED / SPECIFIC，SPECIFIC 必须非空 class_ids，均为本院行政班字符串 ID；范围抽查先按同院有效类型/班级/正式名单筛选，缺额 409，不跨类型补齐。抽查生成与指派两阶段分离。
- group 配置支持 teaching_class_overrides，优先于 type_overrides 和 default_effect。WARN 反馈和部分跨院例外尚待接入，不将未完成的 UI/反馈表述为已验收。
- 成员有效期左闭右开，允许加入多组；跨院先由超管授权完整覆盖成员有效期的支援。撤销请求增加 confirm_future_assignments；默认遇到未来受派拒绝，确认后返回 retained_future_task_ids，保留任务/受派历史并需管理端处理改派。
- 任务响应增加可空 college_id、group_id、group_config_version_id、课程类型 ID/名称快照、组名快照、activity_start_at/activity_end_at、time_snapshot。所有新增 ID 为字符串，实际 datetime 返回带 Z 的 UTC；旧历史无可靠时刻时为 null，不重新推断。
- 启用排班模式后 PATCH 任务必须提供 lock_version；陈旧版本 409。未受派任务改节次同步冻结新实际时间；已受派任务不可直接改时段，需要取消/重新生成及排班。已有正式考勤仍不可修改。
- 报表唯一键含学院或学校旧范围标识；源修订按学院独立。旧版本 college_id_snapshot 为空时，即使主记录回填学院也不可向学院管理员暴露。下载及文件签发通过同院、已发布且内容归属已验证的版本关联核验。
- 正式教务发布使用学院校历/作息，必要时同一来源课表拆成多个时间段，occurrence_dates 为实际执行日期。本人课表初始化保留这些日期；正式更新不修改已有个人副本。

学院校历未覆盖的日期继承学校校历，发布学院作息不隐式取消全校停课日。


### 2026-10-15 待发布：资源范围授权

- `POST /api/v1/colleges/{cid}/grants/preview`：超管预览授权，返回`revision`与服务端冻结的`resource_scope`。
- `POST /api/v1/colleges/{cid}/grants`：新增可选`resource_scope={kind,ids}`，kind为`COLLEGE|GROUPS|COURSE_TYPES|TEACHING_CLASSES`；受限范围必须非空。受限授权必传预览返回的`preview_revision`，过期返回409。旧院级请求兼容。
- `GET /api/v1/colleges/{cid}/groups/{gid}/references`：仅按当前有效的组读取权限提供类型、行政班、教学班基础元数据，未授权组404。
- 受限授权暂不支持教学数据、导入、导出、审计、统计和报表等全院动作；非法组合422，绝不降级成全院权限。
- 智能抽查建议请求在组织模式需`execution_group_id`；建议与正式生成使用相同执行组范围。

本节是当前开发分支契约，尚未生产启用；不会要求微信小程序增加学院配置页面。


### 2026-10-15 待发布：配置影响处置

`GET /api/v1/colleges/{cid}/configuration-impacts?page=1&page_size=50&status=OPEN`返回范围内持久影响项及当前任务/受派修订；`status`可省略，或OPEN/KEEP/CANCEL/REASSIGNED。

`POST /api/v1/colleges/{cid}/configuration-impacts/{id}/resolve`接收`{decision,lock_version,task_lock_version,assignment_revision,note?}`。KEEP需`inspection.generate`，CANCEL需`inspection.cancel`，REASSIGNED需`assignment.manage`；范围、状态及任何修订不符均拒绝。CANCEL复用正式取消校验；REASSIGNED仅登记已经通过正常流程完成的新受派。原影响快照保持不变，处置独立审计。现阶段尚未部署。


### 2026-10-15 待发布：命名作息方案

在`/api/v1/colleges/{cid}/academic/semesters/{sid}/time-versions/profiles`下：

- `GET/POST /`：列表/创建草稿；创建体`{name,configuration}`，configuration复用默认作息结构，但calendar和grid_slot_mapping必须为空。
- `PATCH /{pid}`：`{name,configuration,lock_version}`保存草稿。
- `GET /{pid}/preview`和`POST /{pid}/publish`：发布体`{lock_version,revision,confirm_existing_tasks}`；只发布已保存草稿。
- `POST /{pid}/archive`：`{lock_version}`；有效教学班仍绑定时409。
- `POST /teaching-classes/{tid}/binding/preview`：`{profile_id}`，null表示学院默认；返回修订和保留的未来任务。
- `POST /teaching-classes/{tid}/binding`：`{profile_id,revision}`确认；课表必须能按目标方案解析，旧任务快照不改。

时段增量字段`slot_id`（稳定标识，省略时由节次生成）及`name`（显示名称）兼容旧请求。显式方案只覆盖上课时刻，学院统一校历仍适用；首版生效前跟随默认。当前为开发分支，未部署。


### 2026-10-15 待发布：组成员批量新增

`POST /api/v1/colleges/{cid}/groups/{gid}/members/batch/preview`请求`{semester_id,student_nos,effective_from,effective_to}`，明确最多200个不重复学号，日期沿用左闭右开成员有效期。返回`revision,count,items`；仅返回已经通过纳入校验的人员。

`POST .../members/batch/commit`在同一结构附`revision`，重新核对后整批新增；失败不保留部分结果。跨院人员仍须超管已有有效支援，既有重复或重叠成员拒绝，接口不授予资格与角色。当前尚未部署。


组引用补充：`references.types`仅为可选择的查课目标类型；`references.conflict_types`提供本院冲突规则目录，`teaching_classes`提供本院教学班基本标签用于具体课程例外。它们不包含名单、学籍或课表；冲突目录可见不构成对这些课程的查课/考勤权限。


### 2026-10-15 待发布：请假／不可用（所有组生效）

以下接口前缀为`/api/v1/colleges/{cid}/groups/{gid}`，需组织业务开关及e001迁移。受理组只决定申请/审批归属，获批限制本人所有组、所有学院的新排班。时间采用分钟精度的带时区ISO8601，服务端保存UTC，区间左闭右开，按任务冻结的真实活动时间判断。

| 方法与路径 | 用途 |
| --- | --- |
| GET `/unavailability?semester_id=...&page=1` | 有组读取权限者查看本组申请，每页50条 |
| POST `/unavailability` | 有组成员管理权限者登记待审批申请 |
| GET `/unavailability/{id}/impact` | 本组申请的审批前影响摘要，不返回外院任务ID/请假原因 |
| POST `/unavailability/{id}/decision` | 成员管理者批准、拒绝或撤销 |
| GET `/me/unavailability?semester_id=...&page=1` | 本人在指定组提交的本人申请 |
| POST `/me/unavailability` | 本人申请，服务端核对当前绑定，不得代人 |
| POST `/me/unavailability/{id}/withdraw` | 本人撤回，只接受CANCELED，不可自行批准 |

创建体`{student_id,semester_id,starts_at,ends_at,reason?}`；成员有效期必须覆盖完整区间。审批体`{lock_version,status,impact_revision?,note?}`，批准APPROVED必须带影响预览的`revision`作为`impact_revision`；请求、任务、受派变化后409，需重看影响。PENDING可以转APPROVED/REJECTED/CANCELED；APPROVED只可转CANCELED，终态不可重复操作。

返回ID均为字符串，状态/版本与`scope=ALL_GROUPS`明确给出。现有受派保留，未来有效任务进入变更影响清单；不更改考勤与截止事实。拒绝、撤销不再阻止新排班。批准时段不原地修改，需要撤销后新建并重新审批。小程序前端本轮不开发，现有登录/本人任务/考勤接口不要求随此增量修改。当前尚未部署。

## 2026-10-15 学校作息模板增量契约

新增 API 见 [学校作息模板契约](development/SCHOOL_TIME_TEMPLATE_API.md) 和 OpenAPI 的 `school-time-templates` 标签。学校更新产生不可变模板版本；学院引用生成独立草稿；更新只提示，不覆盖或自动发布。学院方案 DTO 新增可空 `source_template_version_id`，旧请求不变；个人课表及小程序接口不受影响。


## 2026-10-15 已确认模块增量（待部署）

独立全校汇总权限默认false、默认普通课及三种初始类型、换组预览/确认、SQL维度筛选、组履职、本人删除恢复和日期例外，以及统一通知列表的来源变化类型，见 [完整增量契约](development/CONFIRMED_MODULES_API_20261015.md)。通知新增kind；学籍变化项semester_id为null，客户端按kind处理。原初始化和基础条目增删改不改正式业务。


## R4/R5 增量契约（2026-10-16，已部署，相关业务入口待存量数据就绪启用）

本节对应 `f26a1016a001→a003`，承接已发布 `f26a1015h001`。保留已发布的学校节次模板、个人课表、查课与照片 API；现有学校节次模板是跨学期资产，以下“学期默认资料包”是显式冻结的作息＋校历＋教务映射。新入口沿用运行开关，不因页面存在自动启用。

| 功能 | 路径与方法 | 主要约束 |
| --- | --- | --- |
| 学期学校默认版本 | `GET/POST /api/v1/school/academic/semesters/{sid}/time-templates` | 超管发布；完整 TimeConfiguration＋name，可选 `period_template_version_id` 引用已有学校节次模板版本。节次被修改后不能伪称原版本来源。只新增不可变版本，不广播覆盖学院。 |
| 学院采用学校默认 | `GET /api/v1/colleges/{cid}/academic/semesters/{sid}/school-time-templates`，同前缀 `POST /preview`、`POST /adopt` | 请求 `template_id`、`effective_from`、`confirm_existing_tasks`；采用再加预览 revision。返回保留的学院例外和已有未来任务；事务内重验，变化 409。个人/命名作息方案仍复用原接口。 |
| 教学班身份候选 | `GET /api/v1/colleges/{cid}/academic/teaching-classes/{tid}/shared-identity/candidates` | 需本院 academic.manage。只推荐同校同学期上课资料一致的元数据，不返回外院学生名单。未确认仍独立；候选非自动合并结论。 |
| 教学班身份关联 | 同前缀 `POST /preview`、`POST /confirm` | 请求 `target_teaching_class_id`、必填 reason，确认携带 revision。课程、完整周次、节次/实际作息、时间地点及教师均核对；保留来源断言与学院视图。本视图今日及未来已有有效任务须先处置；历史任务不改写。确认后来源冲突阻断该班新任务，不覆盖其他来源。 |
| 负责人交接 | `GET /api/v1/colleges/{cid}/volunteer-groups/{gid}/handover/candidates?keyword=...`，同前缀 `POST /preview`、`POST /confirm` | 拥有所授全部动作且范围不受限的真实教师/超管；教师只能任命本院当前在籍学生账号或本院教师账号，其他/外院账号由超管确认，已有局部授权不作为扩大授权的依据；body `owner_user_id`、必填 reason、确认 revision。只撤销 owner_group_id 对应专属授权，保留独立授权与已有任务/排班。响应提示目标账号是否有 Web 登录方式，不创建密码。普通组编辑不再直接换负责人。 |
| 本人权限来源 | `GET /api/v1/colleges/{cid}/permission-sources/me` | 返回 FIXED_IDENTITY、EXPLICIT_GRANT、GROUP_OWNER 的实际有效动作及范围；不在前端猜测角色权限。 |
| 组织学期准备 | `GET /api/v1/colleges/{cid}/volunteer-groups/{gid}/semesters/{sid}/preparation/source/{source_sid}`，同 preparation 前缀 `POST /preview`、`POST /confirm` | 请求 source_semester_id、明确 member_ids、半开有效期 `[effective_from,effective_to)`、teaching_class_mapping；确认带 revision。先复核目标学期资格、学籍、支援和授权上限；任一选定成员未就绪不确认。只准备本学期规则与成员，不复制账号/绑定/组织/支援授权。目标组学期已有今日或未来有效任务时拒绝重新准备，先处置任务；追加成员使用现有成员维护入口。 |
| 归档 | `POST /api/v1/school/academic/semesters/{sid}/archive/preview`、`/confirm` | 超管按全校学期明确归档；body 必填 reason，确认 revision。先列未完成任务、未结异议、未处置影响、生成中报表；有阻断不可归档。不随学期切换自动归档。 |
| 归档考勤更正 | `POST /api/v1/colleges/{cid}/attendance/{rid}/archived-corrections` | 真实教师/超管＋该记录 attendance.correct；须已归档、非空依据、current_version。追加认定和 `attendance.archived.correct` 审计，不解冻其他业务或覆写旧报表。普通更正及新异议对已归档学期返回 409。 |
| 统计双维度 | `GET /api/v1/colleges/{cid}/statistics/semesters/{sid}/campus-dimensions`；校级 `/api/v1/school/statistics/semesters/{sid}/campus-dimensions` | 学院需 statistics.read；校级超管或明确 statistics.school.read。任务数与已形成正式结果的任务数分开；返回检查人次、去重学生数、去重学生课次数、按任务负责学院/学生当时学院分组的认定分布，不输出全校唯一考勤结论。 |

### 检查责任与兼容字段

- 所有既有 ID 保留；客户端把 task_key/occurrence 标识当不透明值，不按课程名、教室、组名自行拼键。任务负责学院从授权工作区固定，不因学生转院或操作者切换学院改变。
- 服务端按 `(负责学院,稳定课次,学生)` 占用。相同集合重试复用原任务；同院不同组/部分重叠名单整批 409，`fieldErrors.conflicting_student_count` 给出冲突学生数，不泄漏不可见任务名单。不同负责学院在原授权边界内独立保存结果；互不重叠名单可分别检查。预览筛除已被其他有效责任占用的候选；抽查不足不跨范围补足。
- 名单更正、学籍刷新、任务取消/恢复复用占用检查。无正式考勤或截止时事实的取消才释放占用；有事实不可用强制删除绕过保护。原任务已取消或名单已改版时，旧请求不覆盖它，返回 409 引导核对。
- 课程目录的课程编码改为本学院内唯一；旧全局编码存在歧义时要求使用明确学院入口。共享教务身份通过单独确认，不依赖课程编码唯一性推导。
- 只有管理考勤扩展响应 `task` 返回 `responsible_college_id`、`responsible_college_name`、`semester_status`；学生本人列表/详情维持升级前结构。现场照片、考勤 ID、异议 ID/一次审核及文件访问接口保持兼容。小程序无需学院参数或页面。
- `time_snapshot` 保留真实时刻，并可返回 `source_template_id`（学期默认资料包版本）、`source`、`calendar_source`、`adjustment_source`，用于解释学校作息/学院调整/单次调整。已生成任务不借当前作息回填历史。

### 迁移回退边界

三个新增迁移是本轮唯一新增链。迁移前先核对既有重叠责任；有冲突在 MySQL DDL 前阻断，不静默删历史。迁移演练在服务器临时库执行。产生跨院同编码目录后不能盲目降回全局唯一约束；降级先拒绝并要求核对备份，不自动删课程。应用回退不得把新增业务事实当作可丢弃草稿。

## 教工协作增量契约（2026-10-17，本地已实现，未部署）

对应迁移 `f26a1017s001`（档案与任职关系表）、`f26a1017s002`（绑定凭据表）、`f26a1017s003`
（`import_batch.target` 放宽）。响应中的 ID 一律字符串（避免 JavaScript 截断 BIGINT），路径与查询
参数按整数接收并校验范围，请求体里的关联 ID 用字符串（`^[1-9][0-9]{0,18}$`）。关系区间统一半开
`[effective_from, effective_to)`，`effective_to` 为空表示仍在任，非空时必须晚于 `effective_from`。
写入口要求 `lock_version`，不符返回 409 `VERSION_CONFLICT`；数据库约束冲突（唯一工号、锚点
CHECK、区间 CHECK、外键）一律映射为 409，不返回 500。事实、版本与审计同事务提交。

### 院级管理入口（`staff.manage`，受 `CAMPUS_CONFIGURATION_ENABLED` 与 `CAMPUS_ACADEMIC_SCOPED_ENABLED` 控制，未启用 503）

| 功能 | 路径与方法 | 主要约束 |
| --- | --- | --- |
| 档案列表/建立 | `GET/POST /api/v1/colleges/{cid}/staff` | POST body `staff_no`（保留前导零，学校内唯一）、`name`、可选 `phone`、`status`、`reason`。跨学院重号 409 |
| 档案读取/修改 | `GET/PATCH /api/v1/colleges/{cid}/staff/{staff_id}` | PATCH 必带 `lock_version`，且至少修改一个档案字段；姓名与状态不得置空 |
| 账号关联/解绑 | `PUT /api/v1/colleges/{cid}/staff/{staff_id}/account`，同前缀 `POST /account-unlink` | 只关联已存在账号，不读取姓名做匹配，不创建账号、不改角色与权限；档案已绑他账号或账号已绑他档案 409 |
| 绑定码签发/撤销 | `POST /api/v1/colleges/{cid}/staff/{staff_id}/binding-tokens`，`POST /api/v1/colleges/{cid}/staff-binding-tokens/{token_id}/revoke` | 库内只存摘要，明文只在签发响应出现一次；已兑换的码不可撤销复用，重复撤销幂等 |
| 授课关系 | `GET/POST /api/v1/colleges/{cid}/teaching-staff-assignments`，同前缀 `POST /{rid}/end` | `anchor_type=LOCAL` 只给 `teaching_class_id`，`SHARED` 只给 `academic_offering_id`，另一个必须为空（数据库 CHECK 同规则）。同锚点重叠、或 LOCAL 与 SHARED 覆盖同一共享身份 → 409 |
| 班级责任关系 | `GET/POST /api/v1/colleges/{cid}/class-staff-responsibilities`，同前缀 `POST /{rid}/end`、`POST /{rid}/handover` | `duty` 为 `HEAD_TEACHER`/`COUNSELOR`；关系只落在档案所属学院的行政班。同班同职责在职重叠 409。`handover` body `successor_staff_id`、`effective_on`、`lock_version`，一个事务内结束旧关系并建立新关系，交接日必须晚于在任起始日，接班人档案须有效且非同一人 |

`end` 的 `effective_to` 早于开始日拒绝；延长区间同样重查重叠，不制造并存的第二条在任关系。

### 本人入口（无学院开关，逐请求按有效档案判定）

| 功能 | 路径与方法 | 主要约束 |
| --- | --- | --- |
| 进入教职工身份 | `POST /api/v1/me/staff-binding` | body `staff_no` + `binding_code`。一次性原子兑换：已用/过期 409，工号不匹配只累计失败次数并 422，已关联账号的档案不能被抢绑。姓名与手机号不作为认领依据 |
| 入口能力摘要 | `GET /api/v1/me` | 响应含 `app_context`：`modes`、`default_mode`、`administrator` 与 `staff.views.teaching/responsible`。仅用于显示入口，不构成授权 |
| 本人查课卡片 | `GET /api/v1/me/inspection-records?view=teaching\|responsible` | 可选 `semester_id`、`inspection_date`、`date_from`、`date_to`、`teaching_class_id`、`administrative_class_id`、`responsible_college_id`、`course_name`、`page`、`page_size`（≤200）。SQL 先授权后分页 |
| 卡片详情与明细 | 同前缀 `/{task_id}`、`/{task_id}/attendance` | `view` 必填并参与授权判定；明细只返回有权范围内的学生，责任视图不泄露同任务其他学生。授课视图逐学生按**名单快照冻结的教学班归属**（`task_roster_member_class`）判定可否更正：合班任务里只属于他人教学班的学生不出现更正按钮，名单版本没有归属记录的历史数据标记「授课归属待核对」并禁止写入，改由教学班管理员核实。无正式考勤时 `counts=null`，未查课不计缺勤 |
| 汇总与导出 | 同前缀 `/summary`、`/export` | `/summary` 按学院与整体分列，跨学院任务不合并；`/export` 产出 xlsx，`Content-Disposition` 用 `filename*=UTF-8''`，与明细共用同一范围。授课批量查询逐来源教学班核对授权，只消费任务当前名单版本的冻结归属，不混入其他教师的学生或历史名单归属 |
| 本人认定更正 | `POST /api/v1/me/teaching-attendance/{record_id}/corrections` | body `attendance_type`、`current_version`（所见版本）、可选 `reason`。逐记录核对有效授课关系与该生的教学班归属后复用管理员同一更正事务：追加 `CORRECTION` 版本、推进 `current_version`、更新报表源修订（指向原任务负责学院数据域）。版本不符 409，不覆盖他人认定；**不触碰异议状态**，已发起的异议继续待责任学院审核 |
| 本人认定历史 | `GET /api/v1/me/attendance-records/{record_id}/versions?view=teaching\|responsible` | 与卡片 `allowed_actions` 的 `view_history` 配套；`view` 必填，两种工作视图用各自谓词，越界与不存在统一 404。只读入口不持 `FOR UPDATE`；复用 `assemble_versions`，不另建投影 |
| 本人正式课次日历 | `GET /api/v1/me/teaching-occurrences` | 查询 `date_from`、`date_to`（区间必填且 ≤31 天，倒序或超长 422）、可选 `teaching_class_id`、`page`、`page_size`（≤200）。按正式课表 + 校历生成课次，**与是否被抽到查课无关**：未生成任务的课照样返回并可改地点，停课日不出现，调补课按规划核心同一解析定位；已确认共享身份的同一真实课次跨学院视图合并成一条。逐日只列该日有效授课关系覆盖的班，任命区间外的课次不因当前在任而列出 |
| 指定课次换教室 | `GET/PATCH /api/v1/me/teaching-classes/{teaching_class_id}/occurrences/{occurrence_key}/location` | PATCH body `location`（`null` 表示恢复课表原地点）、`revision`（**必传**的所见地点版本，省略即 422，不给跳过乐观校验留后门）、可选 `reason`。只联动该真实课次尚未完成的任务，已完成/已取消/已形成考勤的任务保留现场原地点；GET 不加行锁。已有任务还合并其他独立课次且本次改变目的地时，返回 409 并指出需先拆分的任务，地点覆盖、版本与审计全部回滚；后续预览和生成先按每个课次的有效地点分组，避免带改其他班。并发写冲突回滚后最多重试三次，仍冲突 409 |
| 责任区异议与一次审核 | `GET /api/v1/me/responsible-objections`、`GET …/{objection_id}`、`POST …/{objection_id}/review` | 列表/详情只聚合本人有效责任关系覆盖的学生；逐条返回 `can_review` 与 `review_block_reason`。审核复用管理员终审同一条状态机（`decision/final_type/comment/current_version`），锁序为学院锚点→考勤→异议；不在本人范围统一 404 防枚举，任务确属外院负责 403 要求由该学院审核，版本过期或已结案 409 |

审核改判所需的考勤版本以**审核时**的版本为准：教师更正等合法写入推进版本后，责任学院按刷新后的
`current_version` 重新提交即可结案，不再要求考勤版本等于异议发起时的 `base_attendance_version`
（旧规则会让异议在被更正后永久无法审核，而学生有一条未完成异议时不能再次发起）。**通过和驳回都必须**
提交所见的 `current_version`：版本不一致时在锁内、写库前返回 409 并说明当前认定与版本，驳回同样是
对事实的确认，不能凭旧页面结案。发起版本与本次落差记入审计的 `attendance_changed_since_filing` 与
`base_attendance_version`，版本链完整保留。

材料访问（现场照片、异议证明）在文件域按逐文件事实判定：任课教师限本人授权课次，班主任/辅导员
限本院任务且名单快照中存在本人责任班学生；跨院只读汇总不隐含材料权限。撤权或档案停用后下一次
读取或签名即拒绝。

### 唯一人员关系与导入联动（2026-10-18，已实现，待部署）

显式学院入口的 `timetable/grid_timetable/admin_roster` 在上传预览中增加
`summary.person_links_create/person_links_existing/person_links_pending`，确认后增加
`person_links_created`。普通长表可填 `教师工号`；旧班级责任表可填 `班主任工号/辅导员工号`。
`class_duty` 是 `admin_roster` 的上传别名，继续使用该类型的下载模板。工号、学号填写文本，保留前导零。

匹配顺序：同校工号准确匹配并核对姓名；只有姓名时须全校有效档案唯一，不采用“本院同名优先”。
未知、同名、已有关系冲突作为 `PERSON_LINK_PENDING` 警告，不隐式创建人员/账号、不猜绑定微信，
也不妨碍资料本身导入。有 `staff.manage` 才能建立人员关系；否则保存原资料并提示由有权人员补关联。
关联写入与资料/审计同事务，精确确认集合纳入人员与任职关系基线，过期匹配返回409。
重复导入保持既有关系日期与版本；空白/缺行不撤销、已结束的关系不因旧表重导恢复。
授课仅关联本次学院的 LOCAL 教学班，不扩成跨院 SHARED 授权；授课开始不早于确认日或学期开始日，
结束为学期结束次日（半开区间）。换教师/负责人及调整有效期仍走明确调整/交接。

存量资料无需重新上传：

- `POST /api/v1/colleges/{cid}/imports/confirmation-set/person-links/preview`
  JSON `{ "kind": "teaching", "semester_id": "学期ID" }`，或 `{ "kind": "responsibility" }`。
  返回 `revision`、上述三个计数的 `summary`、`links`、`pending`。关系行含 kind、班级标识、
  name、staff_no、staff_id、半开有效期和 action（CREATE/UNCHANGED）；待处理行含 message。
  不返回候选全校人员列表、手机号或绑定凭证。
- `POST /api/v1/colleges/{cid}/imports/confirmation-set/person-links/confirm`
  同一范围 JSON 加 `revision`。返回 `person_links_created/person_links_pending/summary`。
  只补明确缺失关系，未知或冲突保留待办；资料、身份、关系、日期或学院变化返回409，重新预览后确认。

两个入口均要求本院 `staff.manage`，沿用学院配置和正式业务开关，不绕过未启用状态。
本轮仅增后端与 Web；不修改小程序身份绑定或学生考勤接口。

### 报表与关系管理的身份字段（2026-10-18，待部署）

`ClassStatsItem` 新增可空 `college_id`，`class_id` 优先来自任务名单冻结的行政班 ID，
同名不同班不再合并。缺历史 ID 时不从当前学籍或名称猜填。`AbnormalDetailItem` 新增可空
`student_id/administrative_class_id_snapshot/college_id_snapshot`；`TaskStatsItem` 新增
`administrative_class_ids`（冻结名单当前版本的行政班集合）。上述所有 ID 对外为字符串。
班级明细必须按这些 ID 筛选，不能用班名包含或学生姓名合并。当前底册只供辅助显示，不参与正式统计。
负责人优先读取统计期间有效责任关系，期间交接展示命中姓名合集；从未建关系的旧文字仅兼容显示。
已发布周报与历史快照不自动重写。

本地授课关系管理按教学班所属学院限定，外院教师在本院授课不会转移课程管理权。
`GET /colleges/{cid}/teaching-staff-assignments` 额外返回 staff_no/staff_name 供显示；
教师档案及账号仍由其档案所属学院维护，SHARED 的既有授权范围保持不变。

### 教职工资料导入

目标值 `faculty_staff`、`class_responsibility`、`teaching_assignment` 直接作为
`import_batch.target` 落库（`f26a1017s003` 放宽 CHECK），不再借用 `admin_roster`/`timetable` 别名；
历史批次仍按 `payload.import_type` 识别。模板下载、预览与确认要求 `import.execute` 加本院
`staff.manage`，确认阶段按批次真实种类重新授权。请求走既有 `/api/v1/colleges/{cid}/imports` 与确认
集合契约，无新增端点。

解析与写入约定：工号按字符串匹配并保留前导零；只有姓名时同名多人或未知工号阻断，不自动授权；
责任列为空或整行缺失不结束现有任职；授课锚点必须显式，留空按 `LOCAL`，无效值报
`INVALID_ANCHOR_TYPE`；同锚点重叠或跨锚点覆盖同一共享身份在预览给出
`MULTIPLE_TEACHING_OVERLAP`/`ANCHOR_OVERLAP`，确认阶段 409；补录区间只更新与之重叠的那条任命，
不影响不重叠的历史记录。整批在确认集合的单一提交点落库，任一行失败全部回滚，重试不重复。

## 2026-10-18 导入 ZIP 预览（原接口随 bed04b8 发布，members 增量随 6a00179 发布）

`POST /api/v1/colleges/{cid}/imports/confirmation-set/zip-preview`：multipart 上传 `file`、`target`，可选 `semester_id`、`teaching_class_id`、`course_type_id`。与原学院导入相同的功能/范围鉴权，仅创建成员预览，不写正式资料。返回 `files`（逐成员预览）、`errors`（filename/message）、`business_data_applied=false`。成功成员仍须经现有集合 preview 与携带 revision 的 confirm；前端必须让用户明确处理/排除失败成员，不能静默确认成功子集。

限制：ZIP 10 MiB、20 个表格、每成员 10 MiB、总展开 50 MiB、目录项 200。接受 xls/xlsx/csv，拒绝不安全或重复路径、加密、链接、嵌套归档及其他文件。格式/范围不合规返回现有 422/权限错误；详细行为见 development/IMPORT_FLOW_SIMPLIFICATION_20261018.md。该接口开发完成不等于生产可用。

### 2026-10-18 统一资料入口识别与模板（随 6a00179 发布）

以下接口已随源码 `6a00179` 部署。共同受学院配置及正式业务隔离开关保护，并要求 `import.execute`；具体资料类型仍按目标管理权限核对。

- `GET /api/v1/colleges/{cid}/imports/intake/catalog` 返回 `{types, max_files:1000, max_batch_files:100, max_file_bytes:10485760, max_archive_bytes:52428800}`。`types` 仅列出当前操作者可管理的资料类型，每项含 `target`、`label`、`required`、`semester_required` 和 `manage_permission`。类型包括行政班与学生名单、教职工档案、班级责任关系、标准课表、教务网格课表、志愿者学期资格底册、教学班补充名单、选修与分层课补充资料；其中 `timetable` 与 `grid_timetable` 是两种课表来源，用户按实际文件选择。权限不足的类型不返回。`max_files` 是待处理队列上限；`max_batch_files` 为单次确认集合上限。单表格 10 MiB，ZIP 50 MiB。
- `POST /api/v1/colleges/{cid}/imports/intake/inspect` 使用 multipart `file`，接受一个表格或混合 ZIP。响应 `data={files:[{filename,target,blocked,message,archive_member}],business_data_applied:false}`；不会建立导入草稿或写业务资料，不返回人员数据行。ZIP 内每个成员分别识别；未知类型的 `target` 为 `null`，可由用户选择后进入正式预览，文件内容仍由原导入解析器校验。单文件最大 10 MiB；ZIP 沿用 ZIP 预览的 10 MiB 压缩包、20 个表格、单成员 10 MiB、展开合计 50 MiB、目录项 200 及路径/格式安全限制。超过文件解析界限（20000 行或 256 列）、不可读文件及多于一个有内容工作表的表格会标为 `blocked`，不得静默忽略其他工作表，须拆分文件后重传。
- `GET /api/v1/colleges/{cid}/imports/intake/templates` 返回 ZIP 标准模板包，仅包含当前操作者对其目标具备管理权限的类型。响应为 `application/zip`；生成模板不创建导入预览或写业务资料。

混合 ZIP 的识别仅帮助分组，正式写入仍按资料类型分别调用现有预览、冲突核对和确认流程，不形成跨类型事务。调用 `POST /api/v1/colleges/{cid}/imports/confirmation-set/zip-preview` 时可额外传 multipart `members`，值为 JSON 字符串数组（如 `["教师.xlsx"]`），精确选择 ZIP 中要处理的同类型成员；省略 `members` 保持旧的全成员行为。成员选择不允许跨类型合并成一个确认集合。

人员身份及冲突处理沿用本地实现规则：已有工号/学号关联到的人员若与新资料姓名不符，确认集合阻断保存；用户须先到对应学生或教职工档案核对并明确更名，再重传并重新核对。责任表仅凭姓名消歧时检查同校有效档案，不能以本院同名优先掩盖外院同名；只用姓名且结果未知或重名时阻断责任授权。课表中只有教师姓名且待关联时，保留问题详情但不阻断课表资料保存。教师档案、授课关系及班级责任变更继续使用现有维护与交接入口；导入不扩大本人关系授权或跨院授课授权。Web 应保留逐项问题详情及已有档案、授课、责任关系处理入口，修正后重新上传或重新核对。

### 2026-10-18：本人教职工学院名称

`GET /api/v1/me` 在 `data.app_context.staff` 中新增 `college_name`（字符串），与
既有 `college_id` 同级，返回本人有效教职工档案所属学院的当前名称。示例：

```json
{"college_id": "101", "college_name": "人工智能学院"}
```

无需新增请求参数。学院改名后下一次请求返回新名称；未绑定有效教职工档案或学院已停用时，
仍返回 `staff: null`。该展示字段不改变角色、授权或学生绑定流程。


### 2026-10-18 拖放与大包上限增量

本批次统一替代上文旧体积/数量值：待处理队列及单 ZIP 最多 1000 个表格，ZIP 最大 50 MiB，解压合计 200 MiB，目录项最多 5000；单表格仍为 10 MiB。每次 confirmation-set 最多 100 个文件，变更条数沿用 IMPORT_MAX_ROWS（默认 5000），Web 可选 20/50/100 文件分批；已保存批次不重传、不回滚。ZIP members 最多 100 个路径，预览仅解压选定成员，仍验证整包元数据。Nginx 请求体上限配套为 52m。无新表、无业务权限扩展；发布状态以当前实施状态为准。

### 2026-10-19 管理删除与恢复（本地实现，发布状态见当前实施状态）

迁移 `f26a1019d001` 为 course_type、volunteer_group、inspection_task 增加可空 deleted_at，不回填历史。

- `GET /colleges/{cid}/groups/{rid}/deletion-impact` 与 `GET /colleges/{cid}/course-types/{rid}/deletion-impact` 返回 `mode=PERMANENT|RETAIN_HISTORY`、`references`、`blocking_task_ids`、`can_delete`、`revision`。仍有待执行任务时拒绝删除，须先取消/转组；未来任务生成/排班不得使用停用或删除配置。
- 原 DELETE 对应资源路径接收 `{lock_version,deletion_revision}`。有引用或内置类型必须提交最新预览 revision；无引用的原客户端请求仍兼容。未使用配置彻底清理；有成员/配置使用/课程/任务等引用时保留原实体、置停用并记录 deleted_at，从日常列表移除，保留历史与审计。组删除撤销其 owner_group_id 专属授权，不撤销独立院级授权。
- `GET /colleges/{cid}/volunteer-groups?deleted_only=true`、`GET /colleges/{cid}/course-types?deleted_only=true` 仅列出保留历史的删除项。POST `/colleges/{cid}/groups/{rid}/restore-deleted` 或 `/course-types/{rid}/restore-deleted` 接收 `{lock_version,name?}`；恢复为 INACTIVE，重名时允许改名，不自动恢复旧授权。原读/管理权限及学院范围仍适用。
- `POST /inspection-tasks/deletion-preview` 接收 `{task_ids:[字符串ID]}`，返回 `retained_ids`、`permanent_ids`、`history_preserved=true`、`revision`；学院入口同为 `/colleges/{cid}/inspection-tasks/deletion-preview`。1—500项，混入无权/不存在任务整批404。
- 原单删 DELETE 可传 query `deletion_revision`，批量 POST `/inspection-tasks/batch-delete` body 增加 `deletion_revision`。存在提交、正式考勤、截止考核、变更影响或已归档学期的任务只移除管理可见性；其他误建任务彻底清理。返回原删除计数/ID并增加预览分类。有历史必须携带匹配的revision，过期409；force不能改变分类。管理历史保留不取消考勤、照片权限、统计或任务键，不释放已冻结责任给重建任务。
- 管理任务列表 query `deleted_only=true` 仅显示保留历史的删除项；默认不显示。POST `/inspection-tasks/{task_id}/restore-deleted`（含学院别名）接收 `{lock_version}`，恢复原状态和ID，不重新排班。已删除任务不能经普通编辑/提交路径修改；本人历史、考勤与报表读取沿用原范围，删除不消除业务事实。

删除、范围校验、版本更新、专属授权撤销与审计同事务。生产回滚仅切换应用与Web版本，保留新增可空列；显式降迁移前必须恢复所有保留历史的删除项，否则拒绝降级。

### 2026-10-19 志愿者选组与成员 Excel 导入

所有入口仍受配置、学院正式业务开关及当前学院/组范围授权保护；准备成员不要求组织排班开关开启。停用组允许准备成员，已删除组禁止；实际生成和排班仍要求组启用且通过原资格、支援、课程冲突和配额规则。

- `POST /api/v1/colleges/{cid}/groups/{gid}/members` 保留原请求字段，新增可选 `enable_qualification`，默认false兼容旧客户端。明确传true时，复用本学院资格写入规则，在同一事务中开通资格、维护已关联的学生账号角色并加入当前组；额外要求 `volunteer.manage`。没有任何新建学生、自动更名、自动跨院支援或任务指派。
- `GET /api/v1/colleges/{cid}/groups/{gid}/members/import-template` 下载空xlsx模板，仅“学号、姓名”两列，学号列预设文本格式。要求 `volunteer.member.manage`。教师须先在“学生与班级”建立有效学籍，再导入志愿者组。
- `POST /api/v1/colleges/{cid}/groups/{gid}/members/import/preview` 为multipart：`file`、`semester_id`、`effective_from`、`effective_to`（不含结束日）、`enable_qualification`（默认true）。最多2MiB、单工作表xlsx、200人。文本学号保留前导零，姓名与学号都必填；数值学号、公式、重复学号、多个工作表或超限文件返回422，不猜测补零或合并名单。
- 预览不写资格、成员、账号或角色。返回 `revision/count/can_commit/qualifications_to_enable/unchanged/issues/items`；items包含 `source_row/student_no/name/status`（ADD、UNCHANGED、BLOCKED）、可选 `student_id/message/qualification_action`。未知学号、姓名不符、非在读/未知归属、无覆盖支援授权及有效期冲突逐行阻断；阻断行不泄露未授权学生的档案姓名。
- `POST /api/v1/colleges/{cid}/groups/{gid}/members/import/commit` 重传相同文件和表单，另带 `revision`。服务端重新解析、授权、加锁核对学籍/资格/成员与组配置；任何阻断或过期修订409，整批不保存。成功返回 `created/unchanged/qualifications_enabled/items`。完整相同组/学期/有效期的已有有效成员作为UNCHANGED保留，不重复建人或成员；不同组可各自加入，部分重叠有效期仍须人工核对。
- 旧JSON `/members/batch/{preview,commit}` 可选传 `expected_names`（学号→姓名映射，须覆盖全部输入学号）、`skip_existing`、`enable_qualification`，默认均保持旧行为。已有资格且跨院支援有效的学生可以加入；缺少资格的跨院学生须先由学籍所属学院开通资格，当前组不能借导入扩大权限。

资格写入默认仍独立提交；仅本模块内部显式使用不提交模式纳入组成员事务。任意后续写入失败会一起回滚资格、账号、角色、成员及审计。只复用已通过Student.id明确关联的系统账号，不以姓名或“用户名恰好等于学号”认领无关账号。

Web入口：“志愿者组织→组织与规则→组行的导入成员Excel”或“成员、支援与请假→选择组→导入成员Excel”；单人添加在“本学期资格→添加志愿者（选组）”。保存不启用组或全局排班，也不分配查课任务。小程序无需新增页面或改接口。

## 测试运营期临时教职工身份

- `POST /api/v1/me/staff-binding` 请求字段不变：`staff_no` 接受当前工号或该档案保留的临时工号，仍须同时核验一次性绑定码；返回主工号，保留单次核销、有效期、停用和账号唯一关联检查。
- `POST /api/v1/auth/web/login` 仍为用户名与密码登录，不把临时工号作为用户名别名；绑定临时档案的普通教师须先核对真实工号。既有管理员登录保留，Web 刷新与会话回查适用相同检查。
- 教职工普通新建/档案导入拒绝 `TMP_` 保留前缀。后台初始化命令先核对每条来源，再建档和任职；不开放新 HTTP 接口、不创建 Web 密码、不增加角色。
- 后台提取、核对、导出及补充真实工号见 [临时工号操作说明](development/STAFF_TEMPORARY_ONBOARDING.md)。

## 课表确认的周次与重复行

确认集合中的课表条目标识包含周次集合。同一教学班、课程、星期和节次但周次不相交的安排可以共存（例如单双周教室不同，或第1—10周和第11—14周分段授课）。实际周次有交集且节次区间重叠时仍阻断，问题码为 `SCHEDULE_OVERLAP`，提示包含课程、交集周次、星期、节次及另一个来源文件和行号，不再误报为“多个文件修改同一条资料”。

普通/网格课表在同一文件中出现业务内容完全相同的行时，只应用一次并返回 `DUPLICATE_SCHEDULE_ROW` warning，保留来源定位；教师、教室或周次不同的安排不会作为重复行忽略。跨文件同一时间安排仍须明确核对；非课表实体保留原有跨文件冲突规则。预览、确认及重导幂等使用相同判定；请求/响应结构及 OpenAPI 字段未变。
# 自动换班策略接口候选（2026-10-24，本地未部署）

路径：`/api/v1/colleges/{cid}/groups/{gid}/inspection/auto-change-policy`。

- GET查询参数`semester_id`；PUT请求`{"semester_id":"123","enabled":true,"current_version":0}`。拒绝未知字段、字符串布尔值和客户端指定授权人。
- 返回`{enabled, version, authorizer_user_id}`，外层沿用`{data, requestId}`。未配置时关闭、版本0；成功修改递增版本，旧版本返回409。
- 复用原学院/组排班管理与换班审核权限，授权人取实际登录账号。依赖学院配置/教务隔离/业务隔离/组织排班开关及`AGENT_AUTO_CHANGE_ENABLED`，新增迁移为`f26a1024a003`；所有新增能力默认关闭。
- 开启不追溯处理已有申请。新申请同事务登记执行记录；自动改派仍需后台工作流调用领域服务。无合法候选保留原受派和待处理申请，关闭或变更策略后拒绝原执行。管理端卡片已接入并通过模拟交互验证，腾讯云触发闭环尚未完成，不作为已上线接口。
