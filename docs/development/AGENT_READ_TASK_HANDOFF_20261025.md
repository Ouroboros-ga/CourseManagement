# 云端助手提交读取任务与页面交接

日期：2026-10-25。分支：`future/agent-dev`。本地候选，未部署，未在腾讯云实际应用联调。

## 补齐的断点

原 MANAGEMENT 工具能直接核对资料、准备报表，但直接调用没有可供页面恢复的持久任务编号。新增 `read_task_submit`，让受信工作流用当前运行身份登记现有只读作业，返回任务编号及固定页面入口。继续使用原 `AgentTask`、`AgentJob`、`TaskService`、Worker、状态接口和核对／报表卡，不建立第二套调度器或权限规则。

仅允许两个目标工具：

| tool_name | arguments | 页面 |
| --- | --- | --- |
| report_attendance_export_prepare | 原 ReportExportQuery：学期、周次／完整日期范围、固定格式 | `/dashboard/reports?assistant_task_id=<id>` |
| import_preview_review | 原 ImportReviewQuery：1—100个不同的预览编号字符串 | `/dashboard/academic?tab=imports&assistant_task_id=<id>` |

输入示例：

```json
{
  "tool_name": "report_attendance_export_prepare",
  "arguments": {"semester_id": "20", "week_no": 7, "format": "ANALYTICS_XLSX"},
  "request_key": "report-week7"
}
```

HTTP 仍使用 `POST /api/v1/agent-tools/v1/calls/read_task_submit`，body 为 `{"arguments": 上面的输入}`；MCP `tools/call` 使用相同工具参数。应用密钥和运行凭据通过原受控 Header 传递，不放入参数、提示词或浏览器。

## 工作流中的状态含义

1. 已有可信运行绑定实际用户、来源会话、学院及学期；管理工作流理解请求后，仅生成允许的业务参数。
2. 调用 `read_task_submit`。后端从运行记录确定操作者和会话，复用原入队授权、幂等及容量控制。
3. 返回 `kind=TASK_HANDOFF`、`task_id`、实际 `task_status`、固定相对 `open_path`，以及登录和未应用正式业务数据的标志。提交工具本身的外层 `SUCCEEDED` 表示登记／重放成功，不表示作业已经完成。
4. `QUEUED`／`RUNNING` 仍显示处理中；通过原 `task_status_get` 或页面登录接口查询。`FAILED`／`CANCELED` 不能当成成功；任务完成后继续显示领域结果。
5. 报表页面仍由本人点击才生成并下载文件；资料核对页面重新检查当前资料，并由本人确认保存。工作流不能自动点击保存或终审。

`open_path` 由服务端根据目标工具和数据库任务编号构造，不接收模型自选路径。后续对话渲染器应使用当前业务上下文和已验证的任务类型展示此操作；当前真实管理助手会话、页面链接分发尚未接通。

## 重试、权限与调度

- `request_key` 为1—32位字母、数字、下划线或连字符。后端添加当前真实运行编号作为命名空间，沿用原大小写归一化。同一运行、同键、同规范化参数复用原任务；参数变化409。不同运行可以使用相同简短键。
- 资料预览编号是集合语义，校验互异和 BIGINT 范围后按数值排序；只改变编号顺序不会被误判成另一份任务。
- 重放返回当前真实任务状态，包括已完成、失败或取消，不重新排队已完成作业。超时重试应复用原键；需要一次新的业务读取时才使用新键。
- 学院、用户、角色、运行编号均不能由工具参数覆盖。应用或来源会话撤销会阻止调用；入队检查原动作范围，执行和结果读取继续复核当前权限。各资料类型、预览归属及业务有效性仍在目标工具执行时最终校验，登记成功不保证预览可保存。
- 每个运行的现有待处理上限继续生效（默认100）；超出429。`read_task_submit` 与 `task_status_get` 自身不进入 Worker 队列，避免递归创建和无意义状态查询作业。
- SELF_SERVICE 及两个 AUTOMATION 工作流不暴露此提交工具。换班、申诉终审、任意工具名、SQL、URL或写入操作不在目标枚举内。

## 验证与剩余门禁

新增22项测试与网关／任务／身份／报表／资料预览／合同相关回归合计115项通过；变更 Python 文件 ruff、5个相关源码文件定向 mypy 通过。隔离 SQLite 和合成身份验证两类实际作业、Worker 完成、固定页面入口、状态查询、幂等／冲突／跨运行键、资料集合顺序、参数和身份拒绝、容量及权限撤销。HTTP 使用实际运行凭据；MCP 使用本地真实 Uvicorn 网络请求验证嵌套严格参数与队列登记。小型 OpenAPI 合同同步导出，嵌套 union 无未解析 `$ref`。以上不代表全仓或腾讯云实际验收。

管理助手登录／持久会话和[任务操作侧栏](AGENT_MANAGEMENT_CHAT_UI_20261025.md)已有后续本地候选。真实腾讯云工作流、动态 Header 绑定／脱敏及真实 MySQL 并发与迁移门禁仍未完成。这里没有以本地固定规则代替自然语言智能体，也没有启动消费者、调用腾讯云、申请云资源或启用生产配置。
