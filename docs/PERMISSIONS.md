# 查课管理系统 V1.0 业务资源与权限策略

| 项目 | 内容 |
|---|---|
| 文档版本 | V1.1（2026-09-20，明确教师角色管理边界） |
| 日期 | 2026-09-20 |
| 适用系统 | 查课管理系统 V1.0 |
| 依据 | 《查课管理系统 V1.0 建设说明》《查课管理系统 V1.0 开发技术方案》及最终确认的角色、身份与授权规则 |
| 文档性质 | 权限设计基线，可直接用于 PermissionCode、默认角色权限、业务模块权限策略、API 授权与测试实现 |

> 项目同步说明：本文依据用户提供的《查课管理系统_V1.0_业务资源与权限策略.md》，并纳入教师不得互相授予或撤销教师角色的补充规则。设计采纳不代表代码已实现或数据库已赋权；项目接入细节、静态核对差距及验收补充见 [权限实施对照](./PERMISSIONS_IMPLEMENTATION.md)。与旧草案冲突的规则以本文为准。

---

## 0. 设计原则

本系统用于学院内部查课、审核、电子留档、异议处理和统计查询。权限设计以业务清晰、后端强制校验、关键操作可追溯为原则，不建设复杂企业级 IAM、动态组织树或通用数据范围引擎。

权限判断由以下要素共同决定：

```text
Role
+ Permission
+ 业务身份
+ 资源关系
+ 当前状态
+ 数据范围
```

其中：

- `Role` 描述用户身份和默认功能来源。
- `Permission` 描述是否允许执行某类业务操作。
- 业务身份用于判断学生、志愿者等业务资格。
- 资源关系用于判断本人任务、本人考勤、本人异议等归属。
- 当前状态用于限制审核、取消、改派、提交等操作时机。
- 数据范围用于限制管理类查询的可见范围。
- 前端菜单、按钮隐藏仅用于交互，不能替代后端授权。

V1.0 固定五类角色：

```text
SUPER_ADMIN
TEACHER_ADMIN
STUDENT_AFFAIRS_MANAGER
VOLUNTEER
STUDENT
```

未绑定微信用户不新增第六个角色，只使用受限会话状态。

---

# 1. 角色与身份生命周期

## 1.1 SUPER_ADMIN

超级管理员拥有本系统最高管理权限。

职责：

- 管理所有账号。
- 管理所有角色。
- 管理所有功能权限。
- 管理系统配置。
- 查看系统审计。
- 管理教师管理员和学生工作负责人。
- 可授予或撤销 `TEACHER_ADMIN`、`STUDENT_AFFAIRS_MANAGER` 等管理角色。
- 只有超级管理员可以授予或撤销 `SUPER_ADMIN`。

超级管理员不因角色身份自动获得“代学生提交异议”或“代志愿者查课提交”的业务身份。

---

## 1.2 TEACHER_ADMIN

教师管理员负责当前学院内日常系统管理和查课业务管理。

教师管理员具有当前学院范围内的 `role.assign`，但存在以下边界：

```text
允许：
- 授予 / 撤销 STUDENT_AFFAIRS_MANAGER
- 手工角色分配的允许列表仅为 STUDENT_AFFAIRS_MANAGER
- 配置学生工作负责人的可选权限

禁止：
- 授予 SUPER_ADMIN
- 撤销 SUPER_ADMIN
- 授予 / 撤销 TEACHER_ADMIN（包括自己的教师角色）
- 将自己提升为 SUPER_ADMIN
```

`STUDENT` 和 `VOLUNTEER` 原则上由业务状态自动维护，不作为教师日常手工角色分配对象。

---

## 1.3 STUDENT_AFFAIRS_MANAGER

学生工作负责人负责学院范围内日常查询、协助核验和部分管理工作。

其权限模型采用：

```text
基础权限
+
可配置权限
```

基础权限用于正常开展学院工作，可配置权限由教师管理员逐人开启或关闭。

V1.0 默认可配置项：

```text
statistics.read
report.read
objection.initial_review
```

学生工作负责人：

- 可查看全学院学生名单和考勤。
- 可查看全学院任务和排班。
- 可查看完整提交截止时间配置及历史版本。
- 可签发绑定码、作废绑定码、协助学生换绑。
- 具有 `objection.initial_review` 时，可读取全学院全部异议及历史记录，并执行初核。
- 统计和周报权限按个人配置决定。
- 不具有终审、更正最终考勤、生成周报、任务生成、自动排班、全局角色管理等管理权限，除非未来版本另行明确。

