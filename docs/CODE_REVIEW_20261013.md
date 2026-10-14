# 2026-10-13 系统代码审查与微信小程序同步记录

## 范围与结论

本轮完成项目级 `AGENTS.md`、小程序上游同步和系统代码审查。审查基线为主项目 `dev-main` / `b24018441f6e28c287706981e3f342fa2f0d4627`，包含任务/调班/异议的既有未提交改动；小程序为上游 `main` / `d0a48a0c4a3dcef59fdb11698d6d45d402c1dd9f` 合入后的本地适配副本。

确认并列出 **16 项需要修复的功能或数据问题：5 项 P1、11 项 P2**。P1 涉及身份权限、既有事实和错误考勤写入，建议在继续发布前先处理；P2 涉及导入、授权范围、排班、导出、分页及小程序业务闭环。Ruff/mypy 数量另列，不将格式问题或旧测试失配凑成业务问题。

本轮没有修复下述业务问题，没有自动提交、推送、部署或修改业务数据库。主审核对了独立后端/客户端审查结果，并在内存数据库或模拟客户端复核关键路径。未连接生产或执行 MySQL 集成夹具；未做浏览器业务操作、微信开发者工具编译、真机登录或负载/恢复验收。以下行号指本轮最终本地文件，后续修改可能使其变化。

## 交付与同步

- [项目开发指引](../AGENTS.md)：主项目和小程序 GitHub 地址、目录/技术栈、契约资料、开发/检查命令、身份权限/业务约束、上游同步及发布边界。
- 主项目：<https://github.com/Ouroboros-ga/CourseManagement>；小程序上游：<https://github.com/Mo-Qiong/wxsign>。
- 上游同步：`fbeaf9cc2d670b0baa3826c9f9f63f9466f9254d` → `d0a48a0c4a3dcef59fdb11698d6d45d402c1dd9f`，处理 60 个变化路径，合并/更新 24 个文件，删除 36 个无业务引用的旧云开发组件和图片。
- 保留本地调班 dialog、正确后端 API、待处理/驳回反馈、私有配置忽略规则和原有未提交修改；保留后端仍要求的未来日期提交门禁。没有引入上游错误的 `/api/v1/inspection/assignment-change-requests` 或重复未绑定 handler。
- 其他原有脏文件 SHA256 保持一致，主项目 HEAD/分支未变化。详细记录见 [上游来源](../apps/wechat-miniapp/UPSTREAM_PROVENANCE.md)。
- 备份、原始 binary diff、合并暂存/清单及校验结果在 Git 忽略的 `tmp/sync-miniapp-20261013/`；审查复核脚本在 `tmp/code-review-20261013/`。这些本地证据不随 Git 发布。

## 验证结果

| 检查 | 本次结果 | 边界 |
| --- | --- | --- |
| 后端单元测试 | 189 passed，2 条依赖弃用警告 | 不是 MySQL/HTTP 全量验收 |
| Web 类型检查和生产构建 | exit 0 | 有动态/静态 import 混用与大 chunk 警告；未做浏览器操作 |
| 小程序 JS/JSON/本地导入 | 18 个 JS、13 个 JSON 通过，无缺失 JS 导入/冲突标记 | 不等于微信平台编译或渲染通过 |
| 小程序旧 Node 回归 | 37 个运行器条目：6 passed、30 failed、1 cancelled，exit 1 | 5 秒超时保护；包含已删除模块和旧 VM 依赖/页面调用失配，不等于 30 个独立产品 bug |
| Ruff app/tests | 167 项，exit 1 | 91 行长、39 未用导入、23 导入排序等，不将此数当业务缺陷数 |
| mypy app | 8 个文件、32 项错误，exit 1 | 类型/契约问题仍未解决 |
| 后端关键离线观察 | 5 项当前缺陷成功复现 | SQLite；解绑的隔离级别标记与 STOP 的 MySQL UPSERT 被隔离模拟，未检验并发 |
| 客户端关键离线观察 | 7 项实际脚本模拟复现，另核对逾期模板分支 | 虚构数据；不访问网络/业务数据库 |
| Git diff --check | 仍有 `detail/index.wxss:160` 文件末尾空行 | 原有未提交文件，保留原始哈希，没有为消除警告覆盖它 |

复核命令（从仓库根运行）：

