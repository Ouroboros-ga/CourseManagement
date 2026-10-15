# 上游来源记录

- 来源：用户指定的 `https://github.com/Mo-Qiong/wxsign`。
- 首次引入的上游提交：`30c219fb27e95527dec87c724e288c416a8823b6`；历史同步提交：`9b3cb4cc0099b54da20422939ec953385f66cab6`（2026-09-28）、`43f3540`（2026-10-06）、`3a759dd`（2026-10-08）、`7bca092`（2026-10-09）、`2395641`（2026-10-09）、`fbeaf9cc2d670b0baa3826c9f9f63f9466f9254d`（2026-10-10）；历史同步提交：`d0a48a0c4a3dcef59fdb11698d6d45d402c1dd9f`；最新同步提交：`6d26b4f66ced71f3dec32ccf66eb8c81c445970a`（上游 main，2026-10-14 拉取）。
- 引入范围：上游 `miniprogram/`、`project.config.json` 与 README（保存为 `UPSTREAM_README.md`）；本仓库的 API、身份权限、文件 ID、初核/终审和页面字段按 FastAPI 契约适配，因此不是上游文件的逐字镜像。
- 拉取时的 `miniprogram/package.json` 声明 `"license": "ISC"`；引入的上游文件没有独立 LICENSE 或 NOTICE。本文件记录来源与原声明，不额外授予或推断权利。
- 2026-10-10 向上游推送并同步上述提交（限制未来日期的查课任务只能在当天及以后上传数据，展示黄色引导条，禁用提交按钮并在前端拦截）；仓库仍无独立 LICENSE 或 NOTICE。`package.json` 的 ISC 声明是本次能核对到的许可信息，作者与素材的授权范围未独立核实。

## 2026-10-13 同步记录

- 主项目基线：`b24018441f6e28c287706981e3f342fa2f0d4627`，`dev-main`；同步前已有 12 个未提交文件。
- 从上游 `main` 独立拉取；相对上次记录的 `fbeaf9cc2d670b0baa3826c9f9f63f9466f9254d`，处理 60 个上游变化路径：更新/合并 24 个文件，删除 36 个未被业务页面引用的旧云开发组件及图片。未修改主项目 HEAD、分支或索引，未向上游或主仓库推送。
- 引入双令牌持久化与串行刷新、异议进度/详情和再次申诉页面、初核入口、状态标签样式及上传包忽略配置。上游 README 此次没有相对基线变更，保留现有 `UPSTREAM_README.md`；本地 README 和旧回归测试也保留。
- 冲突处理：保留本地调班申请/状态提示/管理员反馈；调班 API 使用实际后端 `/api/v1/assignment-change-requests`，没有引入上游错误的 `/api/v1/inspection/assignment-change-requests`。删除重复且未绑定依赖的上游弹窗 handler，使用现有本地 dialog。
- 上游临时关闭了未来任务提交的前端限制，本项目后端仍禁止提前提交，因此本地保留日期提示、禁用按钮和提交前门禁。此适配属于本地差异，不宣称与上游逐字一致。
- 保留原有生产/开发环境选择、公开 AppID、私有配置忽略规则和未提交 `detail/index.json`、`detail/index.wxss` 改动；其余原有脏文件哈希保持不变。
- 同步前完整小程序备份、原始 binary diff、合并清单及结果位于 Git 忽略的 `tmp/sync-miniapp-20261013/`。不要将该目录中的本地备份作为公开发布附件。
- 同步验证与系统问题原记录于本地 `docs/CODE_REVIEW_20261013.md`（不随仓库分发）；仓库资料入口见[文档导航](../../docs/README.md)。本轮未执行微信开发者工具编译、真机登录或生产发布；Node 模拟测试不能替代平台验收。

## 2026-10-14 同步记录

- 独立完整 clone 到 `tmp/wxsign-sync-20261014/`；上次 d0a48a0 / 当前本地 / 最新 6d26b4f 三方合并，涉及七个任务 API/列表/详情文件。上游 README、许可声明和配置没有相对基线变化。
- 引入换班申请历史获取、反馈/驳回展示及列表样式；保留本地当前受派状态提示、未来日期门禁和现有 dialog。上游“待申请即禁止任务提交”的行为不引入，申请不免除原任务责任。
- 兼容 `createChangeRequest/getMyChangeRequests` 与上游新函数名，URL 使用真实 `/assignment-change-requests`；申请 ID 保持字符串，已用大整数失败回归修复 Number 截断。
- 没有引入上游 .git、私有开发配置、node_modules 或编译产物。原本地全部 tracked 小程序备份、binary diff、冲突清单保留在 Git 忽略的 `tmp/sync-miniapp-20261014/`。
- 定向 Node 两项通过；全量 39 项中 8 passed、30 failed、1 cancelled，失败/取消数量与之前一致。未编译微信或真机测试，未推送上游，未发布小程序。
- 功能/接口差异、具体缺口及开发者验收见 [开发者变化清单](../../docs/integration/WECHAT_DEVELOPER_CHANGES_20261014.md)。同步代码不等于已完成照片展示、一次审核或所有旧测试修复。