学生工作负责人的权限改变后，下一次 API 请求立即按最新权限生效。

---

## 1.4 STUDENT

`STUDENT` 不要求管理员手工分配。

当用户成功绑定有效 `student_id` 后，系统自动建立学生业务身份并获得 `STUDENT` 角色。

条件：

```text
有效用户
+
有效 student_id
+
学生记录有效
```

学生解除绑定、账号停用或学生身份失效后，系统按业务规则使其学生权限失效。

学生只能访问本人：

- 本人信息。
- 本人考勤。
- 本人考勤历史。
- 本人异议。
- 本人异议材料和处理结果。

---

## 1.5 VOLUNTEER

志愿者采用“角色 + 学期资格”双重模型。

每学期通过 Excel 导入志愿者资格：

```text
volunteer_qualification
semester_id
student_id
enabled
```

维护规则：

1. 首次获得有效志愿者资格时，系统自动维护 `VOLUNTEER` 身份。
2. 志愿者资格有效期为一个学期。
3. 每学期重新导入或维护该学期资格。
4. 学期中支持启用、停用。
5. 是否能执行查课，以当前学期有效资格为准。
6. 仅具有 `VOLUNTEER` 角色但当前学期无有效资格，不允许提交查课结果。

实际提交条件：

```text
VOLUNTEER
AND 当前学期 volunteer_qualification.enabled = true
AND 当前用户仍是任务受派人
AND 任务状态允许提交
```

---

## 1.6 未绑定微信用户

未绑定微信用户不设置额外 Role。

微信登录成功、但尚未绑定 `student_id` 时，进入受限会话状态：

```text
PRE_BINDING
```

允许访问：

```text
GET  /me
POST /me/student-binding
POST /auth/refresh
POST /auth/logout
```

禁止访问：

- 学生考勤。
- 学生异议。
- 志愿者任务。
- 学生名单。
- 查课业务。
- 统计与周报。
- 任何管理业务 API。

绑定成功后：

```text
写入有效 student_id
→ 自动获得 STUDENT
→ 后续请求进入正常业务身份
```

---

# 2. 业务模块与受保护资源

| 功能域 | 工程模块 | 受保护资源 |
|---|---|---|
| 身份与平台 | identity | 用户账号、角色关系、个人权限、微信身份、会话、绑定码、换绑 |
| 基础数据 | academic | 学期、节次、校历、行政班、学生、课程、教学班、课程安排、开课周次、志愿者资格 |
| 导入 | academic / import | Excel 模板、上传文件、导入批次、解析预览、错误报告 |
| 任务与排班 | inspection | 查课任务、名单快照、任务生成、任务取消、排班、调班申请、截止时间 |
| 查课执行 | inspection | 本人任务、任务学生名单、查课提交、异常学生、提交照片、历史 attempt |
| 审核与考勤 | attendance | 待审核提交、审核结果、应到人数、当前考勤、历史认定、更正 |
| 学生服务 | attendance / objection | 本人考勤、本人异议、证明材料、处理结果 |
| 异议处理 | objection | 异议列表、证明材料、初核、终审、历史处理记录 |
| 统计与周报 | report | 到课率、缺勤率、未完成任务、周报、历史版本、Excel |
| 文件 | file | 临时文件、已关联文件、短时访问链接 |
| 审计与配置 | audit / core | 审计日志、业务配置、材料保留策略 |

所有返回个人信息的列表、搜索、自动补全、统计明细、错误报告、下载接口均属于受保护操作。

---

# 3. Permission 设计规则

## 3.1 权限粒度原则

满足以下任一条件时，应拆分独立 Permission：

- 授权人员不同。
- 操作后果不同。
- 是否属于可选权限不同。
- 数据敏感程度明显不同。
- 需要独立审计或业务状态约束。

普通列表与详情可以共用 `read`。

数据库行范围不通过不断增加 Permission 名称表达，而由模块自身的数据范围策略处理。

---

# 4. Permission 注册表

## 4.1 身份与账号

| Permission | 说明 |
|---|---|
| `account.read` | 管理账号读取 |
| `account.manage` | 创建、修改、停用、启用、管理重置、撤销会话 |
| `role.assign` | 在授权边界内授予或撤销用户角色 |
| `optional_permission.manage` | 配置学生工作负责人可选权限 |
| `identity.binding.manage` | 签发/作废绑定码、执行核验换绑 |

---

## 4.2 基础数据

