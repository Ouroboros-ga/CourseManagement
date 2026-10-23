# 页面、代码与需求核对证据

基准：2026-10-23，源码 `73a69fb6d843f5eb8d31630f5340b2342d186b62`。已只读确认服务器 current 指针为 `20261023-task3-73a69fb6d8`，与本轮核对源码一致。主工作区仍在较早分支，文档核对使用匹配部署的隔离源码，未切换或覆盖共享工作区。

## 浏览器实见（PAGE）

用户在 ChatGPT Work 浏览器登录后，使用该现有管理会话逐页查看。该账号可见校级菜单，不能把这个会话当成四种普通角色逐一登录的证据。只访问页面、页签、帮助和未提交表单；没有点击正式保存、导入、派发、审批或更正。

| 证据号 | 页面及实见内容 | 边界 |
| --- | --- | --- |
| PAGE-01 | 登录页及工作台；七个日常入口、辅助菜单、学院学期/教学周、学期准备和待办链接 | 未改账号或授权 |
| PAGE-02 | 教务资料：正式课表、教学班与分类、任课教师、资料导入、课程类型、发布给学生 | 未导入或正式发布 |
| PAGE-03 | 统一资料导入中心：下载标准模板包、选择文件夹、选择 ZIP 压缩包、选择文件／补充修正文件；展开重名/编号冲突帮助 | 没有选择上传文件；核对后和完成页按钮由源码补证 |
| PAGE-04 | 志愿者组织列表和已有组织详情；成员名单、查课范围与排班规则、导入成员 Excel、添加成员、请假记录与审批、查看跨院支援、粘贴学号批量加入 | 未改成员/资格。准备状态会异步加载，不能以瞬时禁用判定功能未实现 |
| PAGE-05 | 更多管理：复用上学期成员与规则、编辑名称与有效期、维护组织默认规则、负责人交接、停用组织、删除组织 | 仅展开菜单 |
| PAGE-06 | 组规则表单：课程类型、全部授权班级/指定班级、本人课程冲突、本班回避、日周上限、统计口径、课程例外与移动缓冲 | 未保存 |
| PAGE-07 | 查课安排：任务与排班、选择具体课次、组范围抽查、未来变更处置、提交截止；智能排班（筛选全部）、人工指派、编辑、详情与点名册、导出筛选结果 | 未生成排班计划，未派发 |
| PAGE-08 | 人工指派表单：智能推荐可用志愿者、搜索、审批/改派说明（选填）、取消、确认指派 | 打开后取消，没有选择或确认 |
| PAGE-09 | 选择具体课次：课程类型、执行组、智能抽查、下发排班；智能抽查参数对话框含均衡抽查/重点班级、上限和比例 | 未勾选、未计算推荐、未下发 |
| PAGE-10 | 提交截止：按日期的北京时间截止、版本、保存、历史；页面说明原截止考核事实保留 | 未调整截止 |
| PAGE-11 | 考勤与现场照片：按课次/按行政班/学生明细、只看异常、查看名单与照片、记录与照片 | 只读打开已有记录，不摘录学生名单 |
| PAGE-12 | 学生异议：全部审核、待审核、审核通过、审核驳回；说明一次审核生效 | 当前无异议数据，裁决表单由源码补证，不能写成实际处理成功 |
| PAGE-13 | 统计报表：三种归属轴、周次、行政班/教学班/详细考勤页签；Word 详表、自习 Excel、到课率分析 Excel | 没有把直接导出写成版本周报生成；未下载真实明细 |
| PAGE-14 | 账号与权限：教工与超级管理员、学生工作负责人与授权、委任、统计开关、Web 密码与功能设置的角色条件 | 当前无负责人行；逐人功能编辑由源码补证；没有授权/重置口令 |

其余后台维护表单及小程序页面按下列源码逐项核对，若本轮未进入对应页面，在手册中保持“源码核对”的证据级别，不冒充浏览器或真机通过。

## 主要代码证据（SRC）

路径均相对上述固定提交；可在仓库按路径或下列文案查找。当前文档在主工作区，但引用的产品实现以固定提交为准。

