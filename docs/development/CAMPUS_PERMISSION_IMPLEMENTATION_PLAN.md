# CourseManagement 账号补权与学院隔离代码改造计划

## 2026-10-14 实施边界

本次已实现固定教师学院、学生负责人当前学籍学院及功能开关、管理员全校统筹、显式平台管理能力，以及后端/Web 的学籍异动和学生数据交接。平台管理员沿用 SUPER_ADMIN，只增加 `administrator_account.manage`，不新增角色或登录入口。普通教师不能办理跨院异动，跨院由管理员办理。

正式学籍以生效区间解析，支持转班/转专业/转院、休学、复学、毕业、退学、未来计划撤销和明确的过去日期纠错。学号、学生 ID 和微信绑定保持稳定；过去纠错保留后续区间，不自动重写历史考勤。离校本人历史访问暂定十个日历年，归档不等于物理删除。

老师通过“学生交接与学籍”导出可回导的 XLSX，上传单文件或平铺 ZIP，预览新增/字段更新/异动/错误/缺失项，确认时重新核验权限、学生版本和行政班归属版本。全量对比的缺失项只提示核查；不会自动删人、归档或恢复学籍。每批只刷新一次受影响的未来正式任务名单。已开始、有提交或已有截止事实的任务保留原快照；无法确定来源或人工人数口径的任务进入待核定队列。

学校初始化名称为“绍兴理工学院”；正式学院为“人工智能学院（低空技术与工程学院）”，软件学院保留为“软件学院（测试）”。原软件学院两个班级及其学生、账号、业务历史全部保留。测试学院目前是独立学院工作区，未实现全校汇总自动排除测试数据；历史学校报表仍保留原内容。

**仍属规划：**学院独立作息/日历及实际时间排班、动态课程类型与志愿者组规则接入抽查/排班、小程序个人课表。已有类型/组配置表不等于上述业务已接入；本轮没有小程序新功能开发。无法可靠核定的存量课程、任务、批次和报表由管理员继续核定，不根据当前学生成员猜测历史归属。

实现、验收和部署边界见 [本次交付记录](../development/ENROLLMENT_IMPLEMENTATION_ACCEPTANCE_20261014.md)。其余章节保留完整设计目标，不能将规划验收项全部视为本次已通过。


版本：1.0 · 日期：2026-10-14 · 状态：固定权限与完整后端学籍/交接已实施；后续阶段保持规划。

目标：以固定角色和学院归属实现全校查课；教师拥有唯一所属学院全部业务权限、学生负责人只在本人学院工作、管理员统筹全校。在现有管理员上补一项管理员账号管理能力，避免新增角色、平台登录或业务隔离体系。

架构：沿用五个 RoleCode、现有 UserPermission/会话/账号服务与 UsersView；增加稳定学院归属及统一 ResourceScope。平台权限仅保护管理员账号操作，不改变已有业务权限。

技术栈：Python 3.12、同步 FastAPI/SQLAlchemy 2、MySQL 8.4、Alembic、Vue 3 Composition API/TypeScript/Pinia/Element Plus。

依据：[产品需求 v2.0](../product/CAMPUS_MANAGEMENT_PRD.md)、[开发设计 v2.0](CAMPUS_BACKEND_WEB_DESIGN.md)、[学籍场景分析](../product/ACADEMIC_LIFECYCLE_ANALYSIS.md)。使用 writing-plans 整理文件、接口、定向测试和实施顺序；由 GPT 直接执行，不生成第三方任务包、不启动子 agent。规划不授权生产迁移或发布。

## 1. 原规划基线与不变量（实施状态见上节）

