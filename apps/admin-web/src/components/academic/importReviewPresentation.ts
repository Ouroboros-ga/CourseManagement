import type { ImportSetPlan } from '../../api/importer'

export type ReviewFile = ImportSetPlan['files'][number]
type Issue = ReviewFile['issues'][number]

const fields: Record<string, string> = {
  staff_no: '工号', student_no: '学号', student_count: '名单人数', duty: '职责',
  effective_from: '生效日期', effective_to: '结束日期（当日不再生效）', name: '姓名',
  class_name: '班级', class_code: '教学班码', course_name: '课程', course_code: '课程代码',
  weekday: '星期', start_period: '开始节次', end_period: '结束节次', weeks: '周次',
  classroom: '教室', teacher: '任课教师', teacher_staff_no: '教师工号',
  head_teacher: '班主任', counselor: '辅导员', head_teacher_staff_no: '班主任工号',
  counselor_staff_no: '辅导员工号', college: '学院', grade_year: '入学年级',
  enabled: '启用', roster_ready: '排班底册已准备', student_nos: '学号名单', present: '在名单中', status: '状态',
  college_id: '学院编号', grade: '年级', phone: '联系电话', email: '邮箱',
  staff_name: '责任人', teacher_name: '任课教师', anchor_type: '授课范围',
  covered_colleges: '覆盖学院', staff_type: '教职工类别',
}
const hidden = new Set(['kind', 'staff_id', 'id', 'action', 'student_sources'])

function weeksLabel(value: unknown[]): string {
  if (!value.length) return '未填写'
  if (!value.every(v => Number.isInteger(v) && Number(v) > 0)) return value.join('、')
  const numbers = [...new Set(value as number[])].sort((a, b) => a - b)
  const ranges: string[] = []
  for (let i = 0; i < numbers.length; i++) {
    const start = numbers[i]!
    let end = start
    while (i + 1 < numbers.length && numbers[i + 1] === end + 1) end = numbers[++i]!
    ranges.push(start === end ? String(start) : `${start}—${end}`)
  }
  return `第${ranges.join('、')}周`
}

export function describeImportValue(value: Record<string, unknown> | null): string {
  if (!value) return '无原资料'
  return Object.entries(value)
    .filter(([key]) => !hidden.has(key) && !key.startsWith('source_') && !key.startsWith('_source_'))
    .map(([key, val]) => {
      let display: unknown = val
      if (key === 'weekday' && Number(val) >= 1 && Number(val) <= 7) display = `星期${'一二三四五六日'[Number(val) - 1]}`
      else if (key === 'weeks' && Array.isArray(val)) display = weeksLabel(val)
      else if (val === 'HEAD_TEACHER') display = '班主任'
      else if (val === 'COUNSELOR') display = '辅导员'
      else if (val === 'ACTIVE') display = '有效'
      else if (val === 'INACTIVE') display = '停用'
      else if (key === 'anchor_type' && val === 'LOCAL') display = '本院教学班'
      else if (key === 'anchor_type' && val === 'SHARED') display = '共享课程'
      else if (Array.isArray(val)) display = val.join('、')
      else if (typeof val === 'boolean') display = val ? '是' : '否'
      else if (typeof val === 'object' && val !== null) display = JSON.stringify(val)
      return `${fields[key] || key}：${display ?? '未填写'}`
    }).join('\n')
}

export function groupIssues(file: ReviewFile) {
  // 老预览也保留兼容：只把原有的“教学班码 · 人员：原因”告警识别为关联提示。
  const isPersonLink = (issue: Issue) => issue.severity !== 'error' && (
    issue.code === 'PERSON_LINK_PENDING' || (!issue.code && / · .+：/.test(issue.message)
      && /教职工|教师|授课|责任人|同一行政班|该学期|工号与姓名/.test(issue.message))
  )
  const courses = new Map<string, string>()
  for (const change of file.changes) {
    const course = change.after?.course_name || change.before?.course_name
    if (course) courses.set(change.key.split('/')[0]!, String(course))
  }
  const people = file.issues.filter(isPersonLink).map(issue => {
    const match = /^(.*?) · (.*?)：(.*)$/s.exec(issue.message)
    const anchor = match?.[1] || ''
    const course = courses.get(anchor)
    const className = String(file.summary.class_name || '')
    return {
      context: course ? [className, course].filter(Boolean).join(' · ')
        : className || (file.target === 'admin_roster' ? anchor : '') || '人员关系',
      person: match?.[2] || '待关联人员',
      reason: match?.[3] || issue.message,
    }
  })
  return {
    errors: file.issues.filter(issue => issue.severity === 'error'),
    warnings: file.issues.filter(issue => issue.severity !== 'error' && !isPersonLink(issue)),
    people,
  }
}

export function personLinkNotice(count: number): string {
  return `${count} 项关系待关联（不是教师人数）。不影响课表保存，仅影响相应教师查看与操作本人课程；关联完成前不会开放教师权限。`
}