| Permission | 说明 |
|---|---|
| `academic.read` | 学期、班级、课程、课表读取 |
| `academic.manage` | 学期、班级、课程、课表维护 |
| `student.read` | 学生、教学班名单读取 |
| `student.manage` | 学生、教学班名单维护 |
| `volunteer.read` | 志愿者资格读取 |
| `volunteer.manage` | 志愿者资格导入、启停、维护 |
| `import.execute` | Excel 导入、预览、确认和错误结果读取 |

---

## 4.3 查课任务与排班

| Permission | 说明 |
|---|---|
| `inspection.read` | 查课任务读取，包含当前排班基本信息 |
| `inspection.generate` | 查课任务预览与生成 |
| `inspection.cancel` | 取消任务 |
| `inspection.roster.read` | 查课任务名单快照读取 |
| `inspection.roster.manage` | 执行前修订任务名单、照片要求 |
| `assignment.manage` | 自动排班、人工改派 |
| `assignment.change_request` | 志愿者创建和读取本人调班申请 |
| `assignment.change_review` | 管理人员读取和处理调班申请 |
| `submission_deadline.read` | 读取默认/指定日期截止时间和历史版本 |
| `submission_deadline.manage` | 修改默认或指定日期截止时间 |

---

## 4.4 查课执行与审核

| Permission | 说明 |
|---|---|
| `submission.create` | 志愿者提交本人查课结果 |
| `submission.read` | 读取查课提交、异常学生、驳回意见和历史 attempt |
| `submission.review` | 审核查课提交 |
| `attendance.expected_count_adjust` | 调整应到人数及必要分班人数 |
| `attendance.read` | 当前考勤及历史认定读取 |
| `attendance.correct` | 更正最终考勤并追加版本 |

---

## 4.5 统计、周报和异议

| Permission | 说明 |
|---|---|
| `statistics.read` | 班级/课程统计、未完成任务和待审核统计 |
| `report.read` | 周报主记录、历史版本和 Excel 下载 |
| `report.generate` | 生成新的周报版本 |
| `objection.create` | 学生创建本人异议 |
| `objection.read` | 读取异议 |
| `objection.initial_review` | 异议初核 |
| `objection.final_review` | 异议终审 |
| `audit.read` | 系统审计日志读取 |
| `system.config.read` | 系统业务配置读取 |
| `system.config.manage` | 系统业务配置维护 |

---

# 5. 默认角色权限矩阵

说明：

- “是”表示默认拥有。
- “可选”表示由教师管理员逐人配置。
- “自动”表示由业务身份自动产生，不作为日常手工角色授权。
- “否”表示该角色没有该权限来源。
- 权限存在不代表拥有无限数据范围。

| Permission | 超管 | 教师管理员 | 学生工作负责人 | 志愿者 | 学生 |
|---|:---:|:---:|:---:|:---:|:---:|
| account.read | 是 | 否 | 否 | 否 | 否 |
| account.manage | 是 | 否 | 否 | 否 | 否 |
| role.assign | 是 | 是 | 否 | 否 | 否 |
| optional_permission.manage | 是 | 是 | 否 | 否 | 否 |
| identity.binding.manage | 是 | 是 | 是 | 否 | 否 |
| academic.read | 是 | 是 | 否 | 否 | 否 |
| academic.manage | 是 | 是 | 否 | 否 | 否 |
| student.read | 是 | 是 | 是 | 否 | 否 |
| student.manage | 是 | 是 | 否 | 否 | 否 |
| volunteer.read | 是 | 是 | 否 | 否 | 否 |
| volunteer.manage | 是 | 是 | 否 | 否 | 否 |
| import.execute | 是 | 是 | 否 | 否 | 否 |
| inspection.read | 是 | 是 | 是 | 是 | 否 |
| inspection.generate | 是 | 是 | 否 | 否 | 否 |
| inspection.cancel | 是 | 是 | 否 | 否 | 否 |
| inspection.roster.read | 是 | 是 | 是 | 是 | 否 |
| inspection.roster.manage | 是 | 是 | 否 | 否 | 否 |
| assignment.manage | 是 | 是 | 否 | 否 | 否 |
| assignment.change_request | 否 | 否 | 否 | 是 | 否 |
| assignment.change_review | 是 | 是 | 否 | 否 | 否 |
| submission_deadline.read | 是 | 是 | 是 | 否 | 否 |
| submission_deadline.manage | 是 | 是 | 否 | 否 | 否 |
| submission.create | 否 | 否 | 否 | 是 | 否 |
| submission.read | 是 | 是 | 否 | 是 | 否 |
| submission.review | 是 | 是 | 否 | 否 | 否 |
| attendance.expected_count_adjust | 是 | 是 | 否 | 否 | 否 |
| attendance.read | 是 | 是 | 是 | 否 | 是 |
| attendance.correct | 是 | 是 | 否 | 否 | 否 |
| statistics.read | 是 | 是 | 可选 | 否 | 否 |
| report.read | 是 | 是 | 可选 | 否 | 否 |
| report.generate | 是 | 是 | 否 | 否 | 否 |
| objection.create | 否 | 否 | 否 | 否 | 是 |
| objection.read | 是 | 是 | 条件派生 | 否 | 是 |
| objection.initial_review | 是 | 是 | 可选 | 否 | 否 |
| objection.final_review | 是 | 是 | 否 | 否 | 否 |
| audit.read | 是 | 否 | 否 | 否 | 否 |
| system.config.read | 是 | 否 | 否 | 否 | 否 |
| system.config.manage | 是 | 否 | 否 | 否 | 否 |

