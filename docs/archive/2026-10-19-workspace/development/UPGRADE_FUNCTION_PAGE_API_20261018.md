> 2026-10-19 归档：原路径 `docs/development/UPGRADE_FUNCTION_PAGE_API_20261018.md`。这是未提交的历史草稿，保留供追溯；功能状态、账号时序、版本、链接和部署信息可能过时或互相冲突，不作为当前需求、接口合同或操作手册。当前以 `docs/development/IMPLEMENTATION_STATUS.md`、已确认产品设计及实际接口为准。

# 升级后的功能、业务逻辑、页面与小程序 API 总览

核对日期：2026-10-18。范围：本轮学院化、教务与组织升级，以及后续教职工协作增量。
原有功能仅列这次发生变化的部分，不把登录、普通名单管理等全部重复算作新增功能。

本文按当前 Router、Schema、Service、Web 页面及仓库内小程序代码整理。历史设计中的建议接口
与未开启能力单独标注，不能直接作为已经可用的页面或联调契约。

**用户后续确认的目标（2026-10-18）：** 每位教职工拥有由工号确定的固定账号，统一使用教职工身份
和同一套“课程/考勤/我的”小程序界面，展示本人课程及管辖责任区考勤。不按任课教师、班主任、
辅导员分别登录或另做界面。以下描述保留当前代码事实；账号生成和统一小程序界面尚需按
统一账号与界面需求（原相对路径：`../product/STAFF_MINIAPP_IDENTITY_REQUIREMENTS_20261018.md`）补齐，不能当成已经实现。

## 1. 当前上线状态

本轮只读核验服务器：应用代码 `f3539a1ced294b42bbb18810c7b1f9e0e6c47a9d`，后端和 Web
发布目录均为 `20261018-staff-f3539a1ced`，数据库版本 `f26a1018s006`。
完整发布和回滚证据见教职工协作发布记录（原相对路径：`STAFF_COLLABORATION_RELEASE_20261018.md`）。

| 能力开关 | 服务器实际状态 | 产品含义 |
| --- | --- | --- |
| 学校/学院配置 | 开启 | 可按权限维护学校、学院及基础配置 |
| 学院教务范围 | 开启 | 教务基础数据使用学院范围入口 |
| 正式教务发布 | 开启 | 可明确发布；本人正式来源、课表备份与通知接口可用 |
| 学院正式业务范围 | 开启 | 查课、考勤、异议、报表等按授权学院/资源处理 |
| 学院作息及新组织排班 | **未开启** | 学院作息发布、组成员/支援/不可用、学期准备、组范围抽查等仍受门禁限制 |
| 提前提交测试例外 | **未开启** | 志愿者默认不能在查课日期前提交；`CM_DEV_ALLOW_EARLY_SUBMISSION=1` 才放行 |

“后端/Web 已部署”不等于“小程序页面已完成”。本仓库小程序 `app.json` 仍为“首页/我的”
两栏，没有本轮教工三栏页面，也未检索到对本轮教工、课表备份、教务通知接口的调用。
独立小程序上游或微信线上包的状态未在本轮核实，不能根据本仓库副本推断其全部状态。

## 2. 新增、扩展功能与 Web 页面

以下路径是 Web 路由。进入页面仍需对应权限、有效任职或能力；页面存在不表示所有账号都可用。
带 `tab` 的地址是同一页面内的子页，不是独立新增页面。

### 2.1 学院化、教务与学生业务

