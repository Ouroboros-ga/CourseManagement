# 管理端教学助手侧栏

日期：2026-10-25。分支：`future/agent-dev`。本地候选，未部署，真实腾讯云未联调。

## 使用流程

管理端顶部“教学助手”打开侧栏，显示当前学院和学期。教师输入具体问题，接口登记后展示“正在排队”，随后自动查询处理状态和正式回复。侧栏可关闭再打开；同一标签页刷新后，重新读取本会话，不重发旧问题。

报表和资料核对操作来自[会话接口](AGENT_MANAGEMENT_CONVERSATIONS_20261025.md)中的真实任务列表。报表操作打开原报表页的准备卡片，再由本人点击生成下载；资料操作打开教务资料核对页，继续原预览与人工确认。聊天文字中的网址、任务编号和 HTML 不会被转换成操作或执行。

网络中断后，原问题和请求键仅在当前页面内存保留，显示“重试原请求”。用户可以先刷新状态；明确点击重试时沿用原标识，后端幂等返回已登记轮次。刷新页面恢复的是服务器记录，不会自动重发未确认请求。未知云端结果继续显示待核对状态，不允许沿用原远端会话继续提问；新建会话也不会自动释放后台未知容量。

学院、学期、账号、角色／权限及授权／配置修订变化时清理对话和恢复指针，旧请求不得回写。读取被拒绝时立即移除旧消息与操作。关闭侧栏暂停轮询，打开后重新读取；仅排队／发送或真实子任务待处理时轮询，每2秒一次，单轮最多450次，之后可手动刷新。更早记录按游标加载并按字符串 ID 合并，最多保留100轮。

发送确认后清理原工作区“未保存输入”记录，避免已发送问题阻止任务跳转；未发送草稿仍沿用原切换提醒。若用户取消导航，侧栏保留。

## 入口与组件边界

新增构建变量 `VITE_AGENT_CHAT_ENABLED=false`，样例在 `apps/admin-web/.env.example`。保持默认关闭；改变变量需要重新构建 Web。入口还检查登录、学院业务模式、学期及现有统计／导入／查课读取能力。这只决定界面入口，真实范围仍由每次后端调用计算，不根据前端角色获得权限。

| 文件 | 单一职责 |
| --- | --- |
| `api/assistantConversations.ts` | 固定登录路径、规范字符串 ID、会话 DTO 与固定任务路径校验 |
| `composables/useManagementConversation.ts` | 会话恢复、请求幂等键、轮询、历史及上下文隔离 |
| `components/assistant/ManagementAssistant.vue` | 顶部入口、侧栏、上下文和受控页面导航 |
| `ManagementConversationPanel.vue` | 组合消息、输入与状态 |
| `ConversationMessages.vue` | 按纯文本显示消息、真实任务按钮；向上发出打开操作 |
| `ConversationComposer.vue` | 输入、发送／重试事件和原未保存输入保护 |

浏览器 sessionStorage 仅保存当前会话编号和上下文指针，不保存问题、回复、材料、Bearer 或平台凭据。后端仍回查本人来源登录，指针不授予访问权。当前展示最终正式回复；浏览器逐字流式文本尚未实现。

## 本地 QA

目标路径：管理端报表页 → 教学助手 → 提问 → 排队与回复 → 打开真实任务 → 原报表卡片 → 本人下载。

相关53项 Node 测试通过，含本批16项会话测试及原外壳／报表／导入／上下文／导航回归；`npm.cmd run build` 包含 vue-tsc 与 Vite构建通过。既有大包体积提示仍存在。源码没有新增前端运行依赖。

Browser plugin not available，采用已有 bundled Playwright 与本机 Edge 无头验证。开发入口 `http://127.0.0.1:3000/dashboard/reports`，1440×1000及390×844；全部 API 被模拟拦截，没有连接实际业务后端或腾讯云。默认生产构建另通过本地4173预览，入口不可见且无对话请求。

| 检查 | 结果与证据范围 |
| --- | --- |
| 页面身份、非空和框架错误层 | 标题为课堂查课考勤管理系统，报表和侧栏可见，无 Vite覆盖错误 |
| 排队、轮询、纯文本 | QUEUED转回复；合成 HTML 只显示为文本，没有图片、脚本或事件执行 |
| 任务和下载 | 固定任务9打开原报表卡片；带实际模拟登录 Header下载一次合成文件 |
| 刷新恢复 | 刷新页面后读取原会话，发送数不增加 |
| 断网重试 | 模拟发送已登记但回执丢失，手动重试同键同内容，仅一条轮次 |
| 权限与上下文 | 模拟403立即去掉消息和任务；切换学院后不显示旧会话 |
| 桌面／窄屏 | 侧栏内容可读、输入和操作可见，390px侧栏无横向溢出 |
| 控制台 | 无未解释的前端异常；只有故意注入的网络失败与403资源提示 |
| 默认关闭 | 默认构建隐藏教学助手，不调用对话接口 |

截图及机读结果存放于本机 `C:/Users/LIU/.codex/visualizations/2026/10/25/agent-chat/`：`desktop.png`、`mobile.png`、`permission-error.png`、`default-off.png`、`result.json`。截图中的 HTML 字符串是故意注入的安全测试文本。

复现单元验证（`apps/admin-web` 内）：

```powershell
node --test tests/management-conversation.test.mjs tests/app-shell.test.mjs tests/assistant-report-export.test.mjs tests/assistant-import-review.test.mjs tests/workspace-navigation.test.mjs tests/campus-context.test.mjs
npm.cmd run build
```

## 尚缺验收

真实 ADP变量／动态 Header和日志隔离、真实 MySQL迁移和并发仍按[聊天队列门禁](AGENT_CHAT_QUEUE_20261025.md)执行。资料原件已有[持久工作区后端](AGENT_IMPORT_WORKSPACE_20261025.md)，管理端附件与原预览交接、周期排班以及五模块完整业务验收继续实施。模拟浏览器闭环只证明前端及约定接口行为，不代表真实模型理解、真实报告数据或生产开放。
