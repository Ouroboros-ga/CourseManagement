# 共用逻辑手工测试流程包

用途：供后续开发者使用虚构数据，核对稳定业务规则和 API。以接口行为为准，页面重构后仍适用。此包不运行、不连接环境，也不证明功能已经验收。

本轮不补生产归属、不整理真实名单、不执行本包。真实数据在正式使用时由用户导入或维护。无需为了测试准备全校数据。

## 环境和最小样例

使用一个独立开发/测试环境及测试数据库；业务测试需要的开关只在该环境配置，不修改生产。先按现有部署说明迁移到 `f26a1015f001`，创建以下少量虚构数据；复用已有导入/维护 API，无需增加测试专用业务接口。

| 实体 | 虚构内容 |
| --- | --- |
| 学校 | TEST_演示学校 |
| 学院 | TEST_A学院、TEST_B学院 |
| 账号 | TEST_超管、TEST_A教师、TEST_B教师、TEST_志愿者甲、TEST_志愿者乙、TEST_学生甲 |
| 学期 | TEST_演示学期，起止日期涵盖选择的实验日 D，D 为未来教学日，首周一和周次一致 |
| 行政班 | 两院各一班，学生每院 2—3 人；虚构学号用 9900000001、9900000002 等，姓名用测试甲等 |
| 课程与教学班 | A院早自习、普通课、晚自习各一班；B院普通课一班；均具有明确归属和课程类型 |
| 组与成员 | A早自习组只查早自习；A常规组只查普通课；甲同时加入两组，乙加入一组；成员有效期覆盖 D |
| 课表 | D 有上述课次，便于用同一个模板检查时间、筛选与冲突 |

不要硬编码数据库 ID；记录创建响应中的 ID，填入下面占位符。认证沿用现有登录流程。使用 API 客户端/开发环境 `/docs`，无须编写新页面；线上公开 OpenAPI 不保证可访问，契约使用仓库 `docs/openapi.json`。

引用草稿及正式业务需测试环境的配置、学院基础数据、业务隔离、组织排班开关开启。学校模板维护本身只需学院配置开关。

## API 操作约定

所有路径加 `/api/v1`。成功数据在 `data` 中。

- `S`：学校 ID；`A/B`：学院 ID；`SEM`：学期 ID。
- `T`：模板 ID；`V1/V2`：模板不可变版本 ID（不是整数版本号）；`P`：学院方案 ID。
- `BASE=/colleges/A/academic/semesters/SEM/time-versions`。
- `D`：学期内实验日，使用 `YYYY-MM-DD`；钟表时间按北京时间解释。
- POST/PATCH 使用 JSON，认证头或 Cookie 来自测试账号。不要把认证信息写入验收文件。

## 学校模板主流程（T01—T07）

### T01 创建并保存基线

超管 POST `/schools/S/time-templates`，请求体使用 [template-v1.json](template-v1.json)。GET 同一路径，记录 `T、lock_version、latest.id=V1`。GET `/schools/S/time-templates/T/versions`，应只有 v1，包含 4 个节次、完整稳定标识和名称。

### T02 学院复制后独立修改

A教师 GET `/colleges/A/time-templates`；POST `BASE/profiles/from-template`：

```json
{"template_version_id":"V1","name":"TEST_A独立作息","effective_from":"D"}
```

将 V1、D 替换为实际值。返回 `DRAFT`、`source_template_version_id=V1`。GET `BASE/profiles` 找到 P，保留初始响应。

PATCH `BASE/profiles/P`，发送 `{name,lock_version,configuration}`（configuration 从响应复制），把早自习改为 `07:05—07:35`。重读确认保存成功；学校 v1 仍为 `07:00—07:30`。再用 B教师尝试读取/编辑 A的 P，应拒绝且 A草稿不变。

### T03 模板更新只提示

超管 PATCH `/schools/S/time-templates/T`，使用 [template-v2-content.json](template-v2-content.json) 并增加当前 `lock_version`。GET 目录记录 V2。历史应同时有 v1/v2，v1内容不变。

A教师 GET `/colleges/A/academic/semesters/SEM/time-template-updates`：返回 P，`source_version=1、latest_version=2、update_available=true`。重读 P，应仍为自己修改的 `07:05—07:35`、来源 V1、原状态；不自动发布或改写。B学院未引用时提示为空。重复读取提示不产生已读/采用状态。

### T04 明确采用新版与发布

引用 V2，名称用 `TEST_A新版作息`，应创建新的 P2，而非覆盖 P。可修改 P2后保存。