| 功能 | 新增或变化的业务逻辑 | 对应页面/入口 | 当前状态 |
| --- | --- | --- | --- |
| 统一工作台 | 按实际权限展示业务入口、准备状态与待办；增加本人授课、本人班级与待审异议入口 | `/dashboard/home` | 已部署 |
| 学院和学期上下文 | 一个统一工作区；换学院/学期使旧请求、旧表单和旧确认失效；档案类页面不随学期清空 | 页面顶部工作区；全局导航 | 已部署 |
| 新业务导航 | 七个日常入口：工作台、教务资料、学生与班级、志愿者组织、查课安排、考勤与异议、统计报表；管理类辅助入口单列 | `/dashboard/*`；旧 schedule/tasks/reviews/objections/volunteers 地址转到对应子页 | 已部署 |
| 学校与学院管理 | 学校/学院、教师管理员固定学院、额外学院或资源授权；停用和归属变更不等于清理历史 | `/dashboard/school?tab=administration` | 已部署 |
| 存量资料归属核对 | 先预览归属影响再确认，历史事实不能只因当前班级或名称改变而被重新归属 | `/dashboard/school?tab=ownership` | 已部署 |
| 账号权限细分 | 教师管理员、超管和学生工作负责人管理分清；平台账号管理使用显式能力，不增加一个新角色代替权限 | `/dashboard/users` | 已部署 |
| 学院正式教务 | 本院课程、教学班、正式课表、名单与分类；共享教务身份和学院管理视图分开 | `/dashboard/academic?tab=timetable`、`tab=classes` | 已部署 |
| 课程类型配置 | 类型是可维护数据，可新建/修改/停用，教学班持有类型；历史任务保留类型快照 | `/dashboard/academic?tab=types` | 配置已部署；新组织排班消费受排班开关限制 |
| 资料准备与确认向导 | 上传后预览新增/更新/不变、来源与问题，明确选择确认集合；导入不等于正式发布，不自动覆盖个人课表 | `/dashboard/academic?tab=imports` | 已部署 |
| 正式教务发布 | 学院按学期预览并发布正式来源；再次发布产生更新通知，由学生主动更新私人副本 | `/dashboard/academic?tab=publication` | 已部署 |
| 共享教学班身份 | 通过明确映射关联同一教务课程，不能仅凭教师/课程名或同教室推断共享授权；各院检查结果保留独立负责学院 | 教务资料的教学班与导入身份核对界面 | 已部署；不代表所有存量教学班已完成映射 |
| 学生当前档案 | 当前学生、行政班、绑定与身份持续保留，不为新学期复制一套账号和学生 | `/dashboard/students?tab=directory` | 已部署 |
| 按日期看学籍 | 按生效日期读取学籍和行政班，不用当前班级反推过去名单 | `/dashboard/students?tab=history` | 已部署 |
| 学籍异动与学生交接 | 异动先预览、明确生效日期与未来影响；历史任务/考勤保留原快照；交接有确认状态 | `/dashboard/students?tab=handoff` | 已部署 |
| 学期与归档 | 学期、共享校历和节次继续维护；归档约束日常写入，授权纠错与新业务写入分开 | `/dashboard/settings`；`/dashboard/school?tab=archive` | 已部署 |
| 学校作息模板与学院版本作息 | 学校模板、引用草稿、命名方案、教学班绑定、学院校历及真实起止时刻；采用更新需明确确认 | 学校/学院配置组件；`/dashboard/academic?tab=time` | 代码已部署；学院作息子页当前隐藏，发布/绑定链未启用 |

### 2.2 志愿者、查课、考勤与统计

