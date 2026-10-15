> **当前线上状态（2026-10-16）：** 本人考勤照片、云端个人课表与正式来源接口已部署；管理侧学院隔离/组织排班增量也已部署，但相应生产开关待存量数据确认。小程序不承担管理页面开发。历史批次的未部署说明不代表当前状态。

> **2026-10-16 已部署接口补充**：本人考勤 `task` 新增可空的 `responsible_college_id`、`responsible_college_name`、`semester_status`。同一学生同一课程可有不同负责学院的独立检查记录，请逐条展示并按具体考勤 ID 发起异议，不按课程名/日期合并或覆盖。任务简报可展示“检查负责学院”；旧响应缺字段时兼容显示。`semester_status=ARCHIVED` 时不再提供新异议操作，服务端亦会返回 409；归档后合法纠错由授权教师通过 Web 处理。照片仍沿该考勤所属任务授权访问。学院配置、作息、组织、排班和共享身份管理仍不属于小程序前端开发任务。个人课表交接继续使用下方独立文档。
>
> 以上是新增兼容字段与业务提示，不代表当前线上已返回；以下 2026-10-14/15 原交付记录保留原发布语境。

> 2026-10-15 新增交付：[云端个人课表与简单通知接口](WECHAT_PERSONAL_TIMETABLE_API_20261015.md)。下面是 10月14日历史清单，个人课表现已单独实现，不能再按“未提供”理解。

# 微信小程序开发者：功能与接口变化清单

日期：2026-10-14。主系统为 `Ouroboros-ga/CourseManagement` 的 `dev-main`；小程序上游为 `Mo-Qiong/wxsign` 的 `main`。本次已独立拉取并审查上游 `6d26b4f66ced71f3dec32ccf66eb8c81c445970a`（含 `4033ebb` 换班功能与 `6d26b4f` UI 优化），相对上次 `d0a48a0c4a3dcef59fdb11698d6d45d402c1dd9f` 共七个文件变化。

生产基础地址：`https://course.zsitai.xyz`。本清单用于人工交给小程序开发者；本次没有向小程序上游推送或发布微信版本。详细 schema 见主项目 `docs/openapi.json`；以这里的业务边界及后端契约一起判断，不能把旧测试或旧 UI 当现行业务要求。

**交接范围**：只列小程序现有业务需要适配的功能、接口和客户端问题。下表中的后端能力已在本次同步发布中提供；状态及测试数字均为 2026-10-14 本次同步的记录，后续发布需重新核验。

| 小程序业务 | 后端状态 | 小程序开发事项 |
| --- | --- | --- |
| 学生查看考勤现场照片 | 照片 ID 返回、本人授权和签名访问已实现 | 展示照片、申请预览链接、处理失效与账号缓存 |
| 学生异议及管理审核 | 一次审核、审核人信息和版本校验已实现 | 移除初核回退，适配审核状态、证据与审核人展示 |
| 志愿者换班申请 | 申请、本人分页查询及当前受派状态接口已提供 | 核对申请与受派关系、分页及申请不免除任务责任的语义 |
| 登录、上传和通用数据处理 | 沿用当前身份、文件与分页契约 | 修复上传刷新、字符串 ID、时间显示和错误处理 |

学院隔离、作息计算、组成员管理、范围抽查和排班由后端与 Web 实现，不属于本清单的开发任务，也不作为上述小程序适配的前置条件。个人可编辑课表是独立的新功能，不属于本次交接范围。

## 1. 必须配套：学生考勤现场照片

**后端已实现**：`GET /api/v1/me/attendance` 每条记录新增 `photo_file_ids: string[]`；管理列表及 `/attendance/{id}` 也有同字段。现场照片来自任务已审核通过的志愿者提交，与学生申诉证明不同。正常出勤也能关联；无照片为 `[]`。过期照片仍保留 ID，但访问会返回明确错误。

脱敏结构示例（所有 ID 都是字符串）：

