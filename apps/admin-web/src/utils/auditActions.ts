/** 审计动作码的中文呈现。动作码由后端各服务写入，稳定且不可枚举校验，
 *  因此这里只做展示层翻译：分段词典 + 少量整码修正，未收录的段保留原文。 */

const SEGMENTS: Record<string, string> = {
  // 作用域
  academic: '教务', account: '账号', assignment: '排班', attendance: '考勤',
  binding_token: '绑定凭证', campus: '学院配置', file: '文件', identity: '身份',
  import: '资料导入', inspection: '查课', objection: '学生异议', optional_permission: '可选权限',
  permission: '权限', report: '报表', role: '角色', staff: '教工',
  staff_binding_token: '教工绑定凭证', student: '学生', submission: '查课提交',
  submission_deadline: '提交截止', volunteer: '志愿者',
  // 资源
  admin_class: '行政班', administrator: '管理员', audience: '受众', batch: '批次',
  calendar_override: '校历', college: '学院', course: '课程', course_schedule: '课表',
  enrollment: '学籍', expected_count_adjust: '应到人数', grant: '授权', group: '志愿者组',
  impact: '变更影响', manager: '负责人', occurrence: '实际课次', offering: '开课',
  onboarding: '入职资料', ownership: '存量归属', password: '密码', period_definition: '节次作息',
  plan: '排班方案', registry: '注册表', relation: '任职关系', resource: '资源',
  roster: '名单', school: '学校', school_time: '学校默认作息',
  school_time_template: '学校作息模板', semester: '学期', student_data: '学生资料',
  task: '查课任务', teacher: '教师', time: '本院作息', time_profile: '作息方案',
  timetable: '正式发布', type: '课程类型', version: '报表版本',
  volunteer_qualification: '志愿者资格', archived: '历史', change_request: '调班申请',
  owner: '负责人', real_number: '真实号码', day_update: '按日截止',
  // 动作
  adjust: '调整', archive: '归档', assign: '任免', auto_link: '自动关联', auto_run: '自动排班',
  backfill: '回填', batch_delete: '批量删除', batch_issue: '批量发放', bind: '绑定',
  bootstrap: '初始化', cancel: '取消', change: '变更', commit: '提交', confirm: '确认',
  correct: '更正', create: '新建', decide: '处理', delete: '删除', delete_retained: '删除并保留',
  effective: '生效', final_review: '终审', functions: '功能配置', generate: '生成',
  handover: '移交', issue: '发放', link: '关联', location_change: '换教室',
  manual_set: '手动指派', migrate: '迁移', prepare: '学期准备', preview: '预览',
  publish: '发布', purge: '清理', read: '查看', replace: '替换',
  request: '申请', resolve: '处置', restore: '恢复', restore_deleted: '恢复已删除',
  rebind: '换绑', review: '审核', revoke: '撤销', revoke_group_deleted: '随组撤销',
  save: '保存', self_unbind: '本人解绑', set: '设置', settle: '结算', start: '启动',
  status: '状态变更', task_review: '任务复核', transfer: '转移', update: '修改', upsert: '保存',
  wechat_new_account: '微信新账号'
}

// 分段拼出来会读不通的整码修正。
const WHOLE: Record<string, string> = {
  'academic.audience.confirm': '教务·确认学生受众',
  'academic.enrollment.task_review': '教务·学籍变更任务复核',
  'academic.offering.link': '教务·关联开课与教学班',
  'academic.period_definition.delete': '教务·删除节次作息',
  'academic.period_definition.upsert': '教务·保存节次作息',
  'academic.school_time.publish': '教务·发布学校默认作息',
  'academic.semester.reset_data': '教务·学期重置业务数据',
  'academic.teaching_class.roster.replace': '教务·替换教学班名单',
  'academic.time.publish': '教务·发布本院作息',
  'academic.course.batch_elective_create': '教务·批量新建公选课',
  'account.administrator.bootstrap': '账号·初始化平台管理员',
  'account.manager.functions': '账号·配置负责人可选权限',
  'account.teacher.college': '账号·配置教师学院归属',
  'assignment.change_request.review': '排班·调班申请审核',
  'attendance.archived.correct': '考勤·更正历史考勤',
  'attendance.expected_count_adjust': '考勤·调整应到人数',
  'campus.grant.revoke_group_deleted': '学院配置·随组撤销授权',
  'campus.impact.resolve': '学院配置·处置变更影响',
  'campus.ownership.backfill': '学院配置·回填存量归属',
  'campus.resource.restore': '学院配置·恢复资源',
  'import.batch.preview': '资料导入·预览批次',
  'import.batch.confirm': '资料导入·确认批次',
  'import.student_data.confirm': '资料导入·确认学生资料',
  'inspection.task.delete_retained': '查课·删除任务并保留记录',
  'inspection.task.group.transfer': '查课·任务转组',
  'objection.create': '学生异议·提交',
  'objection.final_review': '学生异议·终审',
  'optional_permission.update': '可选权限·修改',
  'permission.registry.migrate': '权限注册表·迁移',
  'report.version.start': '报表·开始生成版本',
  'report.version.publish': '报表·发布版本',
  'staff.onboarding.real_number': '教工·补录真实号码',
  'staff.relation.auto_link': '教工·自动关联任职关系',
  'student.self_unbind': '学生·本人解绑',
  'submission.create': '查课提交·提交',
  'submission_deadline.day_update': '提交截止·按日调整',
  'submission_deadline.settle': '提交截止·结算',
  'volunteer.owner.handover': '志愿者·移交组负责人',
  'volunteer.semester.prepare': '志愿者·学期准备',
  'volunteer.unavailability.decide': '志愿者·处理不可用申请',
  'volunteer.unavailability.request': '志愿者·提交不可用申请'
}

