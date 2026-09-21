# 权限设计与项目实施对照

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-21 |
| 权限基线 | [PERMISSIONS.md V1.1](./PERMISSIONS.md) |
| 关联技术方案 | [开发技术方案 V1.5](../查课管理系统V1.0开发技术方案.md) |
| 关联 API 契约 | [API_CONTRACT.md](./API_CONTRACT.md)（已落地端点的可执行契约与错误码） |
| 本轮范围 | 记录 P1 权限基础/管理闭环、P2 微信身份闭环与 P3 基础数据 + 两步原子导入的实际落地：设计对照、实现进度台账与验收覆盖 |
| 核对方式 | 阅读当前代码 + 真实 MySQL 集成测试（`tests/integration/`，195 通过）；缺库自动跳过不算通过 |

## 1. 相对旧草案的确定变化

| 项目 | 当前采用规则 |
|---|---|
| Permission 数量 | 38 个，严格取自新基线注册表与矩阵 |
| 教师角色分配 | 教师默认具备 role.assign，仅手工授予/撤销当前学院 STUDENT_AFFAIRS_MANAGER；禁止授予/撤销 SUPER_ADMIN、TEACHER_ADMIN（含本人），不拥有 account.manage |
| 负责人绑定管理 | 默认具备 identity.binding.manage，可签发/作废绑定码，核验后换绑并撤销旧会话 |
| 学生身份 | 有效 student_id 绑定成功自动维护 STUDENT；解除/失效后收回对应学生能力 |
| 志愿者身份 | 资格按学期导入、启停并自动维护 VOLUNTEER；角色本身不能代替当前学期资格 |
| 未绑定微信会话 | PRE_BINDING 是受限会话状态，不是新角色；仅放行 /me、绑定、刷新、退出 |
| 排班读取 | 使用 inspection.read；不再注册独立 assignment.read |
| 历史参与 | 改派、资格停用或学期结束仍可读本人历史提交、当时排班、异常明细、审核意见及本人提交照片 |
| 负责人异议 | 有初核权限时，可读全学院全部异议及历史；关闭后管理读取路径失效 |
| 截止时间 | 负责人默认可读完整配置和历史，不可修改 |

旧草案中“负责人不能管理绑定”“教师没有 role.assign”“历史提交范围待确认”等条款不再作为当前依据。三个个人可选项仍为 statistics.read、report.read、objection.initial_review，默认关闭。

## 2. 接入约定：保持权限设计简单

### 2.1 固定学院边界与角色变更

SYSTEM_WIDE 和 ALL_GRADES 均为当前系统、当前学院的边界，不建设组织树或通用范围引擎。V1.0 单学院部署可由部署配置界定学院；不能仅相信请求中的 college_id。以后引入多学院时必须增加可信归属模型与 SQL 过滤后才能扩展。

教师没有 account.read/manage，不代表不能完成被允许的角色分配。角色管理界面应提供受 role.assign 保护的受限目标选择器，仅返回可管理目标的必要身份和角色；不得因此开放全量账号查询、密码重置或账号停用。可选权限界面同理使用 optional_permission.manage 保护的负责人选择器。

PUT /users/{id}/roles 必须检查角色增删差集，保护操作者不能管理的现有角色。教师提交完整集合时，不能借省略 SUPER_ADMIN 或 TEACHER_ADMIN 撤销这些角色，也不能用账号编辑接口旁路写 user_role。STUDENT/VOLUNTEER 由绑定和资格流程管理，不能通过 role.assign 绕过资格。

教师不得互相授予或撤销 TEACHER_ADMIN，也不得撤销自己的教师角色；只有超级管理员可执行教师角色变更。教师手工角色允许列表固定为 STUDENT_AFFAIRS_MANAGER。角色变更与个人授权清理、审计必须同事务提交；并发更新通过目标用户行锁与 lock_version 校验防止覆盖。

### 2.2 受限会话与自动身份

身份解析应提供可信的 student_id、会话 client_type、业务身份状态、有效角色和 Permission。PRE_BINDING 用于未绑定的微信会话，不能简单写成“所有 student_id 为空的账号均受限”，否则会锁住本来无需学生身份的 Web 管理员。

微信身份未绑定时，登录接口签发受限会话。后续每次业务请求都在模块入口前检查受限状态；刷新只能延续该状态，不能因旧 JWT 中包含角色就获得管理入口。登录、公共健康检查不属于该会话的业务权限白名单。

绑定成功应在同一事务核销绑定码、验证学生有效性、写 student_id、维护 STUDENT 并追加审计；下次请求读取更新身份。若先导入志愿者资格、后完成学生绑定，绑定路径也须检查已有有效资格，补齐相应业务身份。

资格启停/学期变更必须影响提交授权，但不得误收回基线明确保留的历史参与读取权。可保留 VOLUNTEER 角色作为历史参与入口，执行 submission.create 时强制检查任务所属学期与当前学期及有效资格；不以删除角色作为唯一的停用实现。用户账号停用或会话失效仍拒绝所有业务请求。

