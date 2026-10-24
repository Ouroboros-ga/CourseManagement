# 唯一人员档案与业务关联补齐计划

> 后续状态：本批次已合入、推送并部署应用源码 `bed04b8`，见[发布记录](../archive/2026-10-24/operations/PERSON_RELATION_RELEASE_20261018.md)。文末未发布文字为原验证阶段记录；仍未运行生产人员回填。

日期：2026-10-18。基线：`ae6094d`，由 GPT 在当前会话直接执行，不委派子 agent。

**目标：** 教职工按学校与工号、学生按学号定位唯一档案，正常资料导入自动建立明确关系；姓名不充当外键，历史任务保持快照。

**架构：** 复用 FacultyStaff、Student、TeachingStaffAssignment、ClassStaffResponsibility、学籍与名单生命周期，不新增人员表或账号体系。导入预览计算人员关联，确认时同事务写入；存量资料使用预览与版本确认补关联。

## 1. 当前架构核查

| 环节 | 证据位置 | 结论与处理 |
| --- | --- | --- |
| 人员档案 | academic/staff_models.py、academic/models.py、identity/models.py | 已有学校+工号唯一、学号唯一、账号到人员唯一外键；当前部署单学校，学生全局学号唯一比校内唯一更严格，暂不作多学校迁移 |
| 课表导入 | importer/service.py 的 _apply_timetable、_apply_grid_timetable | 只保存 teacher_name/teacher 文本，缺授课关系；本次补齐 |
| 班主任/辅导员旧名单 | importer/service.py 的 _apply_admin_roster | 只更新显示列，缺正式责任关系；本次补齐 |
| 专用关系导入 | importer/staff_adapter.py | 已有工号/唯一姓名解析；授课姓名“本院优先”可能掩盖外院同名，本次改为学校范围无歧义匹配 |
| 预览一致性 | importer/scoped_service.py 的 source_revision | 缺教职工与关系基线，本次纳入来源指纹，匹配变化后拒绝旧确认 |
| 本人查询与更正 | identity/staff_scope.py、inspection/staff_record_scope.py、attendance/staff_service.py | 使用账号→档案→有效关系→教学班/任务名单外键，不靠教师姓名授权；复用现有实现 |
| 学生名单与任务 | academic/roster_lifecycle.py、inspection/course_occurrences.py、inspection/service.py | 使用 student_id、有效期学籍及任务名单快照；姓名/学号快照属于历史展示，不替换成当前档案 |
| 组成员与排班 | volunteer/member_service.py、inspection/scheduling/private_constraints.py | 使用 student_id、volunteer_user_id 及成员/支援关系；不需改成姓名查找或复制另一份人库 |
| 账号绑定 | identity/staff_binding.py、identity/service.py | 身份验证后绑定档案，不从姓名猜登录账号；导入不创建已认证账号或绑定微信 |
| 授课关系管理范围 | academic/staff_repository.py | 原按教师档案学院筛选 LOCAL 关系，外院教师来本院授课时会归错管理方；改为课程负责学院管理本地关系，档案仍归教师学院；SHARED 不扩大 |
| 班级报表与明细 | report/repository.py、aggregation.py、ReportsView.vue | 原按班级名称归并并用姓名字段查负责人，Web 会用同名班猜 ID；改用名单冻结的学院/行政班 ID，明细增加人员与班级 ID、任务增加冻结班级集合，前端按 ID 展开 |

## 2. 执行顺序与文件边界

- [x] 回归先行：新增 tests/unit/test_import_person_links.py，验证课表及旧责任表关联、未确认不写、同名/未知仅提示、重复不重复建、人员变化409及关系范围。
- [x] 新增 importer/person_links.py：统一匹配、构造关系计划、写入与审计。工号优先并核对姓名；只填姓名需学校内有效档案唯一。多个教师逐人匹配。未知/同名不建虚假档案或账号。
- [x] 修改 importer/service.py、confirmation_diff.py、confirmation_set.py、scoped_service.py：把关联纳入普通课表/网格课表/旧责任区导入与确切确认集合。既有关系不被空白/缺行撤销，不因重导改写任职起始日。不同在任者需明确交接，不静默更换。
- [x] 修改 staff_adapter.py：专用关系导入使用同样的无歧义姓名口径。
- [x] 新增存量关联 preview/confirm 服务及 confirmation_router.py 入口：按学院及学期从已存课表、责任列生成计划，确认绑定人员基线、调用人和日期，支持补录档案后无需重导课表。只创建明确缺失关系；冲突交由现有人工交接/结束入口。
- [x] 新增 Web PersonLinkReview.vue：展示待补关联、已有关系及待处理原因，单独确认。TeachingAssignments、ClassResponsibilities 嵌入同一组件，保留手工调整入口。ImportReview 显示人员匹配概要和可读字段，取消“锚点/任命”为日常操作主线的表达。
- [x] 同步 API 契约、索引、OpenAPI 与当前状态，运行定向后端回归和 Web 构建，记录未覆盖的生产环境范围。

## 3. 规则与验收

