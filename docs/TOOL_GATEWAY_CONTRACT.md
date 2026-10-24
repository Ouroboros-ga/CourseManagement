# 工具网关合同 v1

日期：2026-10-24。状态：本地候选实现，默认关闭；未联调腾讯云、未生产启用。

## 入口与身份

- HTTP：`POST /api/v1/agent-tools/v1/calls/{tool_name}`，body 为 `{"arguments": {...}}`。
- MCP：`/mcp/agent-tools`，Streamable HTTP，JSON 响应、无业务会话状态。
- 两种入口均要求 `X-Tool-App-Key` 和 `X-Agent-Run-Token`；它们来自受保护的应用配置与后端运行记录，不能由模型提供身份字段替代。
- 仅 `AGENT_TOOLS_ENABLED=true` 才挂载 HTTP；MCP 还需 `AGENT_MCP_ENABLED=true`。配置参见 `backend/.env.example`。
- 应用配置字段：app_key_id、key_digest（原始应用密钥的 SHA-256 摘要）、entry_kind（MANAGEMENT／SELF_SERVICE／AUTOMATION）、environment（必须与 APP_ENV 一致）。AUTOMATION另须workflow_kind="change"或"objection"，其他入口不得配置workflow_kind。每个应用使用独立密钥；凭据不得记录到日志。
- 运行记录由内部 `RunService.issue` 使用已验证的用户和会话创建；原始运行凭据只交给后端调用腾讯云的适配层，不提供公网签发接口和前端 token 返回接口。

MANAGEMENT 运行必须绑定可访问学院；SELF_SERVICE 不接受管理学院范围。工具执行时仍调用原身份和业务权限服务。学生负责人使用已有学院／责任区能力，不从角色名称推导全学院权限。

## 已注册工具

| 名称 | 入口 | 输入与输出 |
| --- | --- | --- |
| system_probe | 两组 | 空参数，返回固定 contract_version；同样需要运行身份 |
| task_status_get | 两组 | task_id；只查询当前运行创建的任务，重新检查原有访问范围 |
| report_attendance_summary | MANAGEMENT | 学期字符串 ID＋周次或完整日期范围；返回现有统计总数，不返回人员明细 |
| report_attendance_export_prepare | MANAGEMENT | 与汇总相同的时间窗＋固定format；准备需要当前登录的下载操作，不生成文件或返回明细 |
| responsibility_tasks_list | MANAGEMENT | 学期字符串 ID、周次、分页；复用 ScopedInspectionService 的当前责任区过滤 |
| self_attendance_list | SELF_SERVICE | 分页、可选 task_id 和考勤类型；仅本人记录 |
| self_timetable_get | SELF_SERVICE | 学期字符串 ID；只读已保存副本，不初始化 |
| change_prepare | AUTOMATION/change | 空参数；仅为本次运行绑定的申请准备安全换班方案，无候选返回MANUAL_REQUIRED |
| change_apply | AUTOMATION/change | 空参数；复核策略和运行后实际改派，重复调用返回原回执 |

另有AUTOMATION/objection的3个工具：`objection_case_get`空参数、`objection_material_access`仅file_id、`objection_precheck_save`仅严格result建议对象。后台从绑定恢复申诉与批次，参数不得指定学院、账号或申诉；不改正式考勤或人工审核。独立合同见[预审工具OpenAPI](agent-objection-tools.openapi.json)，身份、保存幂等回执和验收边界见[预审运行接入](development/OBJECTION_PRECHECK_RUNTIME_20261024.md)。

尚未注册导入保存、周期排班发布工具。统计报表新增导出准备工具，返回NOT_GENERATED及固定同源下载操作；实际生成仍在原REST下载边界重新鉴权，管理助手下载卡待接入。详见[导出准备](development/AGENT_REPORT_EXPORT_20261024.md)。AUTOMATION只允许change和objection两种独立绑定；未绑定工作流或未知流程不暴露工具。交互助手现有7个工具，不能调用这些后台工具。[换班工作流OpenAPI](agent-change-tools.openapi.json)保持独立2个工具。预审工具本地可用不等于真实ADP预审已接入。

分页上限50条；外部 ID 必须是规范十进制字符串，范围为1到2^63−1。统计日期区间最多93天；周次与日期区间二选一。额外字段（包括 user_id、student_id、role、college_id）拒绝，不做静默忽略。

