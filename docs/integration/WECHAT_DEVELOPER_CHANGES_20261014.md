# 微信小程序开发者：功能与接口变化清单

日期：2026-10-14。主系统为 `Ouroboros-ga/CourseManagement` 的 `dev-main`；小程序上游为 `Mo-Qiong/wxsign` 的 `main`。本次已独立拉取并审查上游 `6d26b4f66ced71f3dec32ccf66eb8c81c445970a`（含 `4033ebb` 换班功能与 `6d26b4f` UI 优化），相对上次 `d0a48a0c4a3dcef59fdb11698d6d45d402c1dd9f` 共七个文件变化。

生产基础地址：`https://course.zsitai.xyz`。本清单用于人工交给小程序开发者；本次没有向小程序上游推送或发布微信版本。详细 schema 见主项目 `docs/openapi.json`；以这里的业务边界及后端契约一起判断，不能把旧测试或旧 UI 当现行业务要求。

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

- BIGINT ID 必须保持字符串。上游提交照片 `file_ids` 和异常学生 `student_id` 仍使用 `map(Number)/Number(...)`，申请历史排序也使用 `Number(id)`，应全面修复；选择顺序可按服务端排序或十进制字符串长度/字典序，不做浮点转换。
- 日历日期 `YYYY-MM-DD` 是教学业务日期，不做 UTC 平移。无偏移 datetime 按后端 UTC 约定转换为 `Asia/Shanghai`；显式偏移只转换一次。最新上游截止/取消时间仍直接 `new Date(UTC-naive)`，手机时区不同会误显。前端日期禁提交是提示，最终以服务器判定为准；允许逾期补交，不允许提前提交。
- 成功信封为 `{data,requestId}`，分页字段为 `page_size`；错误使用 `code/message`，保留 `requestId` 便于排查。409 分清 `VERSION_CONFLICT/STATE_CONFLICT`，不要将所有状态冲突都说成“重复换班申请”。
- 小程序仍使用 Bearer access token；refresh 是 JSON `refresh_token`，不是 Web Cookie。普通请求已有串行刷新及一次重试；`utils/upload.js` 独立上传尚无 401 刷新协同，且 `JSON.parse` 未捕获，过期 token/异常网关响应可能导致失败或挂起。应共用会话更新逻辑但仍用 `wx.uploadFile`。
- 提交照片类别 `SUBMISSION_PHOTO`，异议证明 `OBJECTION_PROOF`；业务提交只传服务端文件 ID。签名访问与下载适用于 local/OSS，同一个后端契约；不得把 OSS 桶改成公共或在小程序放访问密钥。服务器是否启用 OSS 由受控预检决定，不由小程序猜测。
- 当前上游列表默认只取第一页，个人考勤/异议及换班历史需要分页加载。现有 Node 用例还存在导出命名/旧 VM 夹具不匹配及真实功能失败，不能以旧测试总数推断功能已通过。

## 5. 学院升级本次不会要求小程序立即改学院接口

统一后端包含学院配置及归属底座，但 `CAMPUS_CONFIGURATION_ENABLED`、`CAMPUS_ACADEMIC_SCOPED_ENABLED` 保持关闭；尚未完成全链路隔离、灵活作息和组织排班，旧小程序主要业务 URL 保留。不要提前调用 `/colleges/{cid}/...` 代替本人接口，或让客户端任意传学院 ID 扩大权限。

个人可编辑课表仍是产品需求，尚无本次可调用的完整接口；不应把个人课表接入查课、考勤、免到或排班。后续启用多学院时另行发布完整契约及双学院验收清单。

## 6. 交付验收清单

1. 微信开发者工具 npm 构建与真实登录；access 过期并发请求只刷新一次，上传过期也能恢复，刷新失败退出。
2. 普通学生/正常出勤/异常出勤现场照片：本人可看，多图预览；他人 404、已清理 410、空数组、过期链接和切换账号缓存均正确。
3. 管理员及负责人一次审核：不同改判、驳回、可选备注、无权限隐藏操作、409不覆盖；历史初核只显示历史，不再调用初核写接口；审核人账号正确。
4. 换班申请：原因空值、待审继续执行原任务、驳回重申请、申请通过但尚未改派、实际改派后的任务消失或权限变化；不同受派记录不能被旧申请误匹配。
5. BIGINT ID `9007199254740993` 从选择、上传、提交、列表到预览保持完整；北京时间凌晨/跨日显示正确；未来禁止提交、逾期允许补交。
6. 分页超过默认页大小不漏考勤、异议或申请；页面网络错误不显示成功或错误清空状态。

本次同步新增两个定向用例通过；全量 Node 运行 39 项：8 passed、30 failed、1 cancelled，与同步前既有失败/取消数量一致。未执行微信开发者工具、真机或上游发布，开发者应根据失败根因修复接口测试及页面测试，不能删除用例或放宽门禁制造全绿。