```powershell
backend/.venv/Scripts/python.exe tmp/code-review-20261013/backend_checks.py
node tmp/code-review-20261013/client_repros.mjs
backend/.venv/Scripts/python.exe tmp/sync-miniapp-20261013/validate_sync.py
```

上述前两份脚本断言的是“当前缺陷存在”，exit 0 代表复现成功，不能作为产品正确的通过用例。它们不会连接业务数据库；后端脚本只使用独立内存 SQLite。常规测试命令见 `AGENTS.md`，Node 原始输出在 `tmp/sync-miniapp-20261013/node-tests.log`。

## P1：优先修复

### B01：账号预置与微信合并可能将学生身份附到管理员账号

- 位置：`backend/app/modules/academic/service.py:1221–1234`；关联 `backend/app/modules/identity/service.py:982–1001`。
- 触发：管理员账号用户名恰好等于学生学号，尚未关联 student_id/微信；志愿者账号预置按同名账号复用，学生随后使用合法绑定码绑定。
- 问题：预置只检查 username 和 student_id，不检查账号来源或管理角色；绑定只以“已有账号没有微信”作为可合并条件，迁移微信身份/会话并保留该账号的旧角色。
- 影响：学生微信身份可以获得该既有管理员账号的权限。主审内存复核确认预置复用了含 SUPER_ADMIN 的账号并保留该角色；后续身份/会话迁移由实际绑定服务代码确认。独立审查者另外离线复现了完整绑定链路。
- 修复方向：标记真正的学生预置账号来源，禁止自动合并管理角色账号；不要仅以学号同名或缺少微信证明账号可合并。为同名教师/超管、不同账号来源和已有会话补回归。

### B02：自助解绑绕过最后一个超管保护并清空所有角色

- 位置：`backend/app/modules/identity/service.py:1061–1076`，入口 `backend/app/modules/identity/router.py:215–225`。
- 触发：唯一有效超级管理员调用 `DELETE /me/student-binding`；账号即便没有学生绑定，只要还有角色也能进入。
- 问题：入口只有登录依赖，服务遍历并撤销全部角色，没有复用最后超管守卫或管理员变更锁协议。
- 影响：账号仍启用但已无管理权限，应用内无人可以恢复角色；教师/负责人角色也可能被错误清除。
- 证据：主审内存复核 `['SUPER_ADMIN'] → []`；仅忽略 SQLite 不支持的 READ COMMITTED 标签，ORM 角色删除、审计和 commit 都实际执行。
- 修复方向：限定解绑的学生身份和可移除角色，保留独立管理身份；涉及管理角色时复用最后管理员保护、角色锁和会话生命周期规则。

### B03：停课联动取消已入账任务并覆写截止考核事实

- 位置：`backend/app/modules/academic/service.py:478–491`；默认参数 `academic/schemas.py:103`。
- 触发：某天已有自动 APPROVED 的提交或已结算截止事实，随后新增 STOP 校历覆盖，默认开启 cascade_cancel_tasks。
- 问题：直接将所有该日任务取消，不调用普通取消的正式考勤守卫；已有 assessment 的 result/evaluated_at 被直接改写。
- 影响：已提交任务从考勤统计集合剔除，截止时有效提交或逾期未执行事实被变为 CANCELED，统计和考核历史失真。
- 证据：主审内存复核统计 eligible `[task] → []`、`VALID_SUBMISSION → CANCELED`。仅替换 SQLite 无法编译的 MySQL revision UPSERT，其余取消/快照/提交/审计真实执行；普通取消的守卫在 `inspection/service.py:2101`。
- 修复方向：联动复用普通取消的业务边界，拒绝静默取消已入账任务；截止快照保留不可变事实，需要更正时设计明确的历史与审计。

### C01：任务抽屉异步串数据，可以更正另一任务的考勤

- 位置：`apps/admin-web/src/components/TaskDrawer.vue:93–125`；实际更正在 `155–176`。
- 触发：A 的详情请求慢，关闭后打开 B；B 先返回，A 后返回。
- 问题：名单/提交/考勤异步结果无请求序号或目标 task ID 校验，A 响应覆盖 B 的共享 refs；标题仍取 props.task=B，更正却取旧 correctingRecord.id。
- 影响：管理员以为在处理 B，却提交 A 的 attendance_record_id，实际更正错误任务/学生。
- 证据：实际 Vue script 离线模拟中，当前任务 `2`，更正调用 ID `111`，该记录属于任务 `1`。后端 `attendance/service.py:206` 按 record ID 和 current_version 操作，不能从该请求恢复抽屉当前目标。
- 修复方向：每次加载绑定目标 ID/请求序号，丢弃旧响应；切任务/关抽屉清空更正目标并取消旧请求，写入前再次校验 record.task_id 与当前任务。
- 归属：HEAD 已有，非本轮同步新增。

