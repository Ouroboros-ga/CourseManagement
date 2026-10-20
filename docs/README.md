# 文档导航

2026-10-19 当前入口：[实施状态](development/IMPLEMENTATION_STATUS.md)，包含已部署的查课/删除、志愿者选组及 Excel 成员导入，以及本次工作区整理边界。人员关联专题见 [唯一人员档案与业务关联补齐](development/PERSON_RELATION_COMPLETION_20261018.md)，历史实施描述不代替当前发布记录。

整理日期：2026-10-19。资料按“当前优先、专项参考、历史归档”组织。先阅读前两项；需要实施时看状态页，不逐一执行旧计划。

## 当前优先

| 优先级 | 文档 | 用途 |
| --- | --- | --- |
| 1 | [产品、架构与 Web 重构总体设计](development/CAMPUS_PRODUCT_ARCHITECTURE_WEB_REDESIGN_20261015.md) | 最新设计入口：七入口、学院自行导入、生命周期、权限、跨院检查结果和 R0—R6；已确认项与待讨论项分列 |
| 2 | [全校产品需求](product/CAMPUS_MANAGEMENT_PRD.md) | 需求及验收编号，继承业务约束；与最新总体设计的新增决策一起阅读 |
| 3 | [当前实施状态与下一步](development/IMPLEMENTATION_STATUS.md) | 当前代码基线、已有能力、剩余工作和历史证据入口；不把计划当成实现 |

若需求冲突，以用户后续确认和最新设计中的已确认规则为准；是否实现、启用和验收分别核对代码、配置与证据。新设计中的建议表名和接口能力不是已开放的 API。

当前本地优化：[统一列表分页与查询链路整改](development/LIST_PAGINATION_QUERY_AUDIT_20261020.md)，实现与部署分别记录，不代表已上线。

## 开发与接口参考

| 文档 | 使用方式 |
| --- | --- |
| [后端 README](../backend/README.md)、[Web README](../apps/admin-web/README.md)、[小程序 README](../apps/wechat-miniapp/README.md) | 环境、启动和端侧开发入口 |
| [API 契约](API_CONTRACT.md)、[API 索引](API_INDEX.md)、[OpenAPI](openapi.json) | 已有接口及兼容行为；实际以已挂载路由/schema为准，运行能力可能尚未开启 |
| [权限策略](PERMISSIONS.md) | 授权、资源范围和身份规则；分日期历史章节不能覆盖后续确认 |
| [排班规则参考](SCHEDULING_RULES.md) | 原有调度约束与实现基础；新组织模式结合最新总体设计及 scheduling 模块阅读 |
| [2026-10-16小程序接口增量](integration/WECHAT_API_CHANGES_20261016.md) | 学生旧契约保持不变；正式来源、恢复与单次修改为独立可选能力 |
| [2026-10-16小程序与后端核查](integration/WECHAT_BACKEND_AUDIT_20261016.md) | 最新小程序课表路由不一致、后端修复、实际验证与未部署边界 |
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

38 份旧设计、阶段计划、执行记录和历史发布资料已集中到 [archive/2026-10-15](archive/README.md)，仍保留 Git 追踪。每份都有归档说明和原路径；内部相对链接已随位置更新。需要追溯时使用 `git log --follow -- <新路径>`。

`legacy_parser_reference/` 保持原位：它属于解析实现参考，不参与本次业务方案归档。小程序来源记录及上游 README 保持端侧目录结构，不按旧业务方案删除。

`AGENTS.md` 等本地协作指引继续按仓库既有忽略规则管理，不强制纳入 Git。`tmp/` 下的本地快照、恢复文件、真实资料或凭证不得随文档整理提交。

新增资料应说明用途、日期、状态及与已有设计的关系。日常只维护一份当前实施状态；阶段验收完成后归入历史记录，避免并存多份互相矛盾的“最新计划”。

2026-10-19 主工作区未提交的 README 扩写、功能盘点及教职工身份讨论已收入 [工作区历史草稿](archive/2026-10-19-workspace/README.md)。这些资料包含旧部署状态与相互冲突的账号时序，不作为当前开发命令或联调合同；原始文件另有本地完整快照。