| 功能 | 新增或变化的业务逻辑 | 对应页面/入口 | 当前状态 |
| --- | --- | --- | --- |
| 持续存在的志愿者组织 | 组织跨学期保留，课程类型范围、组内规则和配置版本独立维护；默认规则变化不覆盖已准备学期与已有任务 | `/dashboard/organizations?tab=groups` | 配置已部署 |
| 本学期志愿者资格 | 学期资格和账号/组织实体分开；有底册不代表已完成真实微信绑定 | `/dashboard/organizations?tab=qualifications` | 已部署 |
| 组成员、支援与不可用 | 成员按学期和有效期；跨院支援明确授权；不可用应作用于相关受派检查，不靠改派代替换组 | `/dashboard/organizations?tab=members` | 已有代码；当前因排班开关显示未启用提示 |
| 组织学期准备 | 将组织默认规则明确准备到目标学期；成员/资格核对，支援不自动续期，不复制账号 | `/dashboard/organizations?tab=preparation` | 已有代码；当前未启用 |
| 选择具体课次 | 先选择具体日期和节次，携带 `selection_scope/selection_revision`；旧预览与当前资料不一致时拒绝确认 | `/dashboard/inspections?tab=selection` | 已部署 |
| 两阶段生成排班 | 生成任务与指派分开；排班失败保留生成结果，只对返回的可排任务继续排班 | `/dashboard/inspections?tab=tasks` | 已部署 |
| 按组范围抽查、确认排班计划 | 先按授权、课程类型、班级筛选再抽；不跨类型补缺；核对跨组受派、本人课冲突、配额等，再确认计划 | `/dashboard/inspections?tab=sampling` | 已有代码；当前未启用 |
| 未来变更处置 | 配置/资料变更展示对未来任务的影响并明确处置；既往结果不随配置重写 | `/dashboard/inspections?tab=impacts` | 已部署，仍需实际权限 |
| 提交截止与考核事实 | 学院截止规则、逐日版本及截止时事实；允许逾期补交但不抹除已经形成的截止考核事实 | `/dashboard/inspections?tab=deadlines`；任务与排班 | 已部署 |
| 换班申请 | 申请状态与任务状态分开；申请中仍承担原受派责任，审核通过也不等于管理员已完成改派 | 查课安排的任务/申请处理；原小程序任务页 | 后端已提供；小程序行为需按实际版本验收 |
| 学院考勤与现场照片 | 当前认定、历史版本和现场材料分开；列表、详情、导出和文件访问按同一资源范围 | `/dashboard/attendance?tab=records` | 已部署 |
| 学生异议一次审核 | 待审→通过/驳回；可维持原判或改判，审计和考勤版本同事务；不再新增初核环节 | `/dashboard/attendance?tab=objections` | 已部署 |
| 统计与导出扩展 | 按负责学院、课程类型/组等范围处理；当前认定与版本归档分开，不能伪造班级分母 | `/dashboard/reports`，行政班/课堂/明细等现有报表 | 已部署相关范围与报表扩展 |
| 全校汇总、组绩效读取 | 全校汇总能力不授予明细访问；组绩效仍受资源范围限制 | 后端 summary-statistics 接口 | 后端已提供；本轮未核对到对应独立 Web 展示入口，不能当作已交付新看板 |

### 2.3 教职工协作——本次最新上线的功能

| 功能 | 新增或变化的业务逻辑 | 对应页面/入口 | 当前状态 |
| --- | --- | --- | --- |
| 教职工档案 | 工号、姓名、归属学院、状态、登录账号关联；普通教工档案不自动获得学院管理权限 | `/dashboard/staff` | 已部署 |
| 教工绑定码 | 管理员签发/撤销；本人凭工号和一次性码兑换，不凭姓名或手机号认领 | 教职工档案操作；小程序未来的“我的→绑定教工” | 后端/Web 管理操作已部署；小程序绑定页面待做 |
| 任课关系维护 | 本院教学班 `LOCAL` 或明确共享教务身份 `SHARED`；含学期和生效/结束日期，不按教师显示姓名授权 | `/dashboard/academic?tab=teaching-assignments`，标签“任课教师” | 本院教学班手工维护已部署；共享任命的 Web 批量入口见下方缺口 |
| 班主任/辅导员责任关系 | 明确关联本人档案和行政班；交接原子结束旧关系、建立新关系；当前与历史责任不能混为一谈 | `/dashboard/students?tab=responsibilities`，标签“班级负责人” | 已部署 |
| 多身份和工作视图 | 同一人可同时有学生/教工身份；教工按任职显示授课/责任视图，不取“最高角色”放大全部权限 | 工作台本人入口；`GET /me` 的 `app_context` | 后端/Web 已部署；小程序模式切换待做 |
| 我的授课查课记录 | 本人授课任务卡片、明细、当前认定与统计，支持分页和 Excel；未形成考勤显示未查，不记缺勤 | `/dashboard/attendance?tab=my-teaching` | 已部署 |
| 我的班级查课记录 | 仅按本人负责行政班的冻结名单学生显示；合班任务不暴露其他班学生 | `/dashboard/attendance?tab=my-class` | 已部署 |
| 教师直接更正 | 任课教师可更正有权学生的认定，保留原始提交、旧版本与审计；不会自动关闭学生异议 | 我的授课→名单与认定→更正 | 已部署 |
| 本人认定历史与照片 | 授课/责任视图均可读各自可见记录的历史；现场照片继续申请短期授权链接 | 我的授课/我的班级→名单与认定 | 已部署 |
| 责任区异议一次审核 | 本人责任班级异议聚合；任务属外院时不默认授予改判能力；显示 `can_review` 与限制说明 | `/dashboard/attendance?tab=my-objections` | 已部署 |
| 正式课次日历 | 从正式课表和校历解析，不要求先被抽到查课；按任职生效日期过滤，支持调补课、分页和日期区间 | 我的授课下方“近期正式课次” | 已部署；当前列表显示节次，尚未补齐起止时刻 |
| 指定一节课换教室 | 用真实课次键修改指定日期的地点覆盖，可恢复原址；不改原始导入课表或已完成任务快照 | 近期正式课次→改教室；查课卡片也可进入 | 已部署；既有多独立课次合并任务不能自动拆分 |
| 教职工批量导入 | 后端支持 `faculty_staff/class_responsibility/teaching_assignment` 三类规范目标及模板、预览、确认 | 后端院级导入 API | 后端已部署；当前 Web 资料准备未列出三类专用选择入口，不记为已完成批量页面 |