| 证据号 | 文件/模块 | 核对内容 |
| --- | --- | --- |
| SRC-NAV | apps/admin-web/src/navigation/workspaceNavigation.ts；router/index.ts；stores/session.ts | 实际导航、角色/能力和上下文切换 |
| SRC-IMPORT | components/academic/ImportCenter.vue、ImportWizard.vue、ImportReview.vue、ImportHome.vue、importLabels.ts；backend/app/modules/importer/catalog.py、service.py、confirmation_set.py、attendance_roster.py | 八类主目录、分组独立保存、预览/确认、冲突与首表名单 |
| SRC-ACADEMIC | components/academic/TeachingSchedule.vue；components/campus/ScopedAcademicBrowser.vue、CourseTypeManager.vue、SharedIdentity.vue、AcademicPublication.vue | 课表、自习、分类、共享身份、发布 |
| SRC-STUDENT | components/students/StudentDirectory.vue、StudentGroupEnrollment.vue、EnrollmentHistory.vue；components/campus/StudentHandoff.vue；backend/app/modules/academic/enrollment_service.py | 学生与班级、资格、绑定、学籍和交接 |
| SRC-STAFF | components/staff/StaffDirectory.vue、TeachingAssignments.vue、ClassResponsibilities.vue、PersonLinkReview.vue、StaffAttendancePanel.vue；backend/app/modules/academic/staff_* | 档案、绑定、授课、责任及本人视图 |
| SRC-GROUP | components/organizations/OrganizationDetail.vue；components/campus/GroupManager.vue、GroupMembers.vue、GroupMemberImport.vue、GroupRuleEditor.vue、GroupUnavailability.vue、GroupSemesterPreparation.vue、GroupHandover.vue | 组织、资格与成员分离、支援、请假、规则、复用与交接 |
| SRC-INSPECTION | views/TaskListView.vue；components/TaskDrawer.vue；components/campus/GroupSampling.vue、CollegeDeadlines.vue、ConfigurationImpacts.vue；components/inspection/AssignmentPlanDialog.vue | 生成和排班分阶段、任务及更正、截止、未来影响 |
| SRC-CORRECTION | backend/app/modules/inspection/service.py 的 correction_window、_correction_protected、revise_submission、withdraw_submission；report/repository.py 的 _approved_submission_exists | 两小时不重置；任何异议/管理更正保护结论；仅有效提交参与统计 |
| SRC-ATTENDANCE | views/AttendanceView.vue、ObjectionsView.vue；components/attendance/*；backend/app/modules/attendance/*、objection/* | 结果分组、照片、普通/归档更正、一次异议审核 |
| SRC-REPORT | views/ReportsView.vue；api/reports.ts；backend/app/modules/report/router.py、scoped_router.py、service.py | 按周看板与直接导出；版本周报接口未被当前页面调用 |
| SRC-PERMISSION | views/UsersView.vue、SchoolView.vue、SettingsView.vue；components/accounts/*；backend/app/modules/identity/policy.py、role_scope.py、management_scope.py、repository.py | 教师/负责人/超管边界；有效任命、功能设置和最后有效超管保护 |
| SRC-MINIAPP | apps/wechat-miniapp/miniprogram/app.json 及 pages/login、index、profile、task/list、task/detail、task/abnormal、record/list、record/appeal、admin 的 WXML/JS | 源码真实入口和按钮；没有个人课表、本人请假或教工绑定页面 |
| SRC-API | docs/openapi.json；backend/app/main.py 的实际路由挂载 | 端侧接口核对；有接口不等于已有按钮 |
| SRC-REQUIREMENT | docs/product/CAMPUS_MANAGEMENT_PRD.md；docs/development/IMPLEMENTATION_STATUS.md；docs/PERMISSIONS.md | 需求意图和历史演进；旧“未实现”文字不覆盖当前代码，代码残留标签也不覆盖已确认规则 |

## 当前开关和边界

只读取了与功能有关的配置键：教务发布、学院配置、学院教务范围、学院正式业务、组织排班均启用。纠错窗口和异议期未显式覆盖，当前代码默认分别为 120 分钟、7 天；服务端时钟及返回结果为准。没有读取或记录生产口令、密钥、绑定码和签名地址。

文档列出的写入结果是任务 5 的验收预期，不能用本轮只读浏览声称已经通过。本轮未重跑 CI 或集成测试，功能手册不对当前 CI 状态或历史失败是否解决做结论。

## 后续补充的实际页面观察

| 证据号 | 页面及实见入口 | 本轮范围 |
| --- | --- | --- |
| PAGE-15 | 学生与班级：学生、行政班与绑定；按日期查看学籍；学籍变更与交接；班级负责人；添加学生、班级管理、生成绑定码、批量生成绑定码并导出 Excel、删除 | 只查看入口；未复制名单、签发码、建号或删除 |
| PAGE-16 | 操作日志：查询、逐行查看、分页 | 仅核对页面结构，未把日志内容复制到手册 |
| PAGE-17 | 平台与学期设置：编辑当前学期、开启新学期、学期与教学日历、节次作息时间表、查课业务规则、学校作息模板、归档、添加停补课规则；仍显示重置本学期业务数据 | 仅查看；重置未点击。源码守卫确认当前学院模式拒绝旧重置路线；普通教师与超管可写动作不同 |
| PAGE-18 | 教职工档案：查询、新增教职工、批量生成绑定码并导出 Excel、档案、关联账号、解绑账号、绑定码 | 仅查看；未关联、解绑、创建或签发 |

用户已明确说明当前数据库是测试库，并允许模拟导入、创建和删除；本轮继续按“先完成文档，暂不开展大量写入测试”的范围执行。未把既有资料当一次性样本。本轮没有正式业务写入。

补充代码证据：TaskListView.vue 的删除预览区分彻底删除未使用项与历史保留项；后者考勤统计不变，恢复只回日常列表。StaffAttendancePanel.vue 已有本人授课/班级的名单与认定、历史、授权更正及单课次改教室，故不能将所有历史查看或所有教工工作功能列为无页面。inspection/group_transfer.py 已挂载执行组预览/确认接口，当前 Web 未找到调用。

小程序附证明异议的兼容风险证据：固定提交中 pages/record/appeal/index.js:70 将 file_id 列表 map(Number)，较大编号可能丢失精度；J28 列为待真机复核用例，不把它称为已复现线上失败。纠错截止格式证据在 pages/task/detail/index.js:298—305，格式输出缺少完整日期/时分表示；J10 仍以服务端实际时间为准。
