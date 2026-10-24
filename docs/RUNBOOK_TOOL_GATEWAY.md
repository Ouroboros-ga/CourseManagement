# 工具网关与任务运行手册

日期：2026-10-24。状态：本地候选，未部署；本手册的生产路径继承现有服务约定，执行前核对实际环境。

## 启用顺序

1. 验证目标数据库和备份；运行兼容迁移到 `f26a1024a009`，先在隔离MySQL验证升级／锁语义。本轮未执行真实MySQL迁移。
2. 设置受保护的应用连接配置，默认先不打开新功能。配置与Header见[工具合同](TOOL_GATEWAY_CONTRACT.md)。
3. 开启HTTP只读测试，验证学院、责任区与本人范围及错误凭据拒绝；按需开启MCP并设置精确Host／Origin允许项。
4. 配置 `AGENT_WORKER_ENABLED=true`，先用 `python -m app.modules.agent.worker --once` 验证一条脱敏任务；连续运行去掉 `--once`。
5. Linux可采用 `deploy/production/course-agent-worker.service`，继承现有业务用户和环境文件；这份文件未安装或启动。Windows本地直接在终端运行，不自动弹出额外窗口。

不提供公网运行凭据签发接口；后端适配层必须先通过真实会话建立运行，再受信传入腾讯云。没有动态身份绑定证据前，不开放真实个人数据工具给云端。

后台预审采用独立AUTOMATION/objection连接，由内部策略任务签发绑定运行，不能复用换班身份或伪造登录会话。当前已有3个HTTP/MCP工具及保存重放回执，见[预审运行接入](development/OBJECTION_PRECHECK_RUNTIME_20261024.md)。[预审派发/恢复候选](development/ADP_OBJECTION_DISPATCH_20261024.md)使用独立ADP配置和`objection_dispatcher`入口，材料传递验收开关默认false；未启动消费者，不套用下方换班Worker命令启动预审。

## 当前任务接口

- `POST /api/v1/assistant/tasks`：当前登录用户提交 `run_id`、`tool_name`、`arguments`、`request_key`。只允许本人当前会话的运行，返回 task_id／真实状态；不返回运行密钥。
- `GET /api/v1/assistant/tasks/{id}`：仅本人查看，并重新检查原运行和可见范围；范围变化后拒绝返回旧结果。
- `POST /api/v1/assistant/tasks/{id}/cancel`：取消本人未完成任务；已完成结果不倒退。
- 智能体通过 `task_status_get` 查询当前运行创建的任务，不能凭另一个运行的编号查询结果；状态查询无需排队。

request_key为1—64位字母／数字／下划线／连字符，统一转小写以保持MySQL和SQLite行为一致。同用户／会话／键、同规范化参数返回原任务，不同参数409。每次运行默认最多100条待执行／执行中任务，由 `AGENT_RUN_MAX_PENDING_TASKS` 配置；超出429，已有请求仍可重放查询。

## 任务恢复与限制

当前任务仅执行已注册的只读工具；固定Worker从MySQL持久记录领取，领取后才显示RUNNING。没有在FastAPI进程内保存唯一任务副本。

作业租约60秒，尝试令牌区分重领前后的Worker。完成发布须满足RUNNING、当前令牌且租约未过期；取消后的迟到结果不能发布。临时数据库错误最多3次退避重试，最后一次崩溃租约过期后转失败，不无限重跑。

当前读取任务不以工具token的10分钟有效期作为执行截止，但原登录会话、账号、应用配置和运行状态必须仍有效。后台换班运行已支持绑定策略执行记录，source_session_id为空，使用真实申请人及策略授权人来源，不伪造在线会话。后台写工具调用仍要求未过期的运行凭据；不进入只读Worker队列。

只读结果与范围摘要关联；责任区／学院授权变化或本人绑定变化时，不继续返回旧结果。该摘要复用原权限计算，不存一套可独立授予权限的角色清单。

首期按一个Worker运行；MySQL领取使用行锁／SKIP LOCKED，真实MySQL多Worker并发仍待测试。短查询保持同步。尚未接入ADP异步运行的等待／对账、重文件子进程超时或周期业务计划，不把本地读取队列描述为完整长任务平台。

ADP客户端已接入独立派发Worker候选，详见[持久派发与对账](development/ADP_CHANGE_DISPATCH_20261024.md)。`AGENT_ADP_ENABLED=false`、`AGENT_ADP_CONFIG=null`为默认值且已在本工作区确认；本轮没有启动消费者。短轮询有界返回不代替持久状态；创建结果不确定时保留记录、撤销写入并停止重建。真实Header隔离、元数据脱敏及MySQL门禁未通过前不可启动创建路径。

## 事务边界

TaskService.submit只flush，业务入口可把源事件和作业放入同一事务；HTTP提交入口负责commit。身份恢复支持不触碰会话时间的验证模式，避免内部commit提前提交父业务。

排班服务已提供 `preview_in_transaction`及`commit_in_transaction`，保留原校验、锁和写入，不自行提交；原公开入口仍按旧行为提交。自动换班领域服务使用该核心，将原受派撤销、新受派、申请处理、系统审计及回执一次提交；原申请创建与执行记录登记同事务。策略接口与管理页面已有本地候选，云端自动触发尚未接通。

## 诊断与回退

检查进程、排队年龄、最后领取时间、attempt_count、lease_until、error_code和trace_id；不要在诊断输出打印应用Header、token、完整参数或申诉材料。API健康不等于Worker正在运行。

故障时先关闭新入口、停止Worker领取并对账在途任务，再回退兼容代码。保留任务与运行表，不能清空表“恢复”。迁移downgrade在存在记录时拒绝删除；已生效业务不因应用回退而撤销。

当前可复现验证命令（backend内）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/agent -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app/modules/agent tests/unit/agent --no-cache
.\.venv\Scripts\python.exe -m mypy app/modules/agent --follow-imports=silent
.\.venv\Scripts\python.exe -m alembic heads
```

SQLite、HTTP和本地Uvicorn测试不代替真实MySQL、腾讯云、外部HTTPS或上线验证。