### C02：小程序“同意异议”固定改判正常，可能写错正式考勤

- 位置：`apps/wechat-miniapp/miniprogram/api/admin.js:28`；学生诉求同类问题在 `api/record.js:12`。
- 触发：合法异议请求 LEAVE/LATE/ABSENT，管理员点击“同意”。
- 问题：页面展示诉求，但 API 固定发送 final_type=NORMAL；学生提交接口也固定 desired_type=NORMAL，不能选择其他认定。
- 影响：同意请假可能被写成正常出勤，其他合法诉求无法表达；后端照客户端 final_type 更新事实。
- 证据：实际 API script 模拟确认请求 NORMAL；`objection/schemas.py:20` 支持四种类型，`objection/service.py:408–427` 按 final_type 更正。
- 修复方向：学生显式选择合法诉求，审核显式选择/确认最终认定；不得用默认 NORMAL 替换请求含义。
- 归属：硬编码在 HEAD 已有。

## P2：需要修复的业务闭环

### B04：直接上传普通 XLSX 被误当外层 ZIP，导入必然失败

- 位置：`backend/app/modules/importer/service.py:1402–1425`。
- 触发：直接上传一个或多个 `.xlsx`，不是装有表格文件的外层 `.zip`。
- 问题：所有 XLSX 都以 PK ZIP 签名开头，展开后只看到 OOXML 内部 XML，找不到表格文件。
- 影响：正常 Excel 直接上传返回 422“未找到任何有效的表格文件”，与 UI 支持 Excel/ZIP 的入口不一致。
- 证据：openpyxl 生成合法 XLSX，调用真实 import_bulk_files，主审确认同一 422。
- 修复方向：优先识别明确的表格文件，区分 OOXML 与外层打包 ZIP，并覆盖直接 XLSX、多文件 XLSX、外层 ZIP 和损坏包测试。

### B05：候选查询越过本人范围，且 GET 会创建账号/授予角色

- 位置：`backend/app/modules/inspection/router.py:355–371`；写操作 `inspection/service.py:1571–1586`。
- 触发：普通 VOLUNTEER 持 inspection.read，调用任意学期候选或任意 task_id 的 candidate-volunteers。
- 问题：两个入口只要求 inspection.read；Service 不接受 actor，缺少管理权限和本人受派范围。学期候选读取还循环补资格角色并 commit。
- 影响：其他志愿者姓名、学号、班级、账号 ID、冲突和负载可被读取；普通 GET 改变业务身份，权限撤销可能被候选查询重新补授。
- 证据：主审核对默认角色策略、路由依赖、Service 无 actor 与 commit；独立审查者用纯 VOLUNTEER actor 离线确认返回无受派关系的其他学生。
- 修复方向：改为排班管理权限及服务层纵深复核；将预置/授角色独立成明确写流程，GET 保持只读。

### B06：单文件导入失败的部分写入被下一文件提交

- 位置：`backend/app/modules/importer/service.py:1500–1506`、`1542–1548`；confirm 的最终 commit 在 `497`，preview 的 commit 在 `233`。
- 触发：第一份文件在 flush 部分业务对象后发生普通逻辑异常，bulk 捕获后继续处理第二份文件。
- 问题：捕获分支不 rollback，复用同一 Session；下一次 preview 或 confirm 的 commit 也提交上次未回滚对象。数据库事务失败时还可能使后续文件全部 PendingRollback。
- 影响：返回首文件 FAILED，但其部分课程/排课等已经落库，用户重试可能重复或产生残缺数据。
- 证据：主审静态核对事务链路；独立审查者用真实 writer、隔离 SQLite 和替换解析器的合法标准化输入复现 `FAILED/SUCCESS`，失败文件的 PartialCourse 与排课仍可从新 Session 读到。此项未声称主审重跑了完整 writer 复现，也未验证 MySQL 并发。
- 修复方向：明确定义每文件事务，异常捕获前结束失败事务；成功/失败状态与实际持久化保持一致，覆盖“flush 后逻辑异常”“SQL 异常”“下一文件继续成功”。