```json
{"data":{"items":[{"id":"101","task_id":"201","effective_type":"LATE","current_version":1,"photo_file_ids":["301","302"],"task":{"task_id":"201","inspection_date":"2026-10-14","inspection_type":"COURSE","course_name_snapshot":"示例课程"}}],"page":1,"page_size":20,"total":1},"requestId":"example"}
```

**小程序待实现**：在考勤详情展示“查课现场照片”，逐个请求 `GET /api/v1/files/{id}/access`，再用响应的 `data.url` 展示缩略图及 `wx.previewImage`。相对 URL 用生产基础地址补齐，不使用 object_key 或自行拼下载地址。

```json
{"data":{"url":"/api/v1/files/301/download?expires=EXAMPLE&sig=EXAMPLE","method":"GET","expires_in":300,"expires_at":"2026-10-14T04:35:00"},"requestId":"example"}
```

示例 TTL 仅示意，缓存必须按真实 `expires_in/expires_at` 并留提前量。缓存键至少包含当前账号与文件 ID；退出、解绑、切换账号清理。链接过期重新申请；403/404 展示无权限/不可见，410 `FILE_EXPIRED` 展示“材料已过保留期”，不无限重试或用旧 URL 绕过授权。原始链接有效期内不即时撤销，不能把前端清缓存当服务端撤销。

**权限**：本人正式考勤 + 有效学生绑定 + 有效账号 + `attendance.read`；不能查看其他学生不属于本人的任务材料。上游该版本没有 `photo_file_ids` 消费或授权文件 API 封装，不能宣称自动显示已就绪。

## 2. 必须配套：异议改为一次审核

| 接口/字段 | 变化及开发要求 |
| --- | --- |
| `POST /api/v1/objections/{id}/review` | 当前推荐一次审核入口，权限仍为 `objection.final_review` |
| `/objections/{id}/final-review` | 兼容旧调用的别名，仍可用；新开发统一使用 `/review` |
| `/objections/{id}/initial-review` | 废弃且拒绝写入；不要再提供初核按钮或把无终审权限回退为初核 |
| `final_status` | 当前业务状态为 `PENDING/APPROVED/REJECTED`，UI 对应待审核/通过/驳回 |
| `initial_*` | 仅展示历史，可折叠标为历史初核，不驱动当前待办、审批流或通过状态 |
| `final_reviewed_username/display_name` | 新增审核账号/名称，展示操作人，缺失时合理降级，避免只显示数字 UID |
| `attendance.current_version` | 提交用当前所见考勤版本；409 不强行覆盖，刷新并提示事实已变化 |

同意示例：

```json
{"decision":"APPROVED","final_type":"NORMAL","current_version":1,"comment":""}
```

驳回：`{"decision":"REJECTED","current_version":1,"comment":""}`。意见选填，不在前端强制填写。审核支持 `NORMAL/LEAVE/LATE/ABSENT`，允许维持原判；学生诉求只作提示，不替代管理员决定。学生负责人及以上默认具备一次审核权限，以最新 `/me.permissions` 为准，不能仅按角色名放行。审核更正由后端同事务更新考勤版本和审计，前端不额外调用考勤更正接口。

**上游现存问题**：`api/admin.js` 和 `pages/admin/index.js` 仍有初核回退；驳回理由仍强制填写；同意固定 `NORMAL`；列表模板读取 `proofs`，而后端提供 `file_ids/files`，没有对应签名 URL 装配；审批账号和当前审核文案也需补齐。

## 3. 换班申请：上游已有 UI，需要核对业务语义

| 请求 | 参数/返回 |
| --- | --- |
| `POST /api/v1/assignment-change-requests` | `assignment_id` 为当前受派 ID，`reason` 选填，示例 `{"assignment_id":"401","reason":""}` |
| `GET /api/v1/me/assignment-change-requests` | 分页 `page/page_size`，返回 `items,total,page,page_size`，每项有 `id,assignment_id,task_id,status,reason,comment,processed_at` |
| 任务的 `assignment` 简报 | 含当前受派关系及 `change_request_status/reason/comment`，优先用于当前任务操作状态 |