- 本次核对 dev-main / efa62b5，迁移 head 为 181729fc7239；工作区有既有任务/小程序等差异。实施时重新记录 HEAD 与文件差异，不切分支、不重置脏文件。
- 当前 RoleCode 有五项；`identity/repository.py:list_effective_permissions` 是角色并集＋两项个人可选权限；`policy.py` 默认管理员权限通过枚举全集推导，新增能力不能自动进入默认值。
- `identity/account_service.py:reset_password` 当前允许普通 SUPER_ADMIN 重置管理员；`identity/service.py:assign_roles` 当前允许其授予/撤销 SUPER_ADMIN。这两条旧入口都须纳入补权。
- `UsersView.vue` 已有教师/负责人页签，`api/accounts.ts` 已有账号方法；沿用它们。前端现有 package.json 没有已配置的组件测试命令，不宣称 npm test 当前可用。
- 平台部分不新增表、不新增角色、不限制其原业务读取；仅增加显式能力及账号操作守卫。学院隔离需要业务模型/查询调整，与平台补权分开交付和验证。
- 无教师学院归属不等于全校。负责人无当前有效学籍或任命学院不一致时，管理范围为空；个人历史读取按绑定与期限单独判断。
- 教师本院全量业务不包括管理员/教师账号管理、校级设置、代志愿者提交或学生私人课表读取。跨院转专业仅管理员办理；不创建跨院教师授权或支援关系。
- 转专业不换学号，离校历史暂定 10 年；真实登记时间和生效日期分开。日期补录/纠错不自动覆盖已提交名单、考勤、截止事实与归档报表。

## 2. 第一批：最小平台补权

### P1 能力注册、判定与默认权限

修改文件：`backend/app/core/permissions.py`、`backend/app/modules/identity/{policy,repository,seed}.py`、`backend/tests/unit/test_permission_policy.py`。

新增唯一能力 `administrator_account.manage`，RoleCode 仍保留五项。平台标记是 SUPER_ADMIN＋显式 UserPermission，不是新角色。增加受保护逐人能力集合，与现有负责人 OPTIONAL_PERMISSION_CODES 分开；读取时仅管理员可得到该能力，误存到教师/负责人也必须忽略。

纯判定接口放在 policy.py，Service 负责账号有效性及事务内重读：

```python
def can_manage_administrator(
    role_codes: frozenset[str], permission_codes: frozenset[str]
) -> bool:
    return (
        "SUPER_ADMIN" in role_codes
        and "administrator_account.manage" in permission_codes
    )
```

- [ ] 在现有单测补独立期望：普通管理员 False、显式平台能力的管理员 True、教师即使误授能力也 False。先运行确认新方法/新能力尚不存在而失败。
- [ ] 增加 PermissionCode；默认 `_admin` 明确排除此能力，教师默认亦不能获得；新 code 不进入普通负责人可选列表。
- [ ] Repository 读取原角色/可选权限后，单独读取该受保护能力并核验 SUPER_ADMIN；不扩大所有任意 UserPermission 的认可范围。
- [ ] 更新测试注册表的独立期望（本批从 40 到 41 项，角色仍五项）；增加“seed 重跑不将平台能力授予全部管理员”的回归。
- [ ] 定向运行 `pytest tests/unit/test_permission_policy.py -q -p no:cacheprovider`，再检查被修改文件。

示例回归（使用上述目标接口，不照抄被测集合）：

```python
import pytest
from app.modules.identity.policy import can_manage_administrator

@pytest.mark.parametrize("roles, permissions, expected", [
    ({"SUPER_ADMIN"}, set(), False),
    ({"SUPER_ADMIN"}, {"administrator_account.manage"}, True),
    ({"TEACHER_ADMIN"}, {"administrator_account.manage"}, False),
    ({"STUDENT_AFFAIRS_MANAGER"}, {"administrator_account.manage"}, False),
])
def test_administrator_account_capability(roles, permissions, expected):
    assert can_manage_administrator(frozenset(roles), frozenset(permissions)) is expected
```

### P2 复用账号服务，封住所有旧入口

修改：`backend/app/modules/identity/{account_service,account_schemas,account_router,service,policy}.py`；新增测试 `backend/tests/unit/test_administrator_account_policy.py`、`backend/tests/integration/test_administrator_accounts.py`。

在 AccountService 增加以下目标接口，不新建平台 Service：

| 方法 | 输入 | 输出及职责 |
| --- | --- | --- |
| _require_administrator_account_manage | actor_id: int | None；重读有效管理员角色＋显式能力，失败抛 PermissionDeniedError |
| list_administrators | actor: CurrentUser、params: PageParams、query/status | dict；仅 SUPER_ADMIN 目标账号分页，不包含口令/会话 |
| create_administrator | actor、AdministratorAccountCreate、request_id | dict；建立管理员及明确选择的额外能力，同事务审计 |
| update_administrator | actor、target_id: int、AdministratorAccountUpdate、request_id | dict；版本核验、存续保护、状态/能力更新及会话联动 |

