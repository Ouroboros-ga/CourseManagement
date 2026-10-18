/** 导入资料的中文文案与人话化概要：资料准备首页、三步向导、最近导入列表共用。 */

export const targetLabels: Record<string, string> = {
  faculty_staff: '教职工档案',
  class_responsibility: '班级责任关系',
  teaching_assignment: '授课关系补充表',
  admin_roster: '行政班与学生名单',
  class_duty: '班主任与责任区辅导员',
  grid_timetable: '教务网格课表',
  timetable: '标准课表长表',
  volunteer: '志愿者学期资格底册',
  roster: '教学班补充名单',
  elective_course: '选修课/分层课'
}

export const batchStatusLabels: Record<string, string> = {
  PREVIEW: '草稿待核对',
  CONFIRMED: '已保存',
  FAILED: '保存失败',
  EXPIRED: '草稿已过期'
}

/** 确认保存后的结果概要（来自批次 summary，只翻译已知字段）。 */
export function savedSummary(summary: Record<string, unknown>): string {
  const labels: Record<string, string> = {
    classes_created: '新增行政班',
    students_created: '新增学生',
    students_updated: '核对学生',
    courses_created: '新增课程',
    course_created: '新增课程',
    teaching_classes_created: '新增教学班',
    teaching_class_created: '新增教学班',
    schedules_created: '新增课表',
    schedule_created: '新增课表',
    qualification_created: '新增资格',
    qualification_updated: '更新资格',
    roster_after: '保存后名单人数',
    students_linked: '关联学生',
    class_duties_count: '更新班级责任人',
    person_links_created: '已建立人员关联',
    person_links_pending: '人员待关联'
  }
  if (summary.unchanged && !summary.person_links_created && !summary.person_links_pending) return '资料未变化，已跳过重复写入'
  return (
    Object.entries(summary)
      .filter(([key]) => labels[key])
      .map(([key, value]) => `${labels[key]} ${value}`)
      .join('；') || '资料已保存'
  )
}

/** 核对阶段的一句话概要；数据不足时返回空串，由调用方隐藏该行。 */
export function previewSummary(target: string, summary: Record<string, unknown>): string {
  const num = (key: string) => Number(summary[key] || 0)
  switch (target) {
    case 'faculty_staff':
      return `识别到 ${num('row_total')} 名教职工，新增 ${num('create_count')} 名、修改 ${num('update_count')} 名`
    case 'admin_roster': {
      const classes = num('classes_count')
      const students = num('student_count')
      const duties = num('class_duties_count')
      if (!classes && !students && !duties) return ''
      const parts: string[] = []
      if (classes) parts.push(`${classes} 个行政班`)
      if (students) parts.push(`${students} 名学生`)
      if (duties) parts.push(`${duties} 条班级责任人`)
      return `识别到 ${parts.join('、')}`
    }
    case 'grid_timetable': {
      const courses = num('course_count')
      const occurrences = num('total_occurrences')
      if (!courses && !occurrences) return ''
      const className = String(summary.class_name || '') || '未命名'
      return `识别到班级「${className}」${courses} 门课程、${occurrences} 条上课安排`
    }
    case 'timetable': {
      const classes = num('teaching_class_count')
      const courses = num('course_count')
      const rows = num('schedule_count')
      if (!classes && !rows) return ''
      return `识别到 ${classes} 个教学班、${courses} 门课程、${rows} 条上课安排`
    }
    case 'volunteer': {
      const total = num('student_total')
      if (!total) return ''
      return `识别到 ${total} 名志愿者，其中 ${num('enabled_count')} 名启用`
    }
    case 'roster': {
      const total = num('student_total')
      if (!total) return ''
      return `识别到 ${total} 名名单学生`
    }
    default:
      return ''
  }
}