旧错误路径 `/api/v1/inspection/assignment-change-requests` 不存在。申请状态 `PENDING/APPROVED/REJECTED` 与任务执行状态是两个维度：**申请中仍承担原任务，不自动转交或免除截止责任；通过申请也不代表已完成管理员改派**。禁止前端据申请历史把正式任务强行锁成不可提交。用户已改派/受派撤销后，以后端任务访问和当前 assignment 为准。

本地同步保留未来日期禁提交和当前换班 dialog，兼容上游函数别名，修复申请 ID 的 `Number` 精度截断。最新上游的申请 UI/反馈已合并，但以下项仍需开发者完成：按当前 `assignment_id` 匹配申请而不只按 `task_id`，处理超过第一页的历史申请；避免把列表查询失败默认为“无申请”；换班原因选填；待办/逾期/取消分类不能由申请状态覆盖正式任务状态。

## 4. 通用接口规则及现存缺口

**当前测试服务器临时例外**：用户另会话要求只在服务器关闭提前提交限制，`CM_DEV_ALLOW_EARLY_SUBMISSION=1` 已生效；这段补丁不进入本地/远端 Git，不是正式业务契约变化。小程序客户端日期门禁保持不变，所以直接调用测试后端和通过小程序 UI 可能表现不同。正式发布/测试结束恢复后，未来日期仍拒绝。不要据临时测试结果删除客户端日期提示或改写正式产品规则。

- BIGINT ID 必须保持字符串。上游提交照片 `file_ids` 和异常学生 `student_id` 仍使用 `map(Number)/Number(...)`，申请历史排序也使用 `Number(id)`，应全面修复；选择顺序可按服务端排序或十进制字符串长度/字典序，不做浮点转换。
- 日历日期 `YYYY-MM-DD` 是教学业务日期，不做 UTC 平移。无偏移 datetime 按后端 UTC 约定转换为 `Asia/Shanghai`；显式偏移只转换一次。最新上游截止/取消时间仍直接 `new Date(UTC-naive)`，手机时区不同会误显。前端日期禁提交是提示，最终以服务器判定为准；允许逾期补交，不允许提前提交。
- 成功信封为 `{data,requestId}`，分页字段为 `page_size`；错误使用 `code/message`，保留 `requestId` 便于排查。409 分清 `VERSION_CONFLICT/STATE_CONFLICT`，不要将所有状态冲突都说成“重复换班申请”。
- 小程序仍使用 Bearer access token；refresh 是 JSON `refresh_token`，不是 Web Cookie。普通请求已有串行刷新及一次重试；`utils/upload.js` 独立上传尚无 401 刷新协同，且 `JSON.parse` 未捕获，过期 token/异常网关响应可能导致失败或挂起。应共用会话更新逻辑但仍用 `wx.uploadFile`。
- 提交照片类别 `SUBMISSION_PHOTO`，异议证明 `OBJECTION_PROOF`；业务提交只传服务端文件 ID。签名访问与下载适用于 local/OSS，同一个后端契约；不得把 OSS 桶改成公共或在小程序放访问密钥。服务器是否启用 OSS 由受控预检决定，不由小程序猜测。
- 当前上游列表默认只取第一页，个人考勤/异议及换班历史需要分页加载。现有 Node 用例还存在导出命名/旧 VM 夹具不匹配及真实功能失败，不能以旧测试总数推断功能已通过。

## 5. 后台升级对现有小程序的适配边界

本次沿用现有学生、志愿者本人业务接口，不要求新增学院选择、组成员管理、抽查配置或排班页面，也不要提前调用 `/colleges/{cid}/...` 代替本人接口。学院数据范围由后端根据登录身份授权，客户端不能通过任意传学院 ID 扩大权限。

小程序任务展示应使用后端返回的具体日期和时间，避免写死普通课或早晚自习的时间；课程冲突判断、抽查范围和排班算法由后端执行。后台后续升级只有实际改变小程序字段、请求参数、身份上下文或错误码时，才另行发布接口适配清单。

### 5.1 个人课表：2026-10-14 最终确认云端保存