---

# 6. 角色授权边界

## 6.1 role.assign

超级管理员：

```text
可管理所有角色
包括 SUPER_ADMIN
```

教师管理员：

```text
可在当前学院范围内授予或撤销 STUDENT_AFFAIRS_MANAGER
不能授予或撤销 SUPER_ADMIN、TEACHER_ADMIN（包括自己的教师角色）
```

只有超级管理员可授予或撤销教师角色。完整角色集合更新必须检查增删差集；教师不能通过省略已有教师/超管角色、批量请求或账号编辑旁路撤销这些角色。目标已有教师角色时，可保留它并调整负责人角色；不得修改受保护角色。撤销负责人角色时一并清除其个人可选授权，重新授予不自动恢复。

对于 `STUDENT` 和 `VOLUNTEER`：

- 不作为常规手工角色管理对象。
- `STUDENT` 由有效学生绑定自动维护。
- `VOLUNTEER` 由学期志愿者资格自动维护。
- `role.assign` 不应破坏其业务状态来源。

---

## 6.2 学生工作负责人可配置权限

V1.0 可配置清单固定为：

```text
statistics.read
report.read
objection.initial_review
```

只有这三个 code 可以通过个人权限配置接口授予或撤销。

教师管理员：

- 可给学生工作负责人开启或关闭。
- 不允许通过该接口授予任意其他 Permission。
- 不修改角色默认权限。
- 不通过该接口给自己提权。
- 不通过该接口修改超级管理员权限。

学生工作负责人角色被撤销时，其个人可选授权同时失效。

重新授予角色时，不自动恢复历史可选开关，需重新明确配置。

---

# 7. 数据范围策略

## 7.1 SYSTEM_WIDE

具有对应管理权限时，可查询当前系统、当前学院业务范围内数据。

适用：

- 超级管理员。
- 教师管理员。
- 部分管理操作。

该范围不等于跨学校或跨租户通配。

---

## 7.2 ALL_GRADES

当前学院全部年级。

主要适用学生工作负责人：

- 学生名单。
- 查课任务。
- 排班。
- 当前考勤。
- 截止时间配置。
- 授权后的统计、周报和异议初核。

---

## 7.3 SELF_STUDENT

```text
resource.student_id = current_user.student_id
```

用于：

- 本人考勤。
- 本人异议。
- 本人证明材料。
- 本人认定历史。

未绑定 `student_id` 时直接拒绝，不能退化成无范围查询。

---

## 7.4 ASSIGNED_TASK

```text
assignment.volunteer_user_id = current_user.id
```

用于志愿者：

- 查看本人当前任务。
- 读取当前任务名单。
- 搜索任务内学生。
- 提交查课结果。

提交时还必须重新验证：

- 当前学期志愿者资格。
- 账号有效。
- 任务未取消。
- 仍为当前受派人。
- 当前状态允许提交。

---

## 7.5 OWN_SUBMISSION

用于志愿者读取本人历史提交。

即使志愿者：

- 被改派。
- 当前资格停用。
- 学期结束。

仍允许只读查看本人历史参与信息，包括：

- 当时任务基本信息。
- 自己当时的排班信息。
- 自己提交的结果。
- 自己提交的异常学生记录。
- 审核结果和驳回意见。
- 自己提交的照片。

但不能：

- 再次提交。
- 修改历史提交。
- 读取改派后新增的执行信息。
- 继续读取不再需要的任务当前完整名单。
- 以历史身份继续执行任务。

