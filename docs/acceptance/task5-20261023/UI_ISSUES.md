# 页面与业务问题清单

[验收报告](REPORT.md) · [逐项清单](CASE_RESULTS.md)。日期2026-10-23，版本73a69fb6，测试学院2。下列3个业务问题来自真实页面结果；源码和数据库仅补充定位。本轮未修复应用。

## F01　高：导入资格成功，志愿者仍无法排班

**影响：**新学期批量导入的未绑定志愿者不能正常进入排班，页面资格及组织准备状态与实际可用性矛盾。T01、T14失败为同一个缺陷。

**入口/数据：**教师→教务资料→资料导入，04-志愿者资格.xlsx；V1/V2学号99000011/99000012，学院2、学期1、在籍、已导入有效资格；有效组2成员。

**实际复现：**

1. 导入04，确认保存；志愿者资格页两人显示“本学期有效”，微信未绑定。
2. 负责人建组2，添加两成员，普通课/全部授权班级，保存并启用；页面显示有效成员2、可进入排班预览。
3. 教师精确选2026-10-23数学课次，生成任务293，自动排班计划0安排，理由“本学期无有效志愿者资格或学生身份已停用”。
4. 返回列表同ID保留。只读核对两人ACTIVE、资格enabled=true、无UserAccount；未给他们补号。
5. 正向对照：教师选择V3(99000013)，点击“添加志愿者并选组→开通资格并加入所选组”；再对293计划和确认，真实派发V3成功，V3也未绑定微信。

**预期：**有效资格、成员和在籍均满足时，导入路径应准备与手工资格一致的无微信排班底册身份；真实微信绑定另行办理，不能成为提前排班条件。

**证据：**[导入资格有效](screenshots/36-qualification-two-unbound.jpg)、[组已启用](screenshots/30-group-enabled-confirmed.jpg)、[0安排原因](screenshots/34-task-generated-plan-unassigned.jpg)、[手工资格](screenshots/37-manual-qualification-third-student.jpg)、[派发成功](screenshots/39-one-task-assigned.jpg)、[只读补证](persistence-readback.json)。

**定位线索（固定源码73a69fb6）：**`backend/app/modules/importer/service.py:789` 使用 `_grant_volunteer_if_bound`；手工路径 `academic/service.py:1338` 的 `_grant_volunteer_role` 调用 `_ensure_student_user_account`。导入路径未建立缺失底册身份。建议按同一业务规则修复并覆盖新导入、重复导入及已有账号，不能给所有学生凭空授管理权限。

## F02　高：批量自习显示成功，实际未保存

**入口/数据：**教师→教务资料→正式课表→批量生成自习排课。文档验收A2，早自习，第7–7周，周二，第1–2节，地点“合成自习室QA”，其余选填留空。

**步骤与结果：**

1. 填写上述单班单周范围，确认批量生成1班。
2. 弹窗“批量生成排课成功”，覆盖1班、新建1教学班、排课1、关联3学生。
3. 返回正式课表，顶栏及课表自身周次均改为7，搜索“早自习”并查询，显示未检索到排课。
4. 只读查询学院2的排课，只有472/473两条数学、均ACTIVE/学期1/周6和7，无自习排课。

**预期：**成功后教学班、排课、周次及学生关联持久保存，重新查询可见；若未成功必须回滚并明确报错，不能返回成功计数。

**证据：**[生成表单](screenshots/52-study-generation-one-week-form.jpg)、[成功弹窗](screenshots/53-study-generation-success.jpg)、[保存后查询为空](screenshots/54-study-success-but-no-saved-schedule.jpg)、[数据库只读补证](persistence-readback.json)。

**定位线索（固定源码）：**`backend/app/modules/academic/scoped_self_study.py` 创建并flush对象后直接返回计数，没有走审计/提交；`scoped_writes.py:48` 的装饰器 `organization/service.py:63` 只负责异常回滚，不提交；`core/database.py:144` 的get_db结束只关闭Session。相邻选修批量路径通过 `_audit` 收尾。当前链路缺少成功事务收尾，与重查无记录一致。修复需验证整个生成事务及重复生成幂等，不能仅增加成功提示。

## F03　中：统计Excel标题写错学院

**入口/数据：**教师→统计报表，第6周，测试学院文档验收A，3人均正常；点击“导出到课率分析 (Excel)”。

**实际：**下载文件正常，四个工作表，数据为文档验收A1、数学、应到3实到3、100%；首页A1却是“人工智能学院 查课考勤多维数据分析看板”。

**预期：**标题按当前授权统计学院生成，不能固定成别的学院。当前证据说明报表归属错误，不证明跨院数据泄露。