创建 Schema 只接收账号、姓名、初始口令、可选平台能力，默认能力 False；更新只允许状态、姓名、平台能力和 lock_version。不能让客户端任意提交 roles/permissions 数组。

- [ ] 先复现普通管理员重置/授予管理员现状，补目标拒绝测试；额外能力管理员可对明确目标正常操作。
- [ ] 新增 GET/POST `/administrator-accounts`、PATCH `/{id}`、POST `/{id}/password-reset`，目标角色固定为 SUPER_ADMIN。
- [ ] 创建、停用、角色变更、管理员密码重置、能力授予/撤销全部调用同一新守卫；`assign_roles` 触及 SUPER_ADMIN 或目标当前为管理员时亦执行，避免旧 role.assign 绕过。
- [ ] 原 `set_optional_permission` 不接收新 code；平台能力只能通过受保护管理员账号命令变更。撤销 SUPER_ADMIN 同事务清除其平台授予，避免之后重授角色复活旧能力。
- [ ] 操作者状态、角色、能力锁内重读；目标版本、审计及会话撤销沿用当前规则。自助改密仍验证本人原口令，不要求平台能力，不返回目标会话或原密码。
- [ ] 增加 `require_another_administrator_manager(session, target_id)`，沿用 `lock_admin_registry` 的稳定 SUPER_ADMIN 行锚点；停用/撤角色/撤能力时保证仍有其他有效管理员持能力，同时保留已有最后管理员保护。
- [ ] 测试直接 API、旧别名及伪造字段都不能绕过；MySQL 并发下两人互相停用/撤权不得删掉最后管理者。

### P3 增量迁移、显式初始化与现有账号页

修改：`backend/app/modules/identity/seed.py`、`apps/admin-web/src/api/accounts.ts`、`apps/admin-web/src/views/UsersView.vue`；新增 `apps/admin-web/src/components/accounts/AdministratorAccountEditor.vue`、`backend/app/modules/identity/bootstrap_admin_management.py` 及相应测试。Alembic 新版本由工具接当前真实 head 生成，不预造 revision ID。

- [ ] 迁移只新增 Permission 记录，并清除其非预期 RolePermission 默认映射；不新增角色或表、不自动给全部 SUPER_ADMIN 赋权。反复 seed 的结果一致。
- [ ] 初始化 CLI 接受明确 user_id，验证账号有效且已有 SUPER_ADMIN，在同一账号/角色锁下幂等授予 UserPermission 并审计；只处理指定账号，不读取/输出密码。生产执行另按环境授权。
- [ ] `UsersView` 增加“管理员账号”页签，仅 SUPER_ADMIN＋新能力显示；沿用同一登录、页面壳与 API 客户端。平台标记由能力派生，不传新 RoleCode。
- [ ] AccountEditor props 为目标和 lock_version，emit 保存明确表单；平台能力开关只在该区域出现。教师/负责人编辑不能输入它。
- [ ] 移除 accounts.ts 的固定默认密码回退；创建/重置提供经验证的明确口令或服务端既定安全重置方式，实际方案不得自动落成共享弱密码。
- [ ] 配置 Vitest/Vue Test Utils 并锁依赖后，补账号页显示/隐藏、403 和409用例；运行 `npm.cmd run build` 并实际验证普通管理员不能进入受保护功能，平台管理员原业务能力保持。

本批退出条件：AC50/51/54、平台能力非默认、旧角色/改密入口保护、指定初始化及账号页全部有证据。上线顺序须确保指定平台管理者可用，不把所有管理员升级，也不通过修改数据库全量角色掩盖初始化遗漏。

## 3. 第二批：固定学院身份与负责人功能

### C1 学院、教师绑定及当前学籍底座

新增 `backend/app/modules/organization/{models,schemas,router,service,repository}.py`；修改 `backend/app/{models,main}.py`、`academic/{models,schemas,repository}.py`、`identity/{models,account_schemas,account_service}.py`；增量迁移及 `test_teacher_college_binding.py`、`test_manager_appointment.py`。