原则：

```text
历史参与关系提供只读权
当前分配关系提供操作权
```

---

## 7.6 OWN_OBJECTION

```text
objection.student_id = current_user.student_id
```

学生只允许读取：

- 本人异议理由。
- 本人证明。
- 允许公开的处理意见。
- 最终结果。
- 本人相关更正历史。

---

## 7.7 FILE_PARENT

文件不能仅凭 `file_id` 授权。

访问链：

```text
file_id
→ 查找真实业务关联
→ 判断父资源
→ 检查父资源 Permission + 数据范围
→ 检查附件类别
→ 检查文件状态和有效期
→ 签发短时访问 URL
```

---

# 8. 异议权限规则

## 8.1 学生

学生只处理本人异议。

权限：

```text
objection.create
objection.read
```

范围：

```text
SELF_STUDENT / OWN_OBJECTION
```

---

## 8.2 学生工作负责人

只有在拥有：

```text
objection.initial_review
```

时，才获得管理异议读取路径。

获得初核权限后：

- 可读取全学院全部异议。
- 可读取全学院异议历史。
- 可读取关联考勤。
- 可读取完成初核所需证明材料。
- 可执行初核。

没有初核权限时：

- `attendance.read` 不自动带来异议证明读取权限。
- 不能读取全学院异议详情和证明材料。

初核不能直接修改最终考勤。

---

## 8.3 教师管理员与超级管理员

教师管理员和超级管理员：

- 可读取全学院异议。
- 可执行初核。
- 可执行终审。
- 终审需要更正考勤时，必须同时具备 `attendance.correct`。

---

# 9. 绑定码和换绑

## 9.1 可执行角色

以下角色拥有 `identity.binding.manage`：

```text
SUPER_ADMIN
TEACHER_ADMIN
STUDENT_AFFAIRS_MANAGER
```

可执行：

- 签发一次性绑定码。
- 作废未使用绑定码。
- 核验后解除绑定。
- 核验后重新绑定。
- 撤销旧会话。

---

## 9.2 业务要求

绑定码：

- 使用安全随机数生成。
- 服务端只保存摘要。
- 设置有效期。
- 设置失败次数限制。
- 成功核销后立即失效。
- 明文只在签发时显示一次。

换绑：

```text
工作人员线下核验
→ 执行换绑
→ 修改绑定关系
→ 撤销旧会话
→ 写入审计日志
```

考勤查看权限不自动带来账号安全字段读取权限。

不得向工作人员返回：

- 密码摘要。
- refresh token 摘要。
- 微信 session_key。
- AppSecret。
- 其他秘密字段。

---

# 10. 截止时间权限

学生工作负责人默认具备：

```text
submission_deadline.read
```

可读取：

- 默认每日截止时间。
- 指定日期截止时间。
- 历史版本。
- 修改人和修改时间。
- 相关业务说明。

只有教师管理员和超级管理员具备：

```text
submission_deadline.manage
```

可修改：

- 默认截止时间。
- 指定日期截止时间。

修改必须：

- 记录原因。
- 追加版本。
- 写审计。
- 不改写历史提交已有的逾期事实。

---

# 11. 复合操作权限

| 业务操作 | 必须满足 |
|---|---|
| 导入学生/教学班名单 | `import.execute` AND `student.manage` |
| 导入课表/教学班基础信息 | `import.execute` AND `academic.manage` |
| 导入志愿者资格 | `import.execute` AND `volunteer.manage` |
| 审核查课提交 | `submission.review` AND `submission.read` + 合法状态 |
| 自动或人工排班 | `assignment.manage` + 时间冲突/本班回避/资格检查 |
| 周报生成 | `report.generate` AND `report.read` |
| 异议终审并更正考勤 | `objection.final_review` AND `attendance.correct` + 版本一致 |
| 读取异议证明 | 合法管理异议读取路径 OR 本人异议路径 |
| 获取文件短时链接 | 父资源读取权 + FILE_PARENT + 文件状态有效 |

复合操作必须由同一业务 Service 完成，不能让客户端通过分步调用底层接口绕过权限组合。

---

# 12. API 权限映射

所有业务 API 以 `/api/v1` 为前缀。

## 12.1 身份

| API | 权限/条件 |
|---|---|
| `POST /auth/web/login` | 凭证校验、账号状态、限流 |
| `POST /auth/wechat/login` | 微信 code 校验、账号状态 |
| `POST /auth/refresh` | 有效 refresh 凭证 |
| `POST /auth/logout` | 当前会话 |
| `GET /me` | 当前有效会话 |
| `POST /me/student-binding` | PRE_BINDING + 一次性绑定码 |

