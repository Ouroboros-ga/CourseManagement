# 文档导航

当前进度统一查看[实施状态](development/IMPLEMENTATION_STATUS.md)，区分历史发布、本地候选和未验收事项。人员关联专题见[唯一人员档案与业务关联补齐](development/PERSON_RELATION_COMPLETION_20261018.md)。

整理日期：2026-10-24（归档20份历史资料并修复引用）。资料按“当前优先、专项参考、历史归档”组织。按工作主题选择当前入口；需要实施时看状态页，不逐一执行旧计划。

## 当前优先

| 优先级 | 文档 | 用途 |
| --- | --- | --- |
| 1 | [产品、架构与 Web 重构总体设计](development/CAMPUS_PRODUCT_ARCHITECTURE_WEB_REDESIGN_20261015.md) | 校园业务设计入口：七入口、学院自行导入、生命周期、权限、跨院检查结果和 R0—R6；已确认项与待讨论项分列 |
| 2 | [全校产品需求](product/CAMPUS_MANAGEMENT_PRD.md) | 需求及验收编号，继承业务约束；与最新总体设计的新增决策一起阅读 |
| 3 | [当前实施状态与下一步](development/IMPLEMENTATION_STATUS.md) | 当前代码基线、已有能力、剩余工作和历史证据入口；不把计划当成实现 |

若需求冲突，以用户后续确认和最新设计中的已确认规则为准；是否实现、启用和验收分别核对代码、配置与证据。新设计中的建议表名和接口能力不是已开放的 API。

分页专题：[统一列表分页与查询链路整改](development/LIST_PAGINATION_QUERY_AUDIT_20261020.md)；该批次结果见[2026-10-20发布记录](archive/2026-10-24/operations/LIST_PAGINATION_RELEASE_20261020.md)，原文的本地验证表述保留当时语义。

## AI 产品与开发规划：当前有效入口

| 文档 | 当前版本与用途 |
| --- | --- |
| [五模块产品设计](product/AI_COLLABORATIVE_PLATFORM_FUNCTIONAL_DESIGN.md) | v1.1：功能、交互、权限范围与产品验收 |
| [技术架构](development/AI_COLLABORATIVE_PLATFORM_ARCHITECTURE.md) | v0.4：腾讯云编排、薄网关、任务运行和领域服务边界 |
| [工具合同](TOOL_GATEWAY_CONTRACT.md)、[运行手册](RUNBOOK_TOOL_GATEWAY.md) | 本地候选接口、身份与启用门禁；交互7工具、后台换班2工具和预审3工具分别导出合同，未联调腾讯云或部署 |
| [ADP换班工作流接入规格](development/ADP_CHANGE_WORKFLOW_20261024.md) | 新版SDK适配器、节点配置、动态Header/元数据脱敏门禁；不是已创建的云端应用 |
| [ADP持久派发与对账](development/ADP_CHANGE_DISPATCH_20261024.md) | 实例保存、重启恢复、创建结果不确定、容量和人工复查；本地模拟验证，未启动消费者 |
| [申诉预审领域基础](development/OBJECTION_PRECHECK_DOMAIN_20261024.md) | 独立策略、任务、建议及材料权限；工具接入见下项，尚无云端执行或页面 |
| [申诉预审运行接入](development/OBJECTION_PRECHECK_RUNTIME_20261024.md) | 独立AUTOMATION/objection身份、3个HTTP/MCP工具和保存回执；本地候选，未接真实云端或页面 |
| [预审派发与恢复](development/ADP_OBJECTION_DISPATCH_20261024.md) | 原子领取/登记、独立ADP配置、材料门禁、重启续查及回执对账；模拟验证，未启动消费者 |
| [预审管理接口](development/OBJECTION_PRECHECK_MANAGEMENT_API_20261024.md) | 学院策略、单条申诉状态与安全重试；保留每轮历史，终审约束、表单及学院开关见下项 |
| [预审与教务终审衔接](development/OBJECTION_PRECHECK_FINAL_REVIEW_20261024.md) | 实际教务身份、当前预审确认及人工例外留痕；服务端与管理表单候选，未接真实云端 |
| [预审意见与终审表单](development/OBJECTION_PRECHECK_UI_20261024.md) | 状态、建议、重试和终审确认；本地模拟浏览器验证；学院开关见下项 |
| [学院预审开关](development/OBJECTION_PRECHECK_POLICY_UI_20261024.md) | 配置门禁、保存回执、冲突刷新及范围隔离；本地模拟浏览器验证 |
| [学生本人申诉进度接口](integration/WECHAT_OBJECTION_PROGRESS_20261024.md) | 本人只读进度及小程序对接合同；后端及小程序源码候选，编译和真机待验收 |
| [小程序办理进度接入](development/WECHAT_OBJECTION_PROGRESS_UI_20261024.md) | 详情进度、刷新、上下文隔离和BIGINT；Node行为验证，微信编译/真机待验收 |
| [智能体报表导出准备](development/AGENT_REPORT_EXPORT_20261024.md) | 固定格式及当前学院下载操作；本地实际文件生成/权限回归，统计页任务卡见下项 |
| [助手报表下载卡](development/AGENT_REPORT_EXPORT_UI_20261024.md) | 按本人队列任务读取结果、登录下载及上下文隔离；模拟浏览器通过，真实助手会话待联调 |
| [助手核对资料预览](development/AGENT_IMPORT_REVIEW_20261024.md) | 复用现有差异与冲突检查，汇总本人预览；任务核对卡见下项，上传工作区待接通 |
| [助手资料核对卡](development/AGENT_IMPORT_REVIEW_UI_20261024.md) | 按本人任务恢复同类型预览，交回原核对与人工保存流程；模拟桌面/窄屏验证通过，真实助手交接待联调 |
| [云端助手读取任务交接](development/AGENT_READ_TASK_HANDOFF_20261025.md) | 受限提交报表/资料核对作业，复用原队列与固定页面入口；本地HTTP/MCP通过，真实管理助手入口待接通 |
| [工具网关实施计划（本地）](superpowers/plans/2026-10-24-tool-gateway-implementation.md) | v0.3：网关 A、运行基础 B、业务增强 C 与验收；该目录按仓库规则不纳入 Git，其他检出可能没有此文件 |