- [ ] 建立 school/college；教师绑定 `teacher_college_binding(user_id PK, college_id NOT NULL, version)`，创建教师必须指定一个有效学院，已有教师待核对归属，不默认为全校。
- [ ] 建立按日期 student_enrollment；迁移现有班级学院文本到明确组织关系，未知/歧义进清单，不补造历史起点。
- [ ] 建立 manager_appointment 与 manager_permission_config。任命者是本院教师或管理员；目标已绑定、有效、当前本院学生，配置只接受预定义负责人功能。
- [ ] 负责人动作白名单不得包含学籍变更/归档、管理员账号、教师账号、校级设置或任意跨院权限。旧初核按钮不恢复，新异议能力沿用一次审核。
- [ ] 转院结束旧负责人任命并停止旧学院管理；新院重新任命。教师调院只有管理员可办，版本、交接和权限修订同事务。
- [ ] 回归缺学院拒绝、外院学生任命拒绝、未来异动生效日前后、解绑和停用、身份与私人历史分离。

### C2 统一固定范围，逐条封闭管理入口

新增 `backend/app/modules/identity/authorization.py`；修改 `identity/{deps,service,repository}.py` 及 academic/importer/inspection/attendance/objection/report/file/audit 的 permissions/service/repository/router。

目标类型和接口：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class ResourceScope:
    kind: Literal["SCHOOL", "COLLEGE", "SELF"]
    school_id: int
    college_id: int | None = None
    student_id: int | None = None
    authorization_revision: str = ""