1. 导入确认才建关系，未绑定账号的教职工也能先建立业务关系，之后验证绑定可继承本人范围。
2. 自动授课关联仅创建本院 LOCAL 关系，不凭相同姓名/课程名产生跨院 SHARED 授权。跨院任课可定位同校真实教职工，但只能关联本次授权学院的课程。
3. 有效期从本次确认日与学期开始日的较晚日期开始，至学期结束次日；不追溯授予历史任职。责任关系从确认日起，交接沿用现有显式流程。
4. 未匹配或冲突不阻断正式课表/学生资料保存，但明确标记“未建立对应教师权限”；不得显示为全部关联成功。
5. 有匹配写入时需要 staff.manage，普通资料维护权限不隐式升级为人员授权。无权限只保存原资料并提示由有权人员补关联。
6. 空白/缺行不撤销；重复导入不重复建；已有同一关系保持日期、版本和历史不变；不同在任者及有效期冲突需人工调整。
7. 不改写 TaskRosterMember、考勤历史、个人显示课表，不运行生产回填或部署。若未来引入多学校，应另做 Student.school_id 与绑定索引迁移，不能仅在前端拼接学校字段。

## 4. 验证范围

内存 SQLite 验证实际 ORM 导入、确认、关系与版本行为；现有 staff_importer 回归验证专用导入不退化。前端定向测试与类型/构建校验，必要时本地模拟 API 检查关联预览。此次不重复全量 MySQL 演练，不将本地验证表述为生产发布。

## 5. 追加报表补齐与兼容边界

- 已实现冻结班级身份键：同名不同 ID 不合并；改名不改变实体身份；缺失 ID 的旧行按冻结学院（缺失时按任务负责学院）与名称保留兼容分组，不回查当前学生归属填造历史 ID。
- 已实现负责人读取有效期关系。统计期间有交接时展示期间命中的人员姓名合集，不把新任者当作整段期间唯一负责人；只有从未建立正式关系的旧班级才使用原文字列兼容显示，有关系历史但区间无人时显示空。
- 已实现班级详情 ID 筛选、当前学生底册按已确认 class_id 读取及过期响应丢弃。当前底册仍是辅助显示，不参与后端正式分母；不按同名班补猜 ID，不按同名学生合并。
- 正式查询、统计、导出继续复用原授权任务集合，未增加根据姓名授权的入口。版本化周报新生成使用相同分组规则；已发布版本、名单快照、考勤历史不做后台批量重写。
- 原全局兼容导入入口没有明确学院，不自动建立人员权限。新能力在显式学院入口提供，沿用学院正式业务开关；未开启时不绕过开关、不根据主学院隐式授权。
- 本轮无数据库结构迁移，不运行生产补关联。部署后由有权管理员进入任课教师/班级负责人页面，一次核对并确认现有资料；未知/同名、换人、结束关系与历史学期仍需按提示处理。

## 6. 本次完成与验证记录

已完成上述代码、Web 入口、契约、索引与 OpenAPI（333 个路径、394 个操作）。修改在本地隔离工作区按功能提交；未合入 dev-main、未推送、未部署，未对生产运行补关联或变更任何开关。

- 最后一轮后端 66 项通过：`test_import_person_links`、`test_staff_importer`、`test_staff_management`、`test_scoped_importer`、`test_import_confirmation_set`、`test_report_class_identity`、`test_report_details`、`test_scoped_statistics`、`test_scoped_reports`。使用内存 SQLite，清除了 `CAMPUS_TEST_DATABASE_URL`；无跳过/失败。保留既有 Pydantic 弃用提示。
- 新增用例先观察失败再修实现；覆盖未确认不写、唯一工号/同名、工号前导零、学校模式网格 10—11 节、无 staff.manage 不授权、重复/跨文件幂等、过期预览、已结束关系不恢复、跨院授课关系管理，以及冻结班级 ID 与历史学籍变化、负责人有效期数据来源。
- 前端 7 项通过：导入向导、人员关联过期响应与确认版本、报表明细冻结 ID 筛选。`npm.cmd run build` 类型检查及生产构建通过，保留既有大 bundle 提示。
- 7 个关键后端文件定向 mypy 通过（`--follow-imports=silent --no-incremental`）；不是全仓类型检查结论。
- Ruff 对本次 19 个变动 Python 文件检查后，新增行诊断为 0。报表旧代码仍有 16 处既存 E501 长行，不将全量 Ruff 描述为通过；未修改规则或关闭门禁。`git diff --check` 通过。
- 未进行本轮真实 MySQL 并发、生产部署或微信真机验收；新增 Web 人员关联入口经过类型/构建和状态逻辑测试，未宣称真实浏览器联调已通过。

后续落地是发布本次版本并由有权学院管理员核对存量关联。解析不出来的档案、同名、课程换教师与责任人交接需要原始资料或明确的人工决定，不能用本轮自动匹配猜补。历史数据缺少冻结 ID 时保留兼容分组，不补造外键；多学校学号作用域迁移不属于本次单学校多学院升级。
