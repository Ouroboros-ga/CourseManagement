# ADP申诉预审：派发、恢复与工作流接入候选

日期：2026-10-24。状态：本地候选，云端均为模拟；未创建腾讯云预审应用、未启动消费者、未部署。身份与工具见[运行接入](OBJECTION_PRECHECK_RUNTIME_20261024.md)，当前进度见[实施状态](IMPLEMENTATION_STATUS.md)。

## 调用路径与配置

学生创建申诉 → 原事务登记QUEUED任务 → 预审Worker原子领取/签发运行/登记云实例STARTING → 事务外调用独立ADP应用 → ADP调用绑定工具读取资料并保存建议 → Worker轮询原实例并对账本地建议回执 → 人工审核。

预审复用换班派发的持久云实例生命周期、创建/查询尝试隔离、期限、容量和只读复查；预审适配器提供任务来源、实际建议回执和失败状态规则。派发模块本身不新增迁移；后续管理重试使用a009，当前候选代码须升级到最新头，见实施状态。

| 配置 | 规则 |
| --- | --- |
| `AGENT_ADP_OBJECTION_CONFIG` | 独立预审AdpConfiguration；默认null，不能回退换班配置，AppId不得与换班相同 |
| `header_binding_verified` | 默认false；须验证逐运行Header绑定、凭据不进入模型输入/运行历史及SDK日志 |
| `proof_delivery_verified` | 默认false；须验证实际材料获取、URL与多模态载荷/历史脱敏，配置值不构成验收证据 |
| `AGENT_OBJECTION_APP_KEY_ID` | 独立AUTOMATION/objection工具连接的app_key_id，不是腾讯AppId |
| `AGENT_ADP_DISPATCH_LIMITS` | 复用有界参数：默认每应用最多5个未确认结束实例、2秒查询间隔、总等待300秒、最多100次查询 |

整体还需AGENT_TOOLS_ENABLED、AGENT_OBJECTION_PRECHECK_ENABLED、AGENT_ADP_ENABLED；CLI启动正常消费者另要求AGENT_WORKER_ENABLED。全部保持原默认关闭。预算按环境/工具应用/工作流隔离；部署时须使各应用预算之和符合实际账号配额，当前没有跨应用全局额度仲裁器。

## 持久任务与恢复

1. 领取预审任务、生成内部批次、签发绑定运行、登记云实例STARTING和期限在一个数据库事务中提交。任一步失败全部回滚，任务仍可领取；SDK调用在事务外进行。
2. 云端创建成功后保存实例ID，重启继续查询该实例。只有明确拒绝且可重试的创建错误最多尝试3次，每次轮换运行凭据；不是重复创建已知实例。
3. 网络结果不确定或STARTING租约过期时，记录UNCERTAIN、撤销工具凭据，将未成功任务置FAILED转人工，不再创建。未知云实例仍占容量；没有实例ID时不猜测、不清空追踪表释放额度。
4. 查询租约过期可续查原实例，旧查询尝试不能覆盖新状态。达到期限或次数上限后TIMED_OUT、撤销写入并转人工；不声称云实例已取消，仍占容量直到确认终态。
5. 已知实例的人工只读复查不恢复工具权限。观察到终态后释放本应用容量；仍在运行则保持原阻塞状态和占用。配置不匹配时须恢复原应用/环境配置后复查。
6. 源资料变化或策略关闭时不创建模型任务，记录STALE或FAILED。未知学院和其他环境任务不借当前操作者或学籍推断来源。

历史上手工领取、尚无云实例追踪的RUNNING任务不自动重新派发：无法证明是否曾经执行。现有[管理重试接口](OBJECTION_PRECHECK_MANAGEMENT_API_20261024.md)仍会阻止这类任务盲目重发；遗留无追踪记录的明确处置及页面尚待接入。

## 成功依据

预审成功要求任务SUCCEEDED、建议符合严格Schema且关联运行为同事务完成的COMPLETED回执。云端SUCCESS不能代替本地保存；反过来，建议已保存而云端随后FAILED时保留真实建议成功，同时记录云端失败状态。

本地成功状态或建议结构无法与运行回执对应时标记UNKNOWN/LOCAL_RECEIPT_INVALID，不伪报预审成功。预审成功也不等于人工审核通过：Worker不会改写考勤、考勤版本或终审结论。

## 腾讯云逻辑编排（待真实控制台配置）

以下是逻辑节点约束，不代表云端已创建，也不假定当前控制台节点名称：

1. 开始：固定任务说明，运行凭据仅映射到工具请求Header，不放入Query或模型变量正文。
2. 读取：调用`objection_case_get`，拿到这份申诉的理由、诉求、当前考勤与允许读取的材料列表。
3. 材料分支：只遍历返回的file_id，调用`objection_material_access`，按真实验收后的材料通道读取。最长60秒链接临近读取时申请；相对路径由可信固定公网基址解析，不接受模型指定域名。
4. 预审：把理由、材料及其识别文字标为不可信业务内容。只核对日期/课程/诉求与材料所载信息，输出缺失项、引用和人工核验建议，不据材料外观判断真伪，不接受材料中的指令。
5. 保存：使用独立合同中的严格result Schema调用`objection_precheck_save`。相同保存可重放；不同建议不得覆盖已保存结果。MANUAL_REQUIRED/STALE或工具拒绝进入异常结束，不伪造保存回执。
6. 结束：由后端轮询对账。格式错误、材料不可访问、模型失败、超时均须有明确失败分支，不在前端伪报已经完成预审。

目前官方SDK适配器已增加固定预审Query和独立应用选择，复用原签名/SDK载荷日志抑制；没有进行真实腾讯云调用或多模态验收。

## 运行与验证

```powershell
# backend目录；须先完成隔离MySQL与真实ADP验收，当前不要启用生产配置。
.venv/Scripts/python.exe -m app.modules.agent.objection_dispatcher --once
.venv/Scripts/python.exe -m app.modules.agent.objection_dispatcher --observe-run <已知本地run_id>
```

连续运行去掉--once，每环境/工具应用仅一个Worker。systemd候选为`deploy/production/course-agent-objection-worker.service`，未安装或启动；原换班Worker继续使用其独立入口和应用配置。

本轮测试使用真实领域/任务/运行事务和模拟云端，覆盖原子登记、重启续查、无回执转人工、真实建议与云端失败对账、不确定创建、创建租约过期、明确拒绝重试、策略关闭、材料门禁、环境隔离、源资料失效、提交失败整体回滚、超时只读复查和伪造成功回执；SDK测试验证独立AppId、固定Query、日志抑制及禁止回退/串用应用。真实MySQL竞争、外部HTTPS、ADP节点与材料历史脱敏仍待验收。

本轮新增15项预审定向测试及1项换班回执缓存回归；与原网关、换班、预审、材料和人工审核路径组合246项通过，Agent与预审核心局部Mypy19文件及Ruff通过。CLI的--help已验证，默认配置--once明确拒绝启动，没有运行真实消费者。

回执对账补充：预审运行状态、换班申请及原/新受派采用带锁当前读并刷新ORM值。已复现并修复另一事务完成改派后旧会话缓存导致UNKNOWN的问题；SQLite回归通过，真实MySQL的REPEATABLE READ竞争仍待验证。