最新用户确认取代此前本地保存方案：本人增删改保存云端，以最后成功保存为准；个人副本不参与查课、考勤、免到或排班。以下接口已在开发工作树实现并经局部回归，默认关闭教务发布模式，未部署。小程序页面仍由小程序开发者实现。

| 请求（前缀 `/api/v1`） | 小程序接入职责 |
| --- | --- |
| GET `/me/timetable/semesters` | 查询本人相关学期与是否已初始化 |
| POST `/me/timetable/initialize` | 请求 semester_id 字符串；按本人＋学期幂等初始化已发布正式资料，不覆盖既有副本，删空也不重新填充 |
| GET `/me/timetable?semester_id=...` | 读取本人云端内容及 current_version |
| POST `/me/timetable/entries?semester_id=...` | 新增本人课程，提交 current_version 和课程名称、星期、周次、本地起止时刻等 |
| PATCH `/me/timetable/entries/{eid}?semester_id=...` | 修改本人课程；携带 current_version，409 后刷新而非覆盖他设备保存 |
| DELETE `/me/timetable/entries/{eid}?semester_id=...&current_version=...` | 删除本人课程，以后端成功结果更新显示 |
| GET `/me/academic-notices` | 分页展示教务发布变更通知；没有已读、未读、忽略、采用或主动推送状态，不自动修改个人副本 |

正式共同课及本人正式选修按课程名单投影，不复制全班所有选修。课程条目的 occurrence_dates 是实际课次日期；同一来源课程因学院作息变更可分成多个时间段，应使用条目 id 区分个人编辑，不能只以 source_schedule_id 去重。source_schedule_id 等来源标识不可经个人编辑伪造。绑定完成/进入新学期后可调用幂等初始化；后端绑定和发布自动初始化联动仍须补全验收，不能把显式接口写成已经完成自动联动。

### 5.2 任务展示新增兼容字段

任务可增加 activity_start_at/activity_end_at（UTC 带 Z）、time_snapshot、课程类型/组名称快照及字符串 ID。优先按真实时刻展示，日历日期不做时区平移；旧历史返回 null 时不要用当前学院作息补造。小程序不需要增加学院配置、组成员管理、抽查或排班页面，继续使用本人任务/考勤接口。当前增量未上线，不提前依赖必填新字段。

## 6. 交付验收清单

1. 微信开发者工具 npm 构建与真实登录；access 过期并发请求只刷新一次，上传过期也能恢复，刷新失败退出。
2. 普通学生/正常出勤/异常出勤现场照片：本人可看，多图预览；他人 404、已清理 410、空数组、过期链接和切换账号缓存均正确。
3. 管理员及负责人一次审核：不同改判、驳回、可选备注、无权限隐藏操作、409不覆盖；历史初核只显示历史，不再调用初核写接口；审核人账号正确。
4. 换班申请：原因空值、待审继续执行原任务、驳回重申请、申请通过但尚未改派、实际改派后的任务消失或权限变化；不同受派记录不能被旧申请误匹配。
5. BIGINT ID `9007199254740993` 从选择、上传、提交、列表到预览保持完整；北京时间凌晨/跨日显示正确；未来禁止提交、逾期允许补交。
6. 分页超过默认页大小不漏考勤、异议或申请；页面网络错误不显示成功或错误清空状态。

本次同步新增两个定向用例通过；全量 Node 运行 39 项：8 passed、30 failed、1 cancelled，与同步前既有失败/取消数量一致。未执行微信开发者工具、真机或上游发布，开发者应根据失败根因修复接口测试及页面测试，不能删除用例或放宽门禁制造全绿。


### 2026-10-16 远端并行增量整合

新增 `GET /api/v1/me/timetable/official-source?semester_id=...`，返回最新已发布、本人可见的教务来源（AVAILABLE / NO_ENROLLMENT / NOT_PUBLISHED、source_revision、sources、entries），供小程序与本人云端副本对比。此查询不覆盖个人修改、不自动采用更新，不要求新增已读/未读状态。私人课表条目另已支持自定义节次和颜色；其内容仍不参与正式查课业务。