---

## 12.2 账号与角色

| API | 权限/条件 |
|---|---|
| `GET /users` | `account.read` |
| `GET /users/{id}` | `account.read` |
| `POST /users` | `account.manage` |
| `PATCH /users/{id}` | `account.manage` |
| `PUT /users/{id}/roles` | `role.assign` + 角色边界 |
| `POST /users/{id}/password-reset` | `account.manage` |
| `POST /users/{id}/session-revocations` | `account.manage` |
| `GET /users/{id}/optional-permissions` | `optional_permission.manage` |
| `PUT /users/{id}/optional-permissions/{code}` | `optional_permission.manage` + 三项许可清单 |

---

## 12.3 绑定

| API | 权限/条件 |
|---|---|
| `POST /students/{id}/binding-tokens` | `identity.binding.manage` |
| `POST /binding-tokens/{id}/revoke` | `identity.binding.manage` |
| `POST /users/{id}/student-binding-reset` | `identity.binding.manage` + 线下核验 |

---

## 12.4 基础数据

| API | 权限 |
|---|---|
| `/semesters` | `academic.read/manage` |
| `/period-definitions` | `academic.read/manage` |
| `/calendar-overrides` | `academic.read/manage` |
| `/administrative-classes` | `academic.read/manage` |
| `/courses` | `academic.read/manage` |
| `/teaching-classes` | `academic.read/manage` |
| `/course-schedules` | `academic.read/manage` |
| `/students` | `student.read/manage` |
| `/volunteer-qualifications` | `volunteer.read/manage` |

---

## 12.5 导入

| API | 权限 |
|---|---|
| `GET /import-templates/{type}` | 对应目标资源 manage |
| `POST /imports` | `import.execute` + 对应资源 manage |
| `GET /imports/{id}` | `import.execute` + 对应资源 manage |
| `POST /imports/{id}/confirm` | `import.execute` + 对应资源 manage |
| `GET /imports/{id}/errors` | `import.execute` + 对应资源 manage |

---

## 12.6 任务与排班

| API | 权限/范围 |
|---|---|
| `GET /inspection-tasks` | `inspection.read` + SYSTEM_WIDE / ALL_GRADES / ASSIGNED_TASK |
| `GET /inspection-tasks/{id}` | 同上 |
| `GET /me/inspection-tasks` | 强制 ASSIGNED_TASK |
| `POST /inspection-tasks/preview` | `inspection.generate` |
| `POST /inspection-tasks/generate` | `inspection.generate` |
| `POST /inspection-tasks/{id}/cancel` | `inspection.cancel` |
| `GET /inspection-tasks/{id}/students` | `inspection.roster.read` + 任务范围 |
| `POST /inspection-tasks/{id}/roster-versions` | `inspection.roster.manage` |
| `POST /assignments/auto` | `assignment.manage` |
| `PUT /inspection-tasks/{id}/assignment` | `assignment.manage` |
| `POST /assignment-change-requests` | `assignment.change_request` + 当前受派人 |
| `POST /assignment-change-requests/{id}/review` | `assignment.change_review` |

---

## 12.7 截止时间

| API | 权限 |
|---|---|
| `GET /submission-deadlines/default` | `submission_deadline.read` |
| `GET /submission-deadlines/days/{date}` | `submission_deadline.read` |
| `GET /submission-deadlines/days/{date}/versions` | `submission_deadline.read` |
| `PUT /submission-deadlines/default` | `submission_deadline.manage` |
| `PUT /submission-deadlines/days/{date}` | `submission_deadline.manage` |

---

## 12.8 提交、审核与考勤

| API | 权限/范围 |
|---|---|
| `POST /inspection-tasks/{id}/submissions` | `submission.create` + ASSIGNED_TASK + 当前学期资格 |
| `GET /submissions` | `submission.read` + SYSTEM_WIDE / OWN_SUBMISSION |
| `GET /submissions/{id}` | 同上 |
| `POST /submissions/{id}/review` | `submission.review` + 合法状态 |
| `PATCH /inspection-tasks/{id}/expected-count` | `attendance.expected_count_adjust` |
| `GET /attendance` | `attendance.read` + 管理范围 |
| `GET /me/attendance` | `attendance.read` + SELF_STUDENT |
| `GET /attendance/{id}` | `attendance.read` + 范围 |
| `GET /attendance/{id}/versions` | `attendance.read` + 范围 |
| `POST /attendance/{id}/corrections` | `attendance.correct` |