换绑撤销旧会话，重新核验当前用户对应的学生和志愿者身份；避免旧令牌持有旧 student_id 权限。历史提交仍按原提交者 user_id 及当时快照表达，不能改成读取现任执行人的材料。

### 2.3 个人授权与派生读取

仅三个个人开关可以写入 user_permission，目标具备负责人身份，操作者具有 optional_permission.manage，校验不得自我提权或修改超管权限。撤销负责人角色时同步使其个人授权失效，重新授角色不自动恢复。

负责人获初核权限时，异议管理读取是条件派生，不要求单独持久化 objection.read 授权；关闭初核后立即失去此读取来源。多角色若仍通过教师身份合法拥有同名权限，界面显示来源，不将关闭个人开关描述成禁止所有路径。

### 2.4 资源查询、字段和文件

所有列表、搜索、COUNT、分组和导出先施加范围，再聚合或分页。详情以资源 ID 与范围共同查询；写操作在事务中重验权限、归属、状态与版本。

inspection.read 包含当前排班基本信息。GET /assignments 如实现，也复用 inspection.read 并使用相同任务范围，不重新引入 assignment.read。历史参与从 OWN_SUBMISSION 路径返回当时任务/排班摘要，不开放当前任务全名单或改派后的新执行信息。

OWN_SUBMISSION 下的本人照片仍受文件实际状态和保留期限约束。历史只读权不等于永久保存权；已到期清理的照片显示清理状态，不承诺继续下载。

临时文件读取检查上传者，关联时再次检查业务写权限；已关联文件必须从真实父资源解析权限，不能因是上传者而绕过新的业务范围。短时签名 URL 在签发时鉴权，旧链接按原期限失效。

学生响应不得带整班照片、他人异常、工作人员内部备注或账号秘密；志愿者只看执行所需任务名单及本人历史异常。所有角色均不读取密码摘要、刷新凭证摘要、AppSecret、session_key 等秘密字段。写请求中的 actor_id/reviewed_by/granted_by 等不参与授权和持久化取值，只使用服务端身份。

### 2.5 API 补充映射（不新增 Permission）

以下补充现有工程所需入口，不表示已实现；前缀均为 /api/v1。

| 接口/资源 | 策略 |
|---|---|
| GET /role-assignment-targets | role.assign + 当前学院受限目标/可操作角色，非 account.read 替代 |
| GET /optional-permission-targets | optional_permission.manage + 可配置负责人；仅必要身份信息 |
| GET /assignments | inspection.read + 当前任务范围 |
| GET /assignment-change-requests、/{id} | 本人申请用 assignment.change_request；管理读取用 assignment.change_review |
| GET /inspection-tasks/{id}/roster-versions | inspection.roster.read + 任务范围；志愿者历史路径不返回当前完整名单 |
| PATCH /inspection-tasks/{id}/photo-requirement | inspection.roster.manage + 执行前状态 |
| GET/PUT /teaching-classes/{id}/students | student.read/manage + 范围，名单操作不由 academic.read 旁路开放 |
| GET/PATCH /system-config | system.config.read/manage；当前学期/截止时间等已有业务配置按各自明确权限路由 |
| GET/PUT /file-retention-policies | system.config.read/manage |
| 清理、备份、幂等记录、审计追加 | 部署入口或被授权业务内部写入，不开放任意表 CRUD |

模板下载按新基线仅要求对应资源 manage；真正上传、预览、确认和错误文件读取还需要 import.execute。导入类型从实际批次取得，不能由客户端改传 type 绕过。

## 3. 实现进度台账（截至 2026-09-21，P1 + P2 + P3 已落地）

