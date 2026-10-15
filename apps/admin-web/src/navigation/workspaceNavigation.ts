/** 菜单、路由与页面生命周期共用的描述；实际数据授权仍由服务端执行。 */
export type ContextMode = 'semester' | 'current'
export interface WorkspacePage {
  id: string
  label: string
  path: string
  permissions: string[]
  superOnly?: boolean
}
export interface WorkspaceActor {
  hasPermission: (code: string) => boolean
  hasAnyRole: (...codes: string[]) => boolean
}
export const primaryPages: WorkspacePage[] = [
  { id: 'home', label: '工作台', path: '/dashboard/home', permissions: [] },
  { id: 'academic', label: '教务资料', path: '/dashboard/academic', permissions: ['academic.read', 'academic.manage', 'import.execute', 'course_schedule.import', 'academic.course_type.read'] },
  { id: 'students', label: '学生与班级', path: '/dashboard/students', permissions: ['student.read', 'student.manage', 'academic.read', 'identity.binding.manage'] },
  { id: 'organizations', label: '志愿者组织', path: '/dashboard/organizations', permissions: ['volunteer.read', 'volunteer.manage', 'volunteer.group.read'] },
  { id: 'inspections', label: '查课安排', path: '/dashboard/inspections', permissions: ['inspection.read', 'inspection.generate', 'assignment.manage', 'submission.read'] },
  { id: 'attendance', label: '考勤与异议', path: '/dashboard/attendance', permissions: ['attendance.read', 'objection.read', 'objection.final_review'] },
  { id: 'reports', label: '统计报表', path: '/dashboard/reports', permissions: ['statistics.read', 'report.read', 'statistics.school.read'] }
]
export const auxiliaryPages: WorkspacePage[] = [
  { id: 'school', label: '学校与学院管理', path: '/dashboard/school', permissions: [], superOnly: true },
  { id: 'users', label: '账号与权限', path: '/dashboard/users', permissions: ['role.assign', 'administrator_account.manage', 'teacher_account.manage'] },
  { id: 'settings', label: '学期与平台设置', path: '/dashboard/settings', permissions: ['academic.manage'] },
  { id: 'help', label: '帮助与操作说明', path: '/dashboard/help', permissions: [] }
]
export function canAccessPage(id: string, actor: WorkspaceActor): boolean {
  const page = [...primaryPages, ...auxiliaryPages].find(row => row.id === id)
  if (!page) return false
  if (page.superOnly) return actor.hasAnyRole('SUPER_ADMIN')
  return !page.permissions.length || page.permissions.some(code => actor.hasPermission(code))
}
export function pageContextMode(id: string, tab = ''): ContextMode {
  if (['students', 'school', 'users', 'help'].includes(id)) return 'current'
  if (id === 'organizations') return ['members', 'qualifications', 'unavailability', 'preparation'].includes(tab) ? 'semester' : 'current'
  if (id === 'academic' && ['types', 'courses'].includes(tab)) return 'current'
  return 'semester'
}
export function workspaceContextKey(context: {
  userId: string; collegeId: string; authorizationRevision: string; semesterId: string
}, mode: ContextMode): string {
  return JSON.stringify([context.userId, context.collegeId, context.authorizationRevision, mode === 'semester' ? context.semesterId : 'current'])
}
export function legacyDestination(id: string, query: Record<string, unknown>, hash = '') {
  let path = '/dashboard/home', tab = ''
  if (id === 'tasks' || id === 'reviews') { path = '/dashboard/inspections'; tab = 'tasks' }
  if (id === 'objections') { path = '/dashboard/attendance'; tab = 'objections' }
  if (id === 'volunteers') {
    const qualification = query.tab === 'qualifications' || query.is_volunteer === 'true'
    path = qualification ? '/dashboard/organizations' : '/dashboard/students'
    tab = qualification ? 'qualifications' : 'directory'
  }
  if (id === 'schedule') {
    const importing = query.import === '1' || query.tab === 'imports'
    path = importing || query.tab === 'master' ? '/dashboard/academic' : '/dashboard/inspections'
    tab = importing ? 'imports' : query.tab === 'master' ? 'timetable' : 'selection'
  }
  return { path, query: { ...query, ...(tab ? { tab } : {}) }, hash }
}