**证据：**[页面范围](screenshots/46-weekly-statistics-three-normal.jpg)、[实际下载Excel](attendance_analytics_w6.xlsx)、[内容核对](export-content-check.json)。固定源码 `backend/app/modules/report/artifacts.py:624` 为该学院名硬编码。

## UI-01　首次责任关系HTTP500，单文件复测已成功

初次上传08文件识别出现HTTP500，有原始文字观察，原14号截图无效已隔离。恢复后同账号、同文件单独选择，识别正确→预览2新增→确认保存成功；统计页显示班主任/辅导员。见[图48](screenshots/48-responsibility-import-single-file-retest.jpg)、[49](screenshots/49-responsibility-preview-retest.jpg)、[50](screenshots/50-responsibility-import-saved.jpg)。

**当前状态：未再次复现，不作为持续阻断。** 首次混合批次条件尚未完整重放，不能反过来保证始终无错。如再现，记录批次、时间和请求关联号后定位，勿直接加入历史基线。

## UI-02　权限设置显示内部代码，名称和按钮换行难读

教师→账号与权限→负责人→本院功能设置，出现academic.read、assignment.manage、inspection.generate等内部代码，与中文能力混排。宽屏负责人姓名与“设置Web密码”等按钮也挤成多行。建议使用清楚的业务名称和范围说明，改善列宽。功能保存本身已实测成功，不能把布局问题夸大为授权失败。

证据：[17](screenshots/17-manager-appointment-recheck.jpg)、[18](screenshots/18-permission-codes-and-statistics.jpg)。

## UI-03　旧人工审核文案仍误导用户

账号页“提交审核”“初审学生异议”，统计页“已审核通过·纳入统计分母”仍在。当前提交即生效、异议一次审核，旧文字会引导用户寻找已取消流程。仅文案存在，不能证明旧审核路由仍可写入。

证据：[18](screenshots/18-permission-codes-and-statistics.jpg)、[46](screenshots/46-weekly-statistics-three-normal.jpg)。Excel另有“已审核堂数”旧称。

## UI-04　缺学号错误没有给出具体字段和行

上传07错误学生表，源第2行缺学号，确认禁用正确；展开问题只有“没有可核对的条目，请检查资料类型和文件内容”，未指出第2行/学号。建议明确字段及修正方法，避免反复猜表类型。见[06](screenshots/06-invalid-import-blocked.jpg)。

## UX-05　待核对：排除后仍计入后续待处理

初次点“本次不导入”07并保存有效学生表后，待处理仍列07。可能设计为保留待修正，当前不认定数据Bug；按钮应明确排除当前组还是移出整队列。见[07](screenshots/07-students-and-staff-saved.jpg)。

## UI-06　窄屏展开菜单没有登出入口

窄屏侧栏隐藏后点击“展开功能菜单”，仅业务链接，未见账号身份或登出；恢复宽屏可见“登出→”且可实际使用。影响手机Web或窄侧栏退出/换号。见[19](screenshots/19-narrow-menu-without-logout.jpg)。浏览器尺寸变化本身不是产品Bug。

## UI-07　负责人登录后身份仍只显示学生

完成有效任命后qa_manager_a可查课表、建组、访问统计，身份区却显示“验收负责人甲 学生”。建议显示当前有效管理身份或完整业务角色，避免用户误以为委任失败。见[20](screenshots/20-manager-web-login.jpg)。

## UI-08　已审核异议仍提示“再作决定”

审核通过后当前考勤v2，页面仍显示“发起异议时v1，现在v2……在申诉期间被改过……再作决定”。本次v2正是此次审批形成；已办项没有再次审批按钮，功能正常，但文字暗示审核前发生外部更正。应对已办/本次审核版本变化区分显示。见[45](screenshots/45-objection-approved-version-two.jpg)。

## UI-09　考勤更正理由默认填入未核实事实

更正弹窗预填“补交假条，辅导员已签批”，当前测试实际是迟到核对更正，默认理由可能造成不实审计。本轮已主动替换成合成核对理由，未沿用该默认值。建议为空或使用placeholder，不将特定审批事实当默认真实记录。见[41](screenshots/41-correction-form-before-submit.jpg)。

## UI-10　截止历史不显示办理人

页面历史仅版本、截止、修改时间、说明；未显示办理账号。已成功修改并恢复，不能因此判定没有后台审计，但用户无法按原验收步骤在此确认是谁办理。见[56](screenshots/56-deadline-history-version-two.jpg)。

## 验收边界

06通用多表文件被明确拒绝并要求拆分，是实际格式边界；原B3专用格式仍未测试，不能称为B3回归。有效图片已打开，不代表签名过期/跨账号/OSS越权已通过。直接报表下载不等于不可变历史周报。页面访问审批和旧标签失效归为执行工具问题，没有列成系统Bug。