| 项目 | 状态 | 说明 / 覆盖测试 |
|---|---|---|
| 五角色 | 已实现 | RoleCode 固定五角色，与新基线一致，不加第六角色 |
| PermissionCode | 已实现 | 38 项注册；无独立 assignment.read（`test_seed.py` 校验矩阵精确对齐） |
| 默认权限 | 已实现 | `seed.py` 幂等同步 role_permission 精确对齐 `policy.DEFAULT_ROLE_PERMISSIONS`，不动个人授权、不重置口令（`test_seed.py`） |
| 当前身份 | 已实现 | CurrentUser 增 `pre_binding`；PRE_BINDING 由 `student_id` 空且无角色派生；Web 管理员不误封（`test_wechat_binding.py`） |
| 微信登录 | 已实现 | `identity/wechat.py` code2session（httpx 生产 + Mock）；错误/超时映射 401/502；首次登录建无口令账号（`test_wechat_binding.py`） |
| STUDENT 自动维护 | 已实现 | `bind_student` 同事务核销码 + 自动授 STUDENT + `lock_version+1` + 审计；一次性码加 `FOR UPDATE` 锁，并发核销仅一人成功（`test_wechat_binding.py`） |
| VOLUNTEER 自动维护 | 已实现 | 学期资格 upsert 与导入确认时若学生已绑定且资格启用则即时补授 VOLUNTEER（幂等，`lock_version+1`）；停用不回收；"先导入资格后绑定"由 `bind_student` 反向补授（`test_academic.py`、`test_importer.py`） |
| 基础数据（P3） | 已实现 | `/api/v1/academic` 学期/节次/校历/行政班/学生/课程/教学班/名单整体替换/课表(生效周)/志愿者资格；`academic.read|manage`、`student.read|manage`、`volunteer.read|manage` 守卫，同事务审计、`FOR UPDATE` 串行化、真实并发（`test_academic.py`，33） |
| 两步原子导入（P3） | 已实现 | `/api/v1/imports` 预览→确认；`import_batch` 暂存规范行，确认前重校验外部引用后整批单事务落库、任一失败全回滚零副作用；组合权限 `import.execute` + 目标 manage（路由早拦 + 服务纵深）；过期/重复确认状态机；周次解析复用 `common/parsing`（`test_importer.py`，24） |
| role.assign | 已实现 | `GET /role-assignment-targets` + `PUT /users/{id}/roles`，差集边界 + 乐观并发 + 同事务审计（`test_admin_rbac.py`） |
| 个人权限 | 已实现 | 三项许可清单管理 API、非负责人 422、禁自我提权 403、撤角色清除授权且重授不恢复、下一请求即时生效（`test_admin_rbac.py`） |
| 绑定管理 | 已实现 | 超管/教师/负责人经 `identity.binding.manage` 签发、作废、换绑/解绑并撤销旧会话（`test_wechat_binding.py`） |
| 历史和文件范围 | 待实现 | 业务模块 OWN_SUBMISSION、异议条件读取、FILE_PARENT（P4–P6） |
| 测试 | 持续补全 | 已覆盖新基线身份/授权/PRE_BINDING/并发；跨用户、历史只读、行级范围随各业务模块补齐 |

代码依据：

- [PermissionCode](../backend/app/core/permissions.py)
- [权限种子](../backend/app/modules/identity/seed.py)
- [CurrentUser 与绑定服务](../backend/app/modules/identity/service.py)
- [身份路由](../backend/app/modules/identity/router.py)
- [权限读取/写入 Repository](../backend/app/modules/identity/repository.py)
- [基础数据模块](../backend/app/modules/academic/)（router/service/repository/models/permissions）
- [两步原子导入模块](../backend/app/modules/importer/)（router/service/repository/models/permissions）
- [表格与时间解析](../backend/app/common/parsing/)（xlsx_tabular、time_slots）
- [现有身份测试](../backend/tests/integration/test_identity.py)
- [基础数据测试](../backend/tests/integration/test_academic.py)
- [导入测试](../backend/tests/integration/test_importer.py)

## 4. 实施与验收顺序

工程顺序见 [开发路线](./DEVELOPMENT_PLAN.md)：先完成固定角色、38 个权限与默认矩阵，再将教师角色边界、负责人可选项和审计作为同一授权闭环交付；随后完成微信受限会话、绑定和学期资格，业务模块逐个落实范围、文件父资源和 MySQL 集成测试。

除基线第 17 节外补充验证：

- PRE_BINDING 白名单按方法和路径同时匹配，刷新不能升级权限，Web 管理员不被 student_id 空值误封。
- 教师不能授予/撤销 TEACHER_ADMIN（含本人），不能借省略字段或替换整组角色撤销 SUPER_ADMIN / TEACHER_ADMIN；教师可管理负责人角色，超管可管理教师角色；STUDENT/VOLUNTEER 仍受业务状态控制。
- 负责人能签发/作废/换绑，但没有账号全局读取/管理权限，换绑必须撤销旧会话并审计。
- 先导入资格后绑定、学期切换、资格停用后重新启用，均得到一致的角色与执行资格。
- 志愿者改派、资格停用、学期结束后可读本人历史照片（未清理时），不可读现任执行人的新提交和任务当前全名单。
- 负责人初核开启可查全部已处理异议历史；关闭后同一有效会话下一次请求失效，本人学生阅读来源仍按本人约束。
- 多角色的全年级读取不扩大 submission.create、objection.create 的本人范围。
- 38 个注册权限与默认矩阵一一对应；不存在未知 code、漏授默认项或把三个可选项误设为负责人默认。

截至本轮，上述 PRE_BINDING 白名单、教师角色边界、负责人三项可选项、绑定签发/作废/换绑及一次性码并发核销等已由 P1/P2 实现并经真实 MySQL 集成测试覆盖（见 [API_CONTRACT.md](./API_CONTRACT.md) 与 `tests/integration/`）。P3 进一步落地基础数据全量 CRUD 与两步原子导入，志愿者学期资格的 VOLUNTEER 自动身份（导入/启用即时补授、"先导入资格后绑定"经 `bind_student` 反向补授、停用不回收）已实现并经测试覆盖。历史/文件父资源读取范围与各业务模块的行级数据过滤仍属 P4+ 的后续开发，其运行时生效与否以对应阶段验收为准。