## 3. 需要共同遵守的新增业务逻辑

1. **三种身份不能混用。** 学院教师管理员的固定学院、任课教师的授课关系、班主任/辅导员的责任关系
   是不同授权来源。学生工作负责人这个既有学生角色也不等于新教工辅导员档案。
2. **普通教工没有全院权限也能工作。** 有有效档案和任职即可进入本人视图；不能据此进入本院所有
   考勤或其他学院资料。账号、档案、学院及任职均由后端逐请求复核。
3. **关系有效期是半开区间。** 使用 `[effective_from, effective_to)`；本人授课/责任范围查询还要
   核对当前关系及目标课次日期，不只看今天界面是否有某个角色。
4. **合班任务按学生判断。** 名单版本冻结每个学生来源教学班。只教 A 不能因此统计、导出或更正 B；
   明确共同授课按真实映射授权。旧名单无来源时显示待核对，允许相应兼容读取但拒绝本人更正，
   不按今天选课猜历史。汇总和导出只用当前名单版本的归属。
5. **教师更正与异议审核是两个命令。** 教师更正追加认定历史，不自动结案异议；责任人审核自己的
   责任区异议。教师更正后，审核人刷新并以当前 `current_version` 审核，不要求版本永远等于
   异议发起时的版本。审核仍必须核对当前所见版本，不能覆盖其他人的新认定。
6. **跨院同堂不合并学院结果。** 卡片显示任务负责学院；辅导员能看到负责学生的记录，不等于能审核
   所有外院任务。明确展示可否审核及原因，不用前端角色判断替代服务端授权。
7. **换教室作用于具体课次。** 从未改过 `revision=0`，之后提交所见修订号；`location=null` 恢复
   原址。后续预览/生成先按有效地点分组，再合并任务；整堂共享课换地点保持任务身份。
8. **既有合并任务有明确限制。** 一条未完成任务仍包含其他独立课次且本次要改目的地时，返回 409
   和任务编号，覆盖/修订/审计全部回滚。管理员应取消原合并安排，再保存地点并按两地生成、排班。
   已完成、已取消或已有考勤的任务保留原现场快照。本次没有自动拆分受派任务的功能。
9. **不自动改私人课表。** 正式教务发布、学籍变更、教师换教室不会直接覆盖学生本地课表或云备份。
   当前换教室联动正式课次和未完成查课任务，不承诺主动微信推送或自动同步到个人课表。
10. **空课表是有效数据。** `has_backup=true` 且数组为空表示用户主动保存空课表；不能当成“没数据”
    再导入正式课表。完整快照备份以最后成功受理为准，当前不是跨设备条件版本防覆盖。
11. **原因一般选填，版本不能省略。** 更正/审核/换教室分别使用 `current_version/current_version/revision`；
    不把“备注选填”理解为其他校验可省。409 后重取当前记录、保留用户已填内容，核对后再提交。
12. **任务责任与申请分开。** 改派不等于换组；换班申请不自动免除受派责任。未来日期默认禁止提交，
    逾期补交不会消除截止时考核事实。

## 4. 微信小程序：教工新增 API 与对应页面

生产基础地址：`https://course.zsitai.xyz`。以下接口路径统一加 **`/api/v1`**。
全部使用本人 Bearer 会话，不要求小程序增加学院选择器；请求中的筛选条件只与授权范围取交集。
下表“页面”是小程序待开发映射，不表示本仓库已经实现。

### 4.1 身份和入口