---

## 12.9 异议

| API | 权限/范围 |
|---|---|
| `POST /attendance/{id}/objections` | `objection.create` + SELF_STUDENT |
| `GET /objections` | 管理读取路径或本人读取路径 |
| `GET /objections/{id}` | 同上 |
| `POST /objections/{id}/initial-review` | `objection.initial_review` |
| `POST /objections/{id}/final-review` | `objection.final_review` + 必要时 `attendance.correct` |

---

## 12.10 统计与周报

| API | 权限 |
|---|---|
| `GET /statistics/attendance` | `statistics.read` |
| `GET /statistics/incomplete-tasks` | `statistics.read` |
| `GET /reports` | `report.read` |
| `GET /reports/{id}/versions` | `report.read` |
| `POST /reports/weekly/versions` | `report.generate` + `report.read` |
| `GET /report-versions/{id}/download` | `report.read` |

---

## 12.11 文件与审计

| API | 权限 |
|---|---|
| `POST /files` | 对应业务写权限 + 上传者归属 |
| `GET /files/{id}` | FILE_PARENT |
| `GET /files/{id}/access` | FILE_PARENT + 文件状态有效 |
| `GET /audit-logs` | `audit.read` |
| `GET /audit-logs/{id}` | `audit.read` |

---

# 13. 数据库查询与后端实施要求

## 13.1 查询顺序

每个请求：

```text
认证
→ 获取最新有效角色和权限
→ 解析操作范围
→ SQL 中应用 WHERE / JOIN / EXISTS
→ 分页 / COUNT / GROUP BY
→ 响应字段过滤
```

详情查询必须：

```text
资源 ID
+
数据范围条件
```

一起查询。

禁止：

```text
先查到完整资源
→ 返回部分信息
→ 再判断权限
```

---

## 13.2 写操作

写业务必须：

1. 在事务内读取目标资源。
2. 重新检查账号状态。
3. 重新检查 Permission。
4. 重新检查资源归属。
5. 检查业务状态。
6. 检查版本或并发条件。
7. 完成业务写入。
8. 写入审计。
9. 一起提交。

前端传入的以下字段不得作为操作者身份依据：

```text
actor_id
reviewed_by
granted_by
uploader_user_id
当前 student_id 所有权
```

这些字段必须由后端当前会话确定。

---

# 14. 多角色用户

权限集合可以合并用于菜单和粗粒度入口，但数据范围不能简单合并后套用到所有操作。

例如：

```text
STUDENT_AFFAIRS_MANAGER + VOLUNTEER
```

用户可以：

- 以负责人身份查看全学院任务。
- 以志愿者身份查看本人任务。
- 仅对本人当前受派任务执行 `submission.create`。

不能因为负责人拥有 `ALL_GRADES` 就提交任何任务。

同理：

```text
TEACHER_ADMIN + STUDENT
```

教师可以管理全学院业务，但提交本人异议仍必须走学生本人身份关系。

---

# 15. 文件访问规则

## 15.1 临时文件

上传后尚未关联业务时：

- 仅上传者可查看临时元数据。
- 只能关联到其当前有权操作的业务资源。
- 关联时再次验证权限。
- 旧权限不能通过临时文件继续绕过新状态。

---

## 15.2 已关联文件

已关联文件：

- 不允许按 `file_id` 直接授权。
- 从实际父资源解析权限。
- 文件访问使用短时签名 URL。
- 已签发 URL 不承诺即时撤销。
- 关闭权限后不能再签发新链接。
- 旧链接按原有效期失效。

---

# 16. 审计要求

至少记录：

- 账号重要状态变更。
- 角色授予和撤销。
- 学生工作负责人可选权限变更。
- 绑定码签发和作废。
- 学生换绑。
- 志愿者资格导入、启停。
- 任务生成和取消。
- 人工改派。
- 志愿者查课提交。
- 查课审核。
- 应到人数修改。
- 最终考勤更正。
- 异议初核。
- 异议终审。
- 截止时间修改。
- 周报新版本生成。
- 系统配置变更。

审计记录至少包含：

```text
actor_id
action
resource_type
resource_id
before_json
after_json
reason
request_id
created_at
```

---

# 17. 权限测试基线

V1.0 集成测试至少覆盖：

