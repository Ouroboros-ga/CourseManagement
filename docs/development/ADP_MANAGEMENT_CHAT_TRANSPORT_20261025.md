# 腾讯云管理交互：新版对话传输适配

日期：2026-10-25。分支：`future/agent-dev`。本地协议候选，尚未接入真实登录会话、管理端对话页面或腾讯云应用。

## 接口依据与用途

本轮重新核对[腾讯云对话 HTTP SSE 官方文档](https://cloud.tencent.com/document/product/1759/129202)（页面标注2026-09-18更新）。交互侧使用固定 `https://wss.lke.cloud.tencent.com/adp/v2/chat`，与现有后台 `CreateWorkflowRun` 是不同接口。本文只实现前者的受控出站适配，不改变自动换班／申诉预审派发器。

新增 `AdpChatClient`，接收服务端生成的会话、请求和匿名用户标识，以及服务端运行凭据。问题文本进入文本内容；运行凭据通过单独的 `custom_variables` 内容传入 `agent_run_token`，用于平台配置的 `API.agent_run_token` 变量。配置中的应用 AppKey 只进入官方请求体，不进入用户文本或返回值。这个参数能力并不证明模型隔离、日志脱敏或逐次工具 Header 映射已经实测成功。

## 部署配置与门禁

新增可空 `AGENT_MANAGEMENT_CHAT_CONFIG`，默认 `null`，字段为：

| 字段 | 含义 |
| --- | --- |
| app_key | 已发布交互应用的 AppKey，受保护配置中的 SecretStr |
| tool_app_key_id | 本环境已有 MANAGEMENT 工具连接标识 |
| header_binding_verified | 默认false；须完成真实动态 Header／日志隔离验收后才可设true |
| timeout_seconds | 默认30，范围大于0且不超过60秒 |

配置工厂要求原 `AGENT_TOOLS_ENABLED`、`AGENT_ADP_ENABLED` 同时开启，有配置且存在同环境 MANAGEMENT 连接，并通过 Header 验收门禁。没有绑定到 SELF_SERVICE 或 AUTOMATION 的隐式回退。当前实际读取结果为两开关均false、管理交互配置为空；未启用消费者或云端调用。

## 返回处理

- 按 SSE 帧读取，处理网络分块、UTF-8分割、CRLF、注释与事件边界。
- 仅从唯一成功的 `response.completed` 中提取 `reply` 消息的文本内容，核对会话和 assistant 角色。不将中间 delta／replace 当作最终结论；最终内容可覆盖早期草稿。
- 不返回 thought、procedure、知识检索内部数据、任意 Widget／脚本、文件或链接组件。返回只是文本和本地请求／远端会话关联标识，不是业务执行回执。
- 组装完成后隐藏已知 AppKey 与运行凭据，避免凭据跨网络块或文本内容片段时绕过逐片段替换；错误、日志和对象 repr 不包含请求凭据或原始 SSE。
- 只允许固定 HTTPS 目标，不跟随重定向，也不从部署配置接受替换地址。401、5xx、错误事件、错会话、重复完成、截断、乱码或非 SSE 响应均不自动重发。
- 最大响应512KiB、最多4096个有数据事件、最终文本128KiB、问题4000字符。总预算在每个读取块检查；连接／读／写另有超时，单次读等待最长10秒。不能把这解释为强制进程级硬截止。

该适配器当前汇总最终回复后返回；尚未实现浏览器文本流推送。它没有根据模型文本创建业务卡，现有卡片仍须由已验证本地任务产生。

## 验证与下一步

新增33项 MockTransport／合成 SSE 测试，连同原 ADP后台适配及任务提交相关回归共82项通过；新增模块和测试 ruff、2个相关源码文件定向 mypy 通过。`core/config.py` 的既有 E501 在未修改 HEAD 内容上同样重现，本轮不改该无关行，不声称全仓 lint 通过。

验证覆盖请求结构及独立变量、最终回复、思考／组件丢弃、中文逐字节分块、凭据隐藏、HTTP与解析失败不重试、门禁、参数边界、事件／体积／时间限制和日志。所有网络请求由 MockTransport 截获，未连接腾讯云；这不是平台联调证据。

已有[持久会话与登录API候选](AGENT_MANAGEMENT_CONVERSATIONS_20261025.md)，补充独立业务上下文变量、运行关联、轮次持久化、同会话并发与超时处理及本轮任务操作核验；已有[持久聊天队列](AGENT_CHAT_QUEUE_20261025.md)本地候选，管理端展示继续实施。公开接口的变量能力需要实际验收后才能用于带业务数据的云端调用；未通过时继续保持关闭，不能把运行凭据放进问题文本绕过门禁。