### B07：修改已排班节次绕过冲突约束与版本校验

- 位置：`backend/app/modules/inspection/service.py:2155–2163`；请求 `InspectionTaskUpdateRequest`。
- 触发：已分配但未提交任务 A 为 1–2 节，同一人 B 为 3–4 节，将 A 改为 3–4 节。
- 问题：PATCH 只校验起止顺序，未校验当前受派人本人课程/其他任务、位置、截止时间，也未比对客户端 lock_version。
- 影响：接口成功后同一志愿者同时有两项重叠任务；旧页面也可覆盖新修改。
- 证据：主审内存数据库调用真实 PATCH Service，两个当前受派保持存在且时段完全重叠。
- 修复方向：复用受派日期锚点和排班约束校验，或先解除受派再编辑；添加版本入参与冲突返回。

### B08：任务删除/学期重置没有标记历史周报源已变化

- 位置：`backend/app/modules/academic/service.py:1851`；`backend/app/modules/inspection/service.py:2320–2322`。
- 触发：已有正式考勤和归档周报，强制删除相应任务或重置学期业务数据。
- 问题：考勤/任务消失，ReportSourceRevision 不递增，旧报表还保留；新鲜度仅比较同一个修订号。
- 影响：清空后旧报表仍可能显示 behind_source=False，让用户误认为报表仍反映现状。
- 证据：主审核对删除路径及 revision 比较；独立审查者隔离复现清空前后 revision 都为 4、任务变 0。
- 修复方向：删除前收集受影响学期/周次，同事务递增源修订；历史版本保留并明确显示源已改变。

### C03：课表导出使用不存在的 localStorage access token

- 位置：`apps/admin-web/src/api/academic.ts:471`。
- 触发：正常登录后点击导出学期课表。
- 问题：登录/刷新把 token 保存在 http.ts 模块内存，导出却读取 localStorage，发送空 Bearer。
- 影响：正常会话的导出返回 401，绕开统一请求刷新/错误处理。
- 证据：实际 exporter script 模拟请求 `Authorization: Bearer `；登录写内存见 `api/auth.ts:27/36`，后端依赖拒绝空 Bearer。
- 修复方向：共用受认证的二进制请求 helper 和至多一次刷新，不能通过将 token 写 localStorage 来掩盖问题。

### C04：逾期任务落入只读模板，无法补交

- 位置：`apps/wechat-miniapp/miniprogram/pages/task/detail/index.wxml:13`，只读分支 `99–101`。
- 触发：本人当前受派未提交任务超过截止，后端状态变“已逾期”。
- 问题：表单只在“待执行”渲染，逾期落入归档/锁定提示。
- 影响：后端允许并记录 late_at_submission 的补交流程在小程序没有入口。
- 证据：实际 WXML 分支与 `inspection/service.py:913/2702–2725` 核对；属于静态门禁验证，没有宣称真机渲染。
- 修复方向：对可补交的本人当前受派同时支持“已逾期”，提交后刷新状态，保持既有截止快照。

### C05：小程序证明图片 DTO 错配，且响应中的裸下载 URL 不可直接使用

- 位置：`apps/wechat-miniapp/miniprogram/pages/admin/index.wxml:21`、`pages/admin/index.js:37–47`；后端 `objection/service.py:619`、`file/router.py:71–72`。
- 触发：异议带有证明材料，管理者打开审核列表。
- 问题：WXML 读取 proofs，后端返回 file_ids/files，JS 没有映射；后端 files.access_url 又是无 expires/sig 的裸下载路径。
- 影响：证明区不显示；即使仅改字段名，裸 URL 仍因缺签名参数返回 422，无法可靠审查材料。
- 证据：实际页面映射后 proofs 为 undefined；下载路由明确要求 expires/sig。
- 修复方向：按 file_ids 申请经授权 `/files/{id}/access` 的签名 URL，再提供可预览图片列表；不能让客户端自行拼造签名。

### C06：任务中心只加载首 200 条，搜索/筛选/换班计数不完整