export function describeAuditAction(code: string): string {
  const whole = WHOLE[code]
  if (whole) return whole
  return code.split('.').map(segment => SEGMENTS[segment] || segment).join('·')
}

/** 后端当前会写入的全部动作码，用于筛选下拉；出现新码时列表落后，但仍可手输过滤。 */
export const AUDIT_ACTION_CODES: string[] = [
  'academic.admin_class.create', 'academic.admin_class.delete', 'academic.admin_class.update',
  'academic.audience.confirm', 'academic.calendar_override.create', 'academic.calendar_override.delete',
  'academic.college.create', 'academic.course.batch_elective_create', 'academic.course.create',
  'academic.course.update', 'academic.course_schedule.create', 'academic.course_schedule.delete',
  'academic.course_schedule.update', 'academic.enrollment.cancel', 'academic.enrollment.change',
  'academic.enrollment.effective', 'academic.enrollment.task_review', 'academic.occurrence.location_change',
  'academic.offering.link', 'academic.period_definition.delete', 'academic.period_definition.upsert',
  'academic.school_time.publish', 'academic.school_time_template.create', 'academic.school_time_template.import',
  'academic.school_time_template.revise', 'academic.school_time_template.status', 'academic.semester.archive',
  'academic.semester.create', 'academic.semester.reset_data', 'academic.semester.update',
  'academic.student.batch_delete', 'academic.student.create', 'academic.student.delete',
  'academic.student.update', 'academic.teaching_class.create', 'academic.teaching_class.roster.replace',
  'academic.teaching_class.update', 'academic.time.publish', 'academic.time_profile.archive',
  'academic.time_profile.bind', 'academic.time_profile.create', 'academic.time_profile.draft.save',
  'academic.timetable.publish', 'academic.volunteer_qualification.upsert',
  'account.administrator.bootstrap', 'account.administrator.create', 'account.manager.functions',
  'account.password.change', 'account.password.reset', 'account.teacher.college', 'account.teacher.create',
  'assignment.auto_run', 'assignment.change_request.create', 'assignment.change_request.review',
  'assignment.manual_set', 'assignment.plan.commit', 'attendance.archived.correct',
  'attendance.expected_count_adjust', 'binding_token.batch_issue', 'binding_token.issue',
  'binding_token.revoke', 'campus.college.create', 'campus.college.update', 'campus.grant.create',
  'campus.grant.revoke', 'campus.grant.revoke_group_deleted', 'campus.group.create', 'campus.group.publish',
  'campus.group.update', 'campus.impact.resolve', 'campus.ownership.backfill', 'campus.resource.restore',
  'campus.school.create', 'campus.type.create', 'campus.type.delete', 'campus.type.update',
  'file.purge', 'file.upload', 'identity.wechat_new_account', 'import.batch.confirm', 'import.batch.preview',
  'import.student_data.confirm', 'inspection.roster.revise', 'inspection.task.cancel', 'inspection.task.delete',
  'inspection.task.delete_retained', 'inspection.task.generate', 'inspection.task.group.transfer',
  'inspection.task.restore', 'inspection.task.restore_deleted', 'inspection.task.update',
  'objection.create', 'objection.final_review', 'optional_permission.update', 'permission.registry.migrate',
  'report.version.publish', 'report.version.start', 'role.assign', 'staff.bind', 'staff.onboarding.confirm',
  'staff.onboarding.create', 'staff.onboarding.real_number', 'staff.relation.auto_link',
  'staff_binding_token.issue', 'staff_binding_token.revoke', 'student.bind', 'student.rebind',
  'student.self_unbind', 'submission.create', 'submission_deadline.day_update', 'submission_deadline.settle',
  'volunteer.owner.handover', 'volunteer.semester.prepare', 'volunteer.unavailability.decide',
  'volunteer.unavailability.request'
]

const RESOURCES: Record<string, string> = {
  academic_publication: '教务正式发布', administrative_class: '行政班', assignment_change_request: '调班申请',
  assignment_confirmation_plan: '排班方案', attendance_record: '考勤记录', calendar_override: '校历停补课',
  college: '学院', college_time_version: '本院作息版本', configuration_impact_item: '配置变更影响',
  course: '课程', course_schedule: '课表', enrollment_change: '学籍变更', faculty_staff: '教工档案',
  file_object: '文件', group_semester_preparation: '志愿者组学期准备', identity_binding_token: '绑定凭证',
  import_batch: '导入批次', inspection_assignment: '查课排班', inspection_submission: '查课提交',
  inspection_task: '查课任务', objection: '学生异议', occurrence_location: '实际课次教室',
  period_definition: '节次作息', report_version: '报表版本', school: '学校',
  school_semester_default: '学校默认作息', semester: '学期', staff_binding_token: '教工绑定凭证',
  staff_onboarding: '教工入职资料', student: '学生', student_data_plan: '学生资料批次',
  submission_deadline_day: '按日提交截止', task_deadline_assessment: '任务截止认定',
  teaching_class: '教学班', user_account: '账号', user_permission: '账号可选权限',
  volunteer_group: '志愿者组', volunteer_qualification: '志愿者资格',
  CampusOwnership: '存量归属', CourseType: '课程类型', ScopedGrant: '范围授权', VolunteerGroup: '志愿者组'
}

export function describeAuditResource(type: string): string {
  return RESOURCES[type] || type
}

/** 已知资源类型，用于筛选下拉；未收录的类型仍会原样出现在日志里。 */
export const AUDIT_RESOURCE_TYPES: string[] = Object.keys(RESOURCES)