| 方法 | 路径 | 功能与关键输入 | 小程序页面映射 |
| --- | --- | --- | --- |
| GET | `/me` | 旧接口扩展 `app_context`：`modes/default_mode/administrator/staff`，以及 `staff.views.teaching/responsible` | 登录后决定模式；我的→身份/工作视图 |
| POST | `/me/staff-binding` | `staff_no`、`binding_code`，核销后重新获取 `/me`；不额外要求先绑定学生 | 我的→绑定教工身份 |

`app_context.staff` 包含 `staff_id/staff_no/name/college_id/views`；其中学院是摘要，不是客户端
自选授权目标。纯教工可能同时具有旧语义的 `binding_required`，不能强制引导其绑定学生后才工作。

示例请求：`{"staff_no":"T001","binding_code":"示例一次性绑定码"}`。
码无效/不匹配、过期或已使用时分别按实际 422/409 错误提示，不凭工号直接关联账号。

### 4.2 课程、正式课次和换教室

| 方法 | 路径 | 功能与关键输入 | 小程序页面映射 |
| --- | --- | --- | --- |
| GET | `/me/teaching-occurrences` | 本人正式课次；必填 `date_from/date_to`，区间不超过 31 天；可选 `teaching_class_id/page/page_size`，每页最多 200 | 教工“课程”列表/日历 |
| GET | `/me/teaching-classes/{teaching_class_id}/occurrences/{occurrence_key}/location` | 当前覆盖、课表原地点、当前地点、`revision/affected_task_ids` | 指定课次详情→换教室前读取 |
| PATCH | 同上 `/location` | `location`、必传 `revision`、选填 `reason`；返回新修订及受影响任务 ID | 指定课次→保存/恢复教室 |

课次列表提供 `occurrence_key/teaching_class_id/semester_id/inspection_date/weekday/start_period/end_period/`
`course_names/class_names/base_location/current_location/overridden/revision/task_ids`。
`task_ids=[]` 表示没有查课任务，不表示这节课不存在。直接使用服务端课次键并 URL 编码，不能用课程名拼键。

换教室请求：`{"location":"B202","revision":0,"reason":""}`；恢复：
`{"location":null,"revision":1}`。当前列表只有节次，不能假称已返回起止时刻。

### 4.3 考勤卡片、明细、统计、历史和更正

以下列表、详情、汇总、导出接口的 **`view` 必传**：`teaching` 为本人授课，`responsible` 为本人责任班级。

| 方法 | 路径 | 功能与关键输入 | 小程序页面映射 |
| --- | --- | --- | --- |
| GET | `/me/inspection-records` | 有权查课卡片，按视图、学期、日期、课程及班级筛选；分页 | 教工“考勤”→我的授课/我的班级 |
| GET | `/me/inspection-records/{task_id}` | 指定任务卡片、当前状态、统计口径和可用动作 | 卡片详情 |
| GET | `/me/inspection-records/{task_id}/attendance` | 授权学生子集；可选 `effective_type/page/page_size`，最多 200；必须完整支持翻页 | 卡片→名单与认定 |
| GET | `/me/inspection-records/summary` | 同范围汇总与按负责学院分列 | 本人视图顶部统计 |
| GET | `/me/inspection-records/export` | 同范围 xlsx 文件流，文件名见 `Content-Disposition`，不是 JSON 成功信封 | 导出 Excel |
| POST | `/me/teaching-attendance/{record_id}/corrections` | `attendance_type/current_version`，选填 `reason`；只在有效授课和逐学生授权范围内更正 | 我的授课→更正认定 |
| GET | `/me/attendance-records/{record_id}/versions` | 必传 `view`，授课和责任视图都能读取各自可见记录的历史 | 学生明细→认定历史 |

卡片筛选还包括 `semester_id/inspection_date/date_from/date_to/teaching_class_id/`
`administrative_class_id/responsible_college_id/course_name`；不是每个筛选都需要 UI 展示。
`counts=null` 表示尚无正式考勤，不能显示“全员正常”或“全员缺勤”。

卡片中的 `allowed_actions` 决定任务操作展示；学生行包含 `attendance_record_id/current_version/`
`photo_file_ids/allowed_actions/restriction_reason`，更正按钮还需看**该学生行**的能力。

更正请求：`{"attendance_type":"NORMAL","current_version":3,"reason":""}`。
认定值为 `NORMAL/LEAVE/LATE/ABSENT`；更正返回更新后的记录与版本，不代替异议审核。

### 4.4 班主任/辅导员的责任区异议