- 位置：`apps/admin-web/src/views/TaskListView.vue:105–114`。
- 触发：某周任务超过 200 条。
- 问题：只请求一页，忽略 total，没有翻页或后续加载；客户端过滤均遍历这份截断数据。
- 影响：后续任务、调班申请无法通过页面检索/处理，数量显示不完整。
- 证据：实际 Vue script 模拟 total=201，仅一次请求/200 条缓存；后端 repository 真正执行 limit/offset。
- 修复方向：服务端分页过滤或有界加载全部页，显示总量；同步检查 Web 异议首 50 条和小程序考勤/异议首 20 条的同类截断，避免误认不存在异议。

### C07：新异议进度将初核通过显示为驳回

- 位置：`apps/wechat-miniapp/miniprogram/pages/record/list/index.wxml:79–80`；JS 对应初核状态映射在 `66`。
- 触发：initial_status=PASSED、final_status=PENDING。
- 问题：界面比较 APPROVED，而初核真实枚举为 PASSED；详情走“初核驳回”分支。
- 影响：学生误以为申请被驳回，可能重复联系或再次申诉，初核和终审进度含义混淆。
- 证据：实际 JS 模拟及 WXML 条件核对，后端初核枚举在 `objection/schemas.py:21`。
- 修复方向：使用真实枚举并分别映射初核/终审；覆盖 PENDING/PASSED/REJECTED 与终审组合。
- 归属：此次同步引入的新进度实现存在该问题；本轮按审查范围记录，尚未修改上游业务逻辑。

### C08：人工原因/备注在客户端被重新强制必填

- 位置：小程序 `pages/record/appeal/index.js:63`、`pages/task/detail/index.js:260`、`pages/admin/index.js:94`；Web `TaskDrawer.vue:167`、`ObjectionsView.vue:148/191`。
- 触发：真实业务字段合法，用户留空人工说明。
- 问题：页面在调用 API 前 return 或弹窗校验拦截，与用户“原因类都改成选填”和后端默认空字符串/可省略 schema 不一致。
- 影响：合法空说明的申诉、调班、更正、驳回无法在客户端完成。
- 证据：实际学生申诉 JS 模拟确认空理由时未调用 API；其他入口静态核对。
- 修复方向：删除原因类必填门禁并标注选填；保留判定类型、权限、版本、长度和审计约束。调班属于原有本地未提交功能，其余多个门禁在 HEAD 已有。

## 证据校准与未纳入的疑点

- `inspection/service.py` 确实错误导入不存在的 ObjectionProof 并吞异常，但正常 FK 为 attendance_record → objection → objection_file 级联删除。不能仅凭该 import 错误宣称异议会残留；仍应清理错误导入和吞异常。
- 当前未提交改派代码已同步批准 pending 调班申请，不能再报告“改派后遗漏审批”。其并发锁顺序还需隔离 MySQL 专项验证。
- Node 测试对已删除 `api/file.js`、旧 session API、旧页面方法和 VM 注入依赖仍有引用；这部分要维护测试，不能逐条叫作用户可见 bug。另有分页、补交、认定类型等实际回归已独立确认。
- 上游最新版本已恢复双令牌与串行 401 刷新，不能继续用同步前“刷新机制不存在”的结论描述本次最终代码。令牌刷新失败分类、上传刷新、重放/登出等仍需要专项验收。
- 文件存储 object/COS/OSS 仍未实现；生产 SHA、迁移 head、权限 seed 是否生效，本轮未核对。
- 根 README 和文档仍有过时状态；存储 OpenAPI 92 路径/112 操作，实际工作区 109 路径/134 操作，缺 22 个操作并有重复 operation ID 警告。此为文档/契约维护项，不计入上述 16 项业务缺陷。

## 建议修复顺序

1. B01/B02：先建立账号预置来源、绑定合并及管理角色保护的失败回归，再修身份生命周期。
2. B03/C01/C02：阻止既有事实被抹写及错任务/错认定写入；补异步时序、STOP/已入账/已结算组合测试。
3. B04/B06/B05/B07：完善导入事务、候选权限及编辑后排班约束；MySQL 专项验证外键、锁序与提交原子性。
4. C03–C08/B08：修复双端功能入口、分页、证明访问和版本周报新鲜度，同时维护旧测试。
5. 同步 OpenAPI、索引、README 和验收资料，执行独立 MySQL 全量及浏览器/真机验证后再评估发布。

后续修复应保持本次原有脏文件来源可辨认，每项以可失败回归和实际行为作为验收，不通过关闭门禁、删测试或修改历史测试数字制造“全绿”。