请求体上限256 KiB，实际工具结果上限128 KiB；过大查询需分页或缩小范围。文件上传、任意 URL 下载、SQL、shell 均不属于工具能力。

## 响应与错误

HTTP 沿项目实际成功格式 `{data, requestId}`；data 包含 status、data、task_id、result_ref、error_code、retryable、trace_id。当前只读查询成功返回 SUCCEEDED；task_status_get 的 data.status 才是被查任务的实际状态。

应用密钥无效401；运行失效403或原身份服务的401；隐藏工具404；参数／结果过大422；请求体过大413；原业务错误沿既有状态码。MCP 的已调用业务错误使用 isError 和结构化错误，协议畸形由 SDK 处理。

调用日志仅记录工具名、运行编号、trace_id 和结果状态，不记录 Header、参数全文或证明材料。默认不公开整个业务 OpenAPI；专用合同为 [agent-tools.openapi.json](agent-tools.openapi.json)。

## 生命周期与验证边界

运行凭据初始10分钟；后端可在真实会话有效时调用 rotate，旧值立即失效。每次调用重新验证会话和账号；学院／责任区撤权由原业务服务检查。客户端关闭页面不等于撤销身份，退出登录后会话派生运行失效。

本地验证包含 SQLite 行为、HTTP TestClient 和真实 Uvicorn MCP 网络测试。它们不证明真实 MySQL 锁行为、腾讯云 Header 动态绑定、外部 HTTPS 或实际云端工作流已验收。

后台任务和正式写入完成前不开放相关工具，不将只读阶段标为整个实施计划完成。

## 持久任务增量

任务表迁移为 `f26a1024a002`，依赖运行表迁移。登录API提供POST创建任务、GET本人任务状态、POST取消；HTTP地址与行为详见[运行手册](RUNBOOK_TOOL_GATEWAY.md)。任务接口不签发或返回运行token。

提交登记只flush，由入口或父业务提交，支持与源事件同事务。Worker领取后才进入RUNNING，租约／尝试令牌控制结果发布；同请求返回原任务，不同参数409。最多3次暂时故障重试，每次运行默认最多100个待处理任务；超限429。

当前Worker只处理只读工具；token到期不取消有效队列任务，但会话／账号／应用／运行仍需有效。任务结果读取重新检查现有范围，不能因已有结果绕过撤权。完整ADP等待与对账、重文件执行隔离、周期任务和自动换班仍未接通。

## 自动换班领域候选（尚未注册智能体工具）

迁移`f26a1024a003`新增策略及执行回执。登录管理接口为`GET/PUT /api/v1/colleges/{cid}/groups/{gid}/inspection/auto-change-policy`，复用原排班管理和换班审核权限；具体请求见[API契约](API_CONTRACT.md)。`AGENT_AUTO_CHANGE_ENABLED`默认关闭。

开启后仅对新建申请登记QUEUED执行记录，登记与原申请同事务。领域服务已支持准备方案和实际改派，并保留系统执行来源及策略授权人。[管理页面](development/AUTO_CHANGE_POLICY_UI_20261024.md)已接通策略接口并进行模拟交互验证。

`RunService.issue_change`仅供可信派发器内部调用，绑定一个执行记录，使用实际申请人账号，source_session_id为空，不创建在线会话。一个执行记录最多一个运行，重新签发轮换原凭据；只flush，由派发事务提交。网关恢复策略授权人的当前业务权限，工具参数不能指定其他申请、志愿者或操作者；运行凭据到期、撤销、轮换或绑定变化会在执行前再次拒绝。

后台换班身份迁移为`f26a1024a004`；当前完整候选升级至`f26a1024a009`，另含云实例追踪、源环境来源、独立申诉预审领域记录和专用预审身份。存在后台运行、追踪或确认来源时，相关降级拒绝删除历史。HTTP与MCP本地调用均已验证，包括重复回执与无候选转人工。[换班派发](development/ADP_CHANGE_DISPATCH_20261024.md)和[预审派发](development/ADP_OBJECTION_DISPATCH_20261024.md)共用持久云实例生命周期，均为本地模拟验证；消费者未启动，真实ADP及MySQL迁移和竞争仍待验收，不把工具可调用等同于自动任务已从云端运行。