```

`resolve_scope(actor: CurrentUser, action: str, college_id: int | None) -> ResourceScope` 负责固定角色/学院/任命解析；`require_resource_scope(scope: ResourceScope, resource_college_id: int) -> None` 检查真实资源归属，范围外抛 PermissionDeniedError。这两个目标接口均放 authorization.py，由所有管理 Service 使用。

`scope.kind=SCHOOL` 仅从有效 SUPER_ADMIN 的业务能力产生，college_id 为空不产生全校。教师由绑定得到唯一学院；负责人由当前学籍与有效任命一致取得唯一学院，再核验允许动作。SELF 由本人关系生成，不是管理员代操作能力。

- [ ] 先建独立期望矩阵：管理员全校、教师 A 全量/B 拒绝、负责人 A 已启用功能/B 拒绝、负责人误配外院仍拒绝；平台开关不改变任何业务范围。
- [ ] `/me/workspaces` 和 `/colleges/{cid}/capabilities` 返回上述结果；`/me` 可兼容旧字段，但管理请求不能仅靠扁平 permission 并集通过。
- [ ] 查询从 Service 传明确 scope，列表/计数/详情/候选/上传关联/签名访问/导入预览/导出/批量统一过滤。Repository 不提供无 scope 查全校默认。
- [ ] 学籍跨院办理仅管理员；教师院内日期更正无需专门授权模板，已有事实更正仍按对应版本守卫。
- [ ] 旧 URL 从实际父资源解析归属再验；伪造路径或混合批量整批拒绝，不存在/不可见不泄露外院明细。
- [ ] 撤任命、调院及账号变更使修订失效；写事务重查当前范围。不同动作按本业务原锁序整合统一账号/身份锚点，不增加未经证明的第二套事务引擎。

下列每组必须同时检查路由、Service、Repository、文件与报表消费端，不只改新入口：

| 域 | 必查入口 | 定向用例 |
| --- | --- | --- |
| academic | 学生/班/名单/课表、总课表导出、删除/学期重置 | 外院读写拒绝，历史不因当前班变更搬移 |
| importer | 单文件预览/确认、ZIP/bulk、模板/错误明细 | 外院文件、过期预览、误激活、批次部分失败如实反馈 |
| inspection | 课次选择/生成/抽查、自动/人工、编辑/换班、名单、提交/旧审核 | 管理范围与本人受派都满足，两阶段、规则及历史不变 |
| attendance/objection | 本人/管理读取、更正、一次审核 | 外院拒绝、本人与管理角色分开、自审回避、版本保护 |
| report/file/audit | 列表/计数/产物、源修订、材料签名、操作日志 | 外院导出与附件拒绝，管理员全校正确，私人表无副作用 |

### C3 Web 工作区与负责人编辑

新增 `stores/workspace.ts`、`composables/useWorkspaceRequest.ts`、`api/workspaces.ts`、`api/managerPermissions.ts`、`TeacherCollegeEditor.vue`、`ManagerPermissionEditor.vue`；调整 session/router/AppShell/UsersView 及各业务 API 显式学院参数。

- [ ] 教师/负责人只返回合法单院，管理员可选择学院/校级总览；不增加跨院授权页、RoleGrantsView 或支援页。
- [ ] 教师学院只读显示；管理员修改学院前预览交接；负责人学院由本人身份得到，表单无外院选择。
- [ ] 编辑组件只发出明确配置，后端 capabilities 驱动按钮，不在 Vue 写第二套角色/数据范围算法。
- [ ] 切学院/账号清选择及预览，旧响应按 context_revision 丢弃；403/404/409 不自动重试写入，缓存含用户/学院/学期。
- [ ] 新增 `tests/e2e/college-role-boundary.spec.ts` 和组件用例，实际走 A 教师/负责人、管理员、带平台能力管理员；不能以构建通过替代 HTTP 越权验收。

本批退出条件：AC01/02/03/11/41/52/53 和全管理入口范围闭环；此前不开放第二学院真实数据。只加教师 college_id 或只做工作区下拉不算完成。

## 4. 后续业务阶段与依赖

| 顺序 | 代码范围及交付 | 独立退出条件 |
| --- | --- | --- |
| B1 学籍/老师数据流转 | academic/enrollment_service.py、participation 解析；importer 差异计划、归档/导出；identity 任命结束；任务名单快照补稳定组织 ID | PR-15/AC40—49，转专业不换号、日期区间、旧源不回写、10 年历史与独立异议窗口 |
| B2 类型/作息/统一课次 | academic/course_type_service.py、time_service.py、publication_service.py；course_occurrences.py 稳定实例；相关 Web 维护 | AC04—06/19/22/23，学院类型可维护、真实时间、历史快照和重试去重 |
| B3 本院组与范围抽查 | volunteer 模块、inspection/scope.py、scheduling loader/constraints/validation/planner；本院组及任务页面 | AC07—09/20—26，类型与班级先过滤再抽样，缺额不跨类型补齐，无支援模型 |
| B4 私人课表后端 | timetable 模块、正式发布只读投影、站内通知与主动采用 | AC12—17/36/37 后端契约；私人副本不参与任何正式业务，小程序只产品设计 |
| B5 联合验收 | 两学院匿名试点、迁移/恢复演练、页面/文件导出与账号回归 | AC01—54，记录已实现/本次验证/未验证/未部署，不引用旧测试数宣称完成 |

平台 P1—P3 可作为账号模块独立交付，先降低管理员管理风险；学院 C1—C3 是多学院底座，不能省略。后续 B1—B4 依据开发设计逐域推进，不顺便引入微服务、异步数据库、通用授权引擎或第三方执行工作流。

## 5. 实施与发布验证

每个独立批次先写能失败的行为回归，再修改实现，定向通过后运行受影响链路并检查差异。提交时只暂存明确文件；提交/生产部署按用户相应授权执行，计划不自动推送。

现有检查（实施时执行，本轮仅核对了 alembic heads）：

```powershell
# backend/
.\.venv\Scripts\python.exe -m pytest tests/unit -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests --no-cache
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m alembic heads

# apps/admin-web/
npm.cmd run build
```

MySQL 集成夹具会重建表，先按 conftest 核验独立 *_test 库后才能运行；本计划未连接数据库。Web 组件/E2E 命令在建立配置后写入 README 并锁定依赖，不能直接宣称已有 npm test。

迁移采用扩展→有依据回填→匿名演练→约束→应用切换。既有 SUPER_ADMIN 不自动转平台角色，新增能力不默认分配；教师归属未知不能开全校。多学院事实写入后不能退回忽略范围的旧代码；发布记录包含 SHA、迁移、教师映射、指定平台能力初始化、账号/范围验证和兼容版本恢复路径。