| 方法 | 路径 | 功能与关键输入 | 小程序页面映射 |
| --- | --- | --- | --- |
| GET | `/me/responsible-objections` | 本人责任范围内异议；可选 `final_status/semester_id/administrative_class_id/page/page_size` | 考勤→责任班级异议待办 |
| GET | `/me/responsible-objections/{objection_id}` | 诉求、当前认定/版本、材料、`can_review/review_block_reason` | 异议详情 |
| POST | `/me/responsible-objections/{objection_id}/review` | `decision/current_version`，通过时给 `final_type`，`comment` 选填 | 一次审核 |

通过：`{"decision":"APPROVED","final_type":"NORMAL","current_version":4,"comment":""}`。
驳回：`{"decision":"REJECTED","current_version":4,"comment":""}`，不附 `final_type`。
当前审核状态为 `PENDING/APPROVED/REJECTED`；旧 `initial_*` 仅作历史展示，不驱动新审批流。

### 4.5 旧规划接口的替代关系

以下四个 GET **当前未实现为实际路由**，不能照早期三栏设计直接调用：

| 早期建议 | 当前接法 |
| --- | --- |
| `/me/staff-profile` | `/me.app_context.staff` 提供档案摘要；当前没有本人完整档案/任职列表接口 |
| `/me/teaching-classes` | 以 `/me/teaching-occurrences` 构建目前可用的课次列表；它不等价于独立教学班目录 |
| `/me/teaching-classes/{id}/occurrences` | 使用 `/me/teaching-occurrences?teaching_class_id=...` |
| `/me/responsible-classes` | 目前用责任视图卡片/异议筛选工作；没有独立本人责任班级目录接口 |

当前认定历史只使用上表 `/me/attendance-records/{record_id}/versions?view=...`。
不要根据旧交付消息猜测 `/me/teaching-attendance/{record_id}/versions` 等别名存在。

## 5. 微信小程序：课表、备份和通知 API

### 5.1 当前推荐接入的本地课表 + 云端完整备份

| 方法 | 路径 | 对应功能 | 关键逻辑 |
| --- | --- | --- | --- |
| GET | `/me/class-timetable` | 从已发布正式来源获取本人基准课表 | 可选 `semester_id`；未发布返回 409，不能误当成空课表 |
| GET | `/me/timetable-backup` | 读取/恢复本人该学期完整备份 | 可选 `semester_id`；区分 `has_backup=false` 与已保存空数组 |
| PUT | `/me/timetable-backup` | 完整保存本人课表快照 | `semester_id/schedule_data`；一次事务整体替换，返回 `backup_version` |
| GET | `/me/academic-notices` | 简单教务及学籍来源变化通知 | `page/page_size`；仅展示，不增加已读/忽略/自动采用 |

界面对应学生“课表”及“我的→备份/恢复、通知”。缓存按账号身份+学期隔离；有有效空课表时
仍以空课表为准。没有备份且没有有效本地内容时，才用正式来源初始化。

`PUT` 示例：`{"semester_id":"2","schedule_data":[]}`，表示保存空课表，而不是删除备份状态。
备份可以保留本地课程 ID、节次、周次、颜色和自建课程；不作为正式选课、免到、排班或统计依据。

这套备份协议当前没有必传的 `current_version`，以最后成功受理的整份快照为准。客户端同身份/学期
应串行上传，失败不能提示已备份。旧设备晚上传可能覆盖新设备，不能承诺已经防止多设备覆盖。
灵活日期、真实起止时刻仍需客户端正确透传和展示；仅有节次/周次 UI 不能无损呈现全部学院作息。

### 5.2 保留兼容的逐条云端课表 API

