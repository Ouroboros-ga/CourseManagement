# 申诉预审管理接口候选

日期：2026-10-24。状态：本地候选，默认关闭，未部署。领域见[预审基础](OBJECTION_PRECHECK_DOMAIN_20261024.md)，运行见[专用身份与工具](OBJECTION_PRECHECK_RUNTIME_20261024.md)，后台见[ADP派发与恢复](ADP_OBJECTION_DISPATCH_20261024.md)。本轮提供策略、状态与安全重试；[终审服务端约束](OBJECTION_PRECHECK_FINAL_REVIEW_20261024.md)已有本地候选，[意见与终审表单](OBJECTION_PRECHECK_UI_20261024.md)已有候选，学院策略页面仍待接入。

## 角色与范围

复用真实登录账号和现有学院/责任区授权。策略读取和设置要求实际TEACHER_ADMIN或SUPER_ADMIN，以及完整学院的申诉读取和终审动作范围。重新预审要求这两种实际角色之一，并具有该申诉的既有终审动作范围；限定责任区授权仍按任务范围过滤。

状态读取沿用objection.read，无需新增角色。学生负责人如已获本责任区读取授权，可以读取该范围状态，但不会因有历史审核权限或客户端带教师标签而获得重试权限。普通学生/教工的本人服务不使用这组学院管理接口，学生办理进度仍待单独接入。

接口全部需要原Bearer登录，并受CAMPUS_CONFIGURATION_ENABLED、CAMPUS_BUSINESS_SCOPED_ENABLED和AGENT_OBJECTION_PRECHECK_ENABLED守卫。工具应用密钥或Agent运行凭据不能替代登录身份。四个操作不注册给AI工具目录。

## 接口

所有路径带 `/api/v1`，返回原success的data/requestId格式，响应ID为字符串。

| 方法/路径 | 输入 | 行为 |
| --- | --- | --- |
| GET `/colleges/{cid}/objection-precheck-policy` | 无 | enabled、version、configuration_ready |
| PUT 同上 | enabled严格布尔、current_version严格非负整数 | 原权限复核及版本校验后保存；拒绝authorizer_user_id等额外字段 |
| GET `/colleges/{cid}/objections/{rid}/precheck` | 无 | 该申诉最新预审状态、当前有效建议及重试条件 |
| POST 同上`/retry` | expected_job_id规范数字字符串或null | 发起/重试一轮预审，或返回已登记的同一轮；不能指定学院、策略或执行人 |

配置就绪指工具、Worker与ADP开关、独立预审App配置及两项验收标记、工具应用连接均满足条件，且预审AppId不与换班冲突。它不是Worker在线心跳或实际云端验收证明。未就绪时可以查看状态、关闭已有策略，不能开启策略或登记新的重试任务。

策略开启不回填历史任务。历史缺少预审的申诉通过已授权的retry入口显式发起，不在GET时写数据库，也不在管理员缺少权限时静默代办。

状态字段：

- `job_id/status/stored_status/is_current`：无任务为NOT_STARTED；资料已变化时展示STALE，同时保留真实历史状态。AI建议生成成功不代表人工审核通过。
- `result`：仅当前资料仍匹配且任务SUCCEEDED时返回结构化建议；其他情况为null。不包含执行批次、运行凭据、对象路径或签名链接。
- `final_status`：原人工审核状态，未因查询或重试改写。
- `can_final_review/manual_reason_required/review_block_reason`：实际教务权限、预审当前性及执行状态共同计算；页面据此展示终审和例外原因。原审核POST须携带当前`precheck_job_id`，例外处理须填写`manual_precheck_reason`，具体见终审衔接文档。
- `can_retry/retry_block_reason/retry_block_message`：权限和当前状态共同计算；阻止原因提供业务中文提示，界面无需直接显示内部代码。
- `attempt_no`：当前资料摘要/策略版本内的尝试序号；另有created_at/updated_at。它不是整条申诉跨所有资料版本的总次数。

## 重试与历史

每次真正重试新建任务，保留原FAILED/STALE记录、原运行和原云实例。新任务记录真实发起管理员，并通过retry_of_job_id关联上一轮；旧运行不会重新激活。

同一个旧job_id的重复提交返回同一条后继记录。当前已有未变化的QUEUED/RUNNING任务或有效SUCCEEDED建议时返回该记录，不重复排队；不匹配的旧job_id返回409要求刷新。源资料变化时会使尚未派发的旧QUEUED任务失效，再登记新资料的任务。

上一轮云实例必须已确认FINISHED才能发起新一轮。UNCERTAIN、TIMED_OUT、OBSERVATION_FAILED、WAITING等状态仍有未知或未结束实例，不能靠重试释放容量；旧运行存在但无云实例追踪，或旧任务RUNNING且缺乏可追踪身份时，也禁止盲目重发。应按派发手册对已知实例只读核查，不删除历史表。

已人工完成、已撤回的考勤或已归档学期不能再发起预审；历史状态仍可按原权限读取。后台开始/访问材料/保存时也复核全校学期归档状态，学期共享锁在任务锁之前取得。College权限和资料版本仍由原后端校验。

## 迁移与验证边界

新候选头 `f26a1024a009`：原任务默认attempt_no=1，增加前一轮关联及唯一后继约束，扩展原资料去重键。降级在存在重试序号或前序关联时先拒绝，不删除重试历史。

SQLite验证了无运行引用场景的原任务保留、升降级往返及有重试历史拒绝降级；真实MySQL带运行引用的数据升级、回退和竞争仍待验证。MySQL升级DDL已离线生成，未在真实MySQL执行。

本轮同时调整尚未提交/部署的a004、a008、a009候选降级顺序，先解除外键再删除其支持索引，避免违反MySQL外键索引要求；3项离线MySQL DDL顺序回归不替代真实执行。[MySQL 8.4外键说明](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html)

测试覆盖实际角色撤销、学院/申诉隔离、配置未就绪、开关关闭、严格参数、重试幂等/历史保留、未确认云端结束拒绝重发、原子回滚、归档限制及迁移保护。HTTP测试复用真实领域服务和SQLite，登录依赖替换为合成用户；不作为生产身份或真实ADP验收。

## 后续接入

1. 补学院策略开关页面，处理上下文切换、读取/保存失败、版本冲突及重复点击。意见与重试卡已接入。
2. 已接入共用终审表单：携带当前预审编号，展示例外原因，409后重新核对；补齐责任区独立浏览器场景及真实后端验收。
3. 接入学生本人办理进度，保持预审建议与正式结论区分；完成真实MySQL和ADP验收后再讨论启用。

本轮新增22项领域/HTTP/归档/迁移检查，后续含终审约束的组合回归305项通过；其中3项为离线MySQL降级DDL顺序验证。新增模块Ruff与局部Mypy通过。未执行真实MySQL或ADP验收。