GET `BASE/profiles/P2/preview` 得到 revision；POST `BASE/profiles/P2/publish`：

```json
{"lock_version":1,"revision":"填入刚取得的revision","confirm_existing_tasks":true}
```

`lock_version` 使用刚读取的实际版本，不能总写 1。再 POST `BASE/profiles/teaching-classes/教学班ID/binding/preview`，请求 `{profile_id:"P2"}`；拿到 revision 后 POST 去掉 `/preview` 的路径，请求 `{profile_id:"P2",revision:"…"}`。后续实际课次使用 P2；未绑定的教学班仍跟随默认配置。

### T05 已生成任务保持快照

本项只需一个样本：先将普通课教学班绑定已发布的旧方案，生成 D 的任务，记录任务 ID、实际起止时间、来源版本和受派。随后发布并绑定新方案。

重读旧任务：时间、来源和受派不应被模板更新或绑定覆盖；按现有规则产生未来影响项。另选一个尚未生成任务的日期生成新课次，应使用新方案时间。不要用同一课次生成第二份任务来验证新时间。

### T06 停用和恢复

超管 POST `/schools/S/time-templates/T/status`，`{lock_version:当前版本,status:"INACTIVE"}`。学院再次引用 V1或V2均409；原草稿可继续编辑，原正式方案/任务不变；更新提示显示停用状态。恢复 ACTIVE 后可再次引用。DELETE 没有业务删除入口，不应返回删除成功。

### T07 一组失败场景即可

| 操作 | 预期 |
| --- | --- |
| A教师直接调用学校模板写接口 | 403，模板不变 |
| 使用旧 lock_version 再次修改模板 | 409，没有额外版本 |
| 两节 slot_id 相同、节次号相同、时间重叠、跨午夜、空节次名、带秒或时区 | 422，无写入 |
| 引用已不存在的版本或其他学校版本 | 404，不创建草稿；单校环境跨学校项标记不适用 |
| 生效日期不在学期内、学期已停用 | 拒绝，草稿数不增加 |
| 重复引用且草稿同名 | 409，只有一个草稿 |

## 共用业务逻辑最小回归（后续按需执行一次）

这些用例不依赖旧页面布局；按照 [API索引](../../API_INDEX.md) 和 [OpenAPI](../../openapi.json) 填写当前请求结构，不另造接口或改契约适配页面。

| 编号 | 操作 | 核心预期 |
| --- | --- | --- |
| C01 学院范围 | A教师列表、计数、详情只见A；B教师拿A资源ID访问；混合A/B ID提交一次批量请求 | 列表与计数一致；越权拒绝；失败批次无部分写入 |
| C02 类型先筛后抽 | A早自习组抽取1节；再要求超过早自习总数的配额 | 第一次只有早自习；不足明确拒绝，不能用普通课/晚自习补齐 |
| C03 排班确认与跨组冲突 | `/colleges/A/groups/G/inspection/assignment-plans/preview` 后明确提交；另一组给同人重叠时间；改变规则后提交旧计划 | BLOCK拒绝；WARN须具体确认；旧计划409；重复提交不重复受派；排班失败保留任务 |
| C04 不可用全组生效 | 某组发起不可用，经影响预览后批准，再在两个组给该人新增重叠排班 | 两组都拒绝；原受派保留并产生影响项；考勤事实不被自动改变 |
| C05 发布与个人课表隔离 | 正式教务发布，学生绑定/初始化同学期；本人改一条、增一条、删一条，再次正式发布、重复初始化 | 私人增删改保留；不覆盖；`/me/academic-notices`展示更新；私人改动不影响正式忙碌/查课/考勤 |
| C06 历史与版本 | 更改作息或组配置后读取原任务、提交和考勤；用旧版本写一次 | 历史快照及实际操作人不变；陈旧版本拒绝，不悄悄覆盖 |

每个编号只需少量代表性样本；某项失败先记录并定位，不重复跑全套、不扩展成全校数据清洗。页面重构时可替换操作入口，保留相同请求和结果断言。

## 记录与收尾

复制 [RESULT.md](RESULT.md) 记录环境、版本、用例、HTTP状态与必要字段；不保留 token或完整学生资料。测试结束保留/还原整个独立测试环境即可，不对生产执行清空命令。模板与历史版本不通过业务删除接口清理。

此包不包括组织学期复制或负责人完整交接的验收：两项仍待补开发，不能用现有组编辑接口冒充已完成。