| 场景 | 预期 |
|---|---|
| 教师尝试授予 SUPER_ADMIN | 拒绝 |
| 教师授予或撤销 TEACHER_ADMIN（含本人） | 拒绝 |
| 教师提交完整集合时省略原有教师或超管角色 | 整体拒绝，原角色不变 |
| 教师授予或撤销 STUDENT_AFFAIRS_MANAGER | 学院范围内允许 |
| 超管授予或撤销 TEACHER_ADMIN | 允许 |
| 超管授予/撤销 SUPER_ADMIN | 允许 |
| 未绑定微信用户访问考勤 | 拒绝 |
| 未绑定微信用户访问绑定接口 | 允许 |
| 成功绑定 student_id | 自动获得 STUDENT |
| 新学期导入志愿者 | 自动维护 VOLUNTEER 业务身份 |
| 志愿者资格停用 | 不能继续提交 |
| 被改派志愿者再次提交 | 拒绝 |
| 被改派志愿者查看本人历史提交 | 允许 |
| 学生 A 修改 URL 中学生 B ID | 不可读取 |
| 学生工作负责人默认查看统计 | 无可选权限时拒绝 |
| 教师开启 statistics.read | 下一请求可用 |
| 教师关闭 statistics.read | 下一请求失效 |
| 无初核权限的负责人读取异议证明 | 拒绝 |
| 有初核权限的负责人读取全院异议历史 | 允许 |
| 初核负责人执行终审 | 拒绝 |
| 负责人读取截止时间历史版本 | 允许 |
| 负责人修改截止时间 | 拒绝 |
| 负责人签发绑定码 | 允许 |
| 替换 file_id | 按真实父资源重新校验 |
| statistics.read 用户下载周报 | 无 report.read 时拒绝 |
| 批量请求混入无权限目标 | 整体拒绝 |
| 写请求伪造 actor_id | 忽略客户端值并使用服务端身份 |
| 权限关闭后申请新附件链接 | 拒绝 |
| 权限关闭前已签发短时链接 | 按原有效期失效 |

---

# 18. V1.0 不建设的权限能力

V1.0 不建设：

- 通用组织树授权。
- 动态 DSL 权限表达式。
- 任意 DataScope 编辑器。
- 数据库级通用 RLS 平台。
- 任意角色创建器。
- 通用角色模板市场。
- 批量下载全院所有照片。
- 普通用户删除查课事实、考勤历史、异议历史和审计记录。
- 任意客户端指定操作者。
- 超级管理员模拟任意学生/志愿者提交业务事实。

后续只有在真实业务需求出现时再扩展。

---

# 19. 实施顺序

权限功能按以下顺序落地：

```text
1. 固定 RoleCode
2. 固定 PermissionCode
3. 配置默认角色权限
4. 实现 PRE_BINDING 会话
5. 实现 STUDENT 自动身份
6. 实现 VOLUNTEER 学期资格与自动身份
7. 实现教师 role.assign 边界
8. 实现学生工作负责人可选权限
9. 实现各业务模块 permissions.py
10. 在 Repository 查询中落实数据范围
11. 接入文件父资源授权
12. 接入审计
13. 完成 MySQL 集成权限测试
```

---

# 20. 最终权限模型总结

V1.0 最终采用：

```text
固定五角色
+
有限 Permission
+
模块内资源范围
+
学生 / 志愿者自动业务身份
+
学生工作负责人少量可配置权限
+
关键操作审计
```

核心边界如下：

```text
SUPER_ADMIN
→ 全局账号与最高权限管理

TEACHER_ADMIN
→ 当前学院业务管理
→ 可 role.assign，仅手工管理 STUDENT_AFFAIRS_MANAGER，不能管理 SUPER_ADMIN / TEACHER_ADMIN

STUDENT_AFFAIRS_MANAGER
→ 全学院日常查询与辅助管理
→ 统计 / 周报 / 异议初核按个人配置
→ 可管理学生绑定
→ 可读取完整截止时间历史

VOLUNTEER
→ 由学期资格驱动
→ 只能操作本人当前任务
→ 可保留本人历史参与只读记录

STUDENT
→ 由有效 student_id 绑定自动产生
→ 只能访问本人业务数据

PRE_BINDING
→ 不是角色
→ 仅允许身份绑定相关 API
```

本权限策略作为查课管理系统 V1.0 权限实现基线。后续新增功能时，应先明确资源、操作、默认角色、数据范围和审计要求，再新增对应 API 与 Permission，不通过扩大既有 `read` 或 `manage` 权限隐式放行。