以下为另一套已有个人副本模型，**不是新版备份流程的必接接口**，也不与完整备份自动双向同步。
除读取可用学期与 initialize 的 body 外，其他下表操作按路由要求提供 `semester_id` 查询参数。

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/me/timetable/semesters` | 本人可用学期 |
| POST | `/me/timetable/initialize` | 按 body 中的 `semester_id`，从已发布正式来源初始化逐条个人副本 |
| GET | `/me/timetable` | 读取逐条个人副本及整表版本 |
| GET | `/me/timetable/official-source` | 只读正式来源，供主动比对 |
| POST | `/me/timetable/entries` | 新增个人课程条目 |
| PATCH | `/me/timetable/entries/{eid}` | 修改个人条目 |
| DELETE | `/me/timetable/entries/{eid}` | 删除个人条目，按 body 版本校验 |
| GET | `/me/timetable/deleted-entries` | 查看已删除条目 |
| POST | `/me/timetable/entries/{eid}/restore` | 恢复删除条目，按 body 版本校验 |
| PUT | `/me/timetable/entries/{eid}/exceptions/{day}` | 只改某一天的私人显示安排 |
| DELETE | `/me/timetable/entries/{eid}/exceptions/{day}` | 取消该日私人例外，按 body 版本校验 |

`eid` 使用这一模型的 UUID，不能将完整备份中的任意 `c_.../s_...` 本地标识直接拿来调用。
具体条目字段和版本必填见 OpenAPI 的 `EntryCreate/EntryUpdate/EntryDelete/OccurrenceEdit`。

## 6. 小程序沿用接口的新逻辑

这些是原接口或兼容扩展，不全部算新增路由。

| 接口 | 对应小程序功能 | 本次升级需要知道的规则 |
| --- | --- | --- |
| `GET /me/attendance`、`GET /attendance/{id}` | 学生本人考勤/详情 | 仍是本人记录，不新增学院选择器；`photo_file_ids` 可用于现场照片；按考勤记录 ID 展示和申诉，不能按课程名合并不同检查 |
| `POST /objections`、`GET /objections`、`GET /objections/{id}` | 学生发起/查看本人异议 | 原申诉入口保留；新审核不走初核；发起时仍校验当前考勤版本与状态 |
| `POST /objections/{id}/review` | 已有管理员小程序的一次审核兼容入口 | 需相应管理权限与范围；普通教工应使用本人责任区审核接口，不能借旧全院入口提权 |
| `GET /files/{file_id}/access` | 学生、教工及审核材料预览 | 返回短期签名 URL，文件服务新增教工范围授权；403/404/410 不能通过裸文件地址绕过 |
| `POST /files` | 志愿者照片/异议证明上传 | `wx.uploadFile`，业务请求仅传服务端文件 ID；上传也需处理 401 刷新 |
| `GET /me/inspection-tasks`、`GET /inspection-tasks/{task_id}`、`GET /inspection-tasks/{task_id}/students` | 志愿者本人任务/名单 | 仍按当前受派；教师不能通过这个提交链更正考勤 |
| `POST /inspection-tasks/{task_id}/submissions` | 志愿者现场提交 | 默认拒绝未来日期；允许逾期补交但保留截止考核事实 |
| `POST /assignment-change-requests`、`GET /me/assignment-change-requests` | 发起/查看换班申请 | 传当前 `assignment_id`，不是只看 `task_id`；申请不自动转派或免除责任 |

学生本人考勤响应保持原兼容结构。本轮不要求小程序依赖管理端的
`responsible_college_id/responsible_college_name/semester_status` 扩展字段；旧历史文档曾提出
这些字段的建议，已被后续兼容决定撤回。

### 6.1 已有代码但当前不要求小程序接入的组不可用 API

| 方法 | 路径（仍加 `/api/v1`） | 功能 | 当前状态 |
| --- | --- | --- | --- |
| GET | `/colleges/{cid}/groups/{gid}/me/unavailability` | 查看本人组内不可用申请 | 排班开关未开启 |
| POST | 同上 | 新增本人不可用申请 | 排班开关未开启 |
| POST | 同上 `/{rid}/withdraw` | 撤回本人申请 | 排班开关未开启 |

这类学院/组路径不应自动塞进当前学生/教工三栏 MVP。`/me/workspaces`、`/me/campus-runtime`
服务管理工作区与运行能力展示，也不是普通小程序新增学院选择器的要求。

## 7. 小程序页面交付范围

| 小程序区域 | 页面/组件职责 | 本次真实交付 |
| --- | --- | --- |
| 学生：课表 | 本地编辑、正式来源、完整备份/恢复、通知展示 | 后端接口已提供；本仓库副本未实现对应课表页，上游/微信包另核实 |
| 学生：考勤 | 本人考勤、现场照片、发起异议、审核结果 | 保留现有记录/申诉页，新增逻辑仍需逐项适配验收 |
| 教工：课程 | 本人正式课次，指定日期换教室 | API 已上线；小程序页面待开发 |
| 教工：考勤 | 在 `teaching/responsible` 间切换，卡片、明细、更正、历史、统计、导出、责任区审核 | API 与 Web 已上线；小程序页面待开发 |
| 我的 | 学生/教工模式、教工绑定、身份摘要、退出与缓存清理 | `/me` 扩展及绑定 API 已上线；本仓库尚无完整教工模式 UI |
| 志愿者任务 | 保留任务列表、提交与换班申请入口 | 不因三栏重排而删除或替换成教师更正入口 |

建议三栏名称仍为学生“课表/考勤/我的”、教工“课程/考勤/我的”；这是待实现设计，不能把
Web 的“我的授课”面板复制说明成已经发布了微信三栏。

## 8. 联调时最容易接错的地方

- 请求分页使用 `page/page_size`。**教工卡片列表和学生明细目前返回 `pageSize`**；正式课次日历、
  责任区异议及多数旧接口返回 `page_size`。在 API 适配层归一，不让组件猜字段。
- 普通成功响应 `{data,requestId}`；Excel 导出是文件流。`wx.downloadFile` 不沿用 JSON 解包，
  应带认证，保存文件后用 `wx.openDocument` 等能力打开，并处理过期会话。
- `/me` 摘要、卡片 `allowed_actions`、行级 `allowed_actions`、异议 `can_review` 分别消费；
  UI 能力不是服务端授权证明，权限变化后重新获取数据。
- ID 保持字符串，禁止 `Number/parseInt` 转换业务 BIGINT。日期 `YYYY-MM-DD` 是业务日，不做 UTC 平移；
  具体时间按响应时区约定显示，不能直接把 UTC 无偏移字符串当手机本地时间。
- 401 沿用小程序 JSON refresh token 流程，串行刷新且最多重试一次；Web Cookie 流程不能照搬。
- 409 区分版本过期、已结案、归档、合并任务需调整等情况，展示服务端信息；不能一律提示“重复申请”。
- 切身份/视图/账号时清掉旧名单、材料签名 URL、表单及旧请求结果；缓存至少按账号与学期隔离。
- 查询、导出、更正、审核分别重新检查范围；不使用当前学生档案替代历史名单快照。

## 9. 仍未交付或未验收的项目

1. 微信学生/教工三栏、教工绑定、正式课次、更正与审核页面及真机验收。
2. 当前没有独立本人教工完整档案、教学班目录、责任班级目录 API；上面的替代接法不能当成等价完整目录。
3. Web 教职工三类批量导入专用入口未核对到；特别是共享授课任命，现有页面提示“通过资料准备导入”
   不代表该入口已经有对应目标可选。手工本院教学班任命可用。
4. 学院作息、新组织成员/支援/不可用、组抽查、确认排班等当前未开启；不能按页面组件存在宣布可用。
5. 已有多独立课次合并任务不自动拆分；正式课次列表未补起止时刻；无微信主动推送承诺。
6. 三个浏览器业务闭环留给用户验收。迁移升降级和两条 MySQL 迁移回归已通过；绑定码、导入确认、
   名单归属、地点与生成、更正与审核的真实 MySQL 并发仍未完成专项验收。

## 10. 开发核对入口

- API 契约（原相对路径：`../API_CONTRACT.md`）、API 索引（原相对路径：`../API_INDEX.md`）、OpenAPI（原相对路径：`../openapi.json`）。
- 教工三栏历史设计（原相对路径：`../integration/WECHAT_STAFF_THREE_TAB_PLAN_20261017.md`）：界面意图参考，实际路由以本文和代码为准。
- 本地个人课表与云端备份契约（原相对路径：`../integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md`）。
- 学生原接口兼容决定（原相对路径：`../integration/WECHAT_API_CHANGES_20261016.md`）。
- Web 路由/入口：`apps/admin-web/src/navigation/workspaceNavigation.ts`、`src/views/`。
- 教工后端：identity 的 `staff_deps`/绑定服务，inspection 的 `staff_record_router`，academic 的
  `staff_router/occurrence_location_router`，attendance/objection 的 `staff_router`。
- 私人课表后端：`backend/app/modules/timetable/router.py`；通知与正式来源：academic publication 模块。

本清单整理产生独立文件，没有改动其他任务在途的 README、docs/README 与 FUNCTIONAL_GUIDE。