三份文档分别承担产品、架构与实施职责；本地候选进度统一看实施状态，设计和计划不作为已交付证明。旧“四模块＋排班内换班”和通用授权平台方案已被原位更新，不再另维护一份旧计划。2026-10-15校园重构批次的“智能体暂缓”只保留历史含义；AI实施状态见上方统一状态页。

## 开发与接口参考

| 文档 | 使用方式 |
| --- | --- |
| [后端 README](../backend/README.md)、[Web README](../apps/admin-web/README.md)、[小程序 README](../apps/wechat-miniapp/README.md) | 环境、启动和端侧开发入口 |
| [API 契约](API_CONTRACT.md)、[API 索引](API_INDEX.md)、[OpenAPI](openapi.json) | 已有接口及兼容行为；实际以已挂载路由/schema为准，运行能力可能尚未开启 |
| [权限策略](PERMISSIONS.md) | 授权、资源范围和身份规则；分日期历史章节不能覆盖后续确认 |
| [排班规则参考](SCHEDULING_RULES.md) | 原有调度约束与实现基础；新组织模式结合最新总体设计及 scheduling 模块阅读 |
| [2026-10-16小程序接口增量](integration/WECHAT_API_CHANGES_20261016.md) | 学生旧契约保持不变；正式来源、恢复与单次修改为独立可选能力 |
| [2026-10-16小程序与后端核查](archive/2026-10-24/reviews/WECHAT_BACKEND_AUDIT_20261016.md) | 历史核查及后续兼容修复证据；当前接口看契约，部署看实施状态 |
| [小程序功能及接口变化](integration/WECHAT_DEVELOPER_CHANGES_20261014.md) | 既有照片、一次异议审核、换班和通用客户端适配；保留当时版本边界 |
| [个人课表与简单通知接口](integration/WECHAT_PERSONAL_TIMETABLE_API_20261015.md) | 以小程序本地编辑＋完整备份为准；三个兼容入口已上线，原逐条接口保留 |

## 运行与维护

| 文档 | 使用方式 |
| --- | --- |
| [微信运行配置](WECHAT_RUNTIME_CONFIG.md) | 接入配置及历史配置记录，执行前核对当前环境 |
| [备份恢复手册](RUNBOOK_BACKUP_RESTORE.md) | 开发/预发示例与恢复方法；生产按真实连接、存储和权限调整 |
| [生产安全配置](../deploy/production/SECURITY_BASELINE.md) | 线上 nginx 配置的版本化清单、实际安装位置与恢复边界 |
| [负载及运行验收手册](RUNBOOK_LOADTEST_ACCEPTANCE.md) | 需要性能/容量验收时使用，不是每次提交必跑门禁 |
| [历史发布及部署记录](archive/README.md#operations) | 按日期查备份位置、旧发布和回滚证据；不直接复用旧命令推断当前部署 |

## 历史资料与本地资料

本次收拢的15份历史发布/修复记录、3份阶段核查/验收和2份早期计划见[2026-10-24归档清单](archive/2026-10-24/README.md)。每份保留原路径、当时结论和证据；未将尚待核实的专项方案整体判为过期。

38 份旧设计、阶段计划、执行记录和历史发布资料已集中到 [archive/2026-10-15](archive/README.md)，仍保留 Git 追踪。每份都有归档说明和原路径；内部相对链接已随位置更新。需要追溯时使用 `git log --follow -- <新路径>`。

`legacy_parser_reference/` 保持原位：它属于解析实现参考，不参与本次业务方案归档。小程序来源记录及上游 README 保持端侧目录结构，不按旧业务方案删除。

`AGENTS.md` 等本地协作指引继续按仓库既有忽略规则管理，不强制纳入 Git。`tmp/` 下的本地快照、恢复文件、真实资料或凭证不得随文档整理提交。

新增资料应说明用途、日期、状态及与已有设计的关系。日常只维护一份当前实施状态；阶段验收完成后归入历史记录，避免并存多份互相矛盾的“最新计划”。

2026-10-19 主工作区未提交的 README 扩写、功能盘点及教职工身份讨论已收入 [工作区历史草稿](archive/2026-10-19-workspace/README.md)。这些资料包含旧部署状态与相互冲突的账号时序，不作为当前开发命令或联调合同；原始文件另有本地完整快照。

- [2026-10-20 统一分页正式发布与成套回滚记录](archive/2026-10-24/operations/LIST_PAGINATION_RELEASE_20261020.md)
- [2026-10-20 全校操作日志查看页发布记录](archive/2026-10-24/operations/AUDIT_LOG_VIEWER_RELEASE_20261020.md)
