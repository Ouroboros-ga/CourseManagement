import { request } from './http'

export interface SemesterItem {
  id: string
  code: string
  name: string
  status: 'ACTIVE' | 'ARCHIVED'
  start_date: string
  end_date?: string
  first_monday?: string
  total_weeks: number
  lock_version?: number
  created_at: string
}

export interface TeachingClassItem {
  id: string
  semester_id: string
  course_id: string
  class_code?: string | null
  class_name: string
  status: string
}

export interface AdministrativeClassItem {
  id: string
  class_code: string
  class_name: string
  grade_year?: number | null
  major_name?: string | null
  college?: string | null
  status: string
}

export interface StudentItem {
  id: string
  student_no: string
  name: string
  administrative_class_id?: string | null
  administrative_class_name?: string | null
  status: 'ACTIVE' | 'SUSPENDED' | 'GRADUATED'
  unassigned_task_count?: number
}

export interface VolunteerQualificationItem {
  id: string
  semester_id: string
  student_id: string
  enabled: boolean
  created_by?: string | null
}

export interface BindingTokenResult {
  token_id: string
  student_id: string
  plaintext_code: string
  expires_at: string
}

export async function listSemesters(status = 'ACTIVE'): Promise<{ items: SemesterItem[]; total: number }> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('page_size', '50')
  return request<{ items: SemesterItem[]; total: number }>(`/api/v1/academic/semesters?${params.toString()}`)
}

export async function listTeachingClasses(semesterId: string): Promise<{ items: TeachingClassItem[]; total: number }> {
  const params = new URLSearchParams()
  params.set('semester_id', semesterId)
  params.set('page_size', '100')
  return request<{ items: TeachingClassItem[]; total: number }>(`/api/v1/academic/teaching-classes?${params.toString()}`)
}

export async function listAdministrativeClasses(params?: {
  college?: string
  status?: string
  keyword?: string
  page_size?: number
}): Promise<{ items: AdministrativeClassItem[]; total: number }> {
  const q = new URLSearchParams()
  q.set('page_size', String(params?.page_size || 100))
  if (params?.college) q.set('college', params.college)
  if (params?.status) q.set('status', params.status)
  if (params?.keyword) q.set('keyword', params.keyword)
  return request<{ items: AdministrativeClassItem[]; total: number }>(`/api/v1/academic/administrative-classes?${q.toString()}`)
}

export async function listStudents(params: {
  page?: number
  page_size?: number
  keyword?: string
  status?: string
  administrative_class_id?: string | number
  college?: string
  is_volunteer?: boolean
  semester_id?: string | number
} = {}): Promise<{ items: StudentItem[]; total: number; page: number; page_size: number }> {
  const q = new URLSearchParams()
  if (params.page) q.set('page', String(params.page))
  q.set('page_size', String(params.page_size || 50))
  if (params.keyword) q.set('keyword', params.keyword)
  if (params.status) q.set('status', params.status)
  if (params.administrative_class_id) q.set('administrative_class_id', String(params.administrative_class_id))
  if (params.college) q.set('college', params.college)
  if (params.is_volunteer !== undefined) q.set('is_volunteer', String(params.is_volunteer))
  if (params.semester_id) q.set('semester_id', String(params.semester_id))
  return request(`/api/v1/academic/students?${q.toString()}`)
}

export async function listVolunteerQualifications(semesterId: string): Promise<{
  items: VolunteerQualificationItem[]
  total: number
}> {
  const q = new URLSearchParams()
  q.set('semester_id', semesterId)
  q.set('page_size', '200')
  const res = await request<{ items: VolunteerQualificationItem[]; total: number }>(
    `/api/v1/academic/volunteer-qualifications?${q.toString()}`
  )
  const items = [...(res.items || [])]
  let currentPage = 1
  while (items.length < res.total && currentPage * 200 < res.total) {
    currentPage++
    q.set('page', String(currentPage))
    const nextRes = await request<{ items: VolunteerQualificationItem[]; total: number }>(
      `/api/v1/academic/volunteer-qualifications?${q.toString()}`
    )
    if (!nextRes.items?.length) break
    items.push(...nextRes.items)
  }
  return { items, total: res.total }
}

export async function upsertVolunteerQualification(payload: {
  semester_id: number
  student_id: number
  enabled: boolean
  reason?: string
}): Promise<VolunteerQualificationItem> {
  return request('/api/v1/academic/volunteer-qualifications', {
    method: 'PUT',
    body: JSON.stringify(payload)
  })
}

export async function issueBindingToken(studentId: string, reason = '管理端发放绑定码'): Promise<BindingTokenResult> {
  return request(`/api/v1/students/${studentId}/binding-tokens`, {
    method: 'POST',
    body: JSON.stringify({ reason })
  })
}

export async function revokeBindingToken(tokenId: string, reason = '管理端作废'): Promise<{ token_id: string }> {
  return request(`/api/v1/binding-tokens/${tokenId}/revoke`, {
    method: 'POST',
    body: JSON.stringify({ reason })
  })
}

export interface RoleTargetUser {
  id: string
  username: string | null
  display_name: string
  status: string
  roles: string[]
  lock_version: number
  student_id?: string | null
  has_wechat?: boolean
}

export async function listRoleTargets(): Promise<{ items: RoleTargetUser[]; assignable_roles: string[] }> {
  return request('/api/v1/role-assignment-targets')
}

export async function createStudent(payload: {
  student_no: string
  name: string
  administrative_class_id?: number
  reason?: string
}): Promise<StudentItem> {
  return request('/api/v1/academic/students', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function createSemester(payload: {
  code: string
  name: string
  start_date: string
  end_date: string
  first_monday: string
  total_weeks?: number
  init_default_periods?: boolean
  reason?: string
}): Promise<SemesterItem> {
  return request('/api/v1/academic/semesters', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export interface MasterTimetableItem {
  id: string
  semester_id: string
  course_id: string
  course_code: string
  course_name: string
  teaching_class_id: string
  teaching_class_code?: string | null
  teaching_class_name: string
  weekday: number
  start_period: number
  end_period: number
  classroom?: string | null
  weeks: number[]
  status: string
  enrolled_student_count: number
  is_physical_education: boolean
  is_inspectable: boolean
  administrative_classes: string[]
}

export async function getMasterTimetable(params: {
  semester_id: string | number
  week_no?: number
  weekday?: number
  administrative_class_id?: number
  keyword?: string
}): Promise<{ items: MasterTimetableItem[]; total: number }> {
  const q = new URLSearchParams()
  q.set('semester_id', String(params.semester_id))
  if (params.week_no !== undefined) q.set('week_no', String(params.week_no))
  if (params.weekday !== undefined) q.set('weekday', String(params.weekday))
  if (params.administrative_class_id !== undefined) q.set('administrative_class_id', String(params.administrative_class_id))
  if (params.keyword) q.set('keyword', params.keyword)
  return request(`/api/v1/academic/master-timetable?${q.toString()}`)
}

export async function batchCreateElectiveCourse(payload: {
  semester_id: number
  course_name: string
  course_code?: string
  teaching_classes: Array<{
    class_code: string
    class_name?: string
    weekday: number
    start_period: number
    end_period: number
    weeks: number[]
    classroom?: string
    student_nos?: string[]
  }>
  reason?: string
}): Promise<any> {
  return request('/api/v1/academic/teaching-classes/batch-elective', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export interface SemesterResetResult {
  semester_id: string
  cleared_tasks_count: number
  cleared_schedules_count: number
  cleared_teaching_classes_count: number
  cleared_volunteer_qualifications_count: number
  cleared_calendar_overrides_count: number
}

export async function resetSemesterData(
  semesterId: string | number,
  payload: { confirm_name: string; reason?: string }
): Promise<SemesterResetResult> {
  return request(`/api/v1/academic/semesters/${semesterId}/reset-data`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export interface AdminClassDeleteResult {
  class_id: string
  class_name: string
  deleted_students_count: number
}

export async function deleteAdministrativeClass(
  classId: string | number,
  params?: { cascade_students?: boolean; reason?: string }
): Promise<AdminClassDeleteResult> {
  const q = new URLSearchParams()
  if (params?.cascade_students !== undefined) q.set('cascade_students', String(params.cascade_students))
  if (params?.reason) q.set('reason', params.reason)
  return request(`/api/v1/academic/administrative-classes/${classId}?${q.toString()}`, {
    method: 'DELETE'
  })
}

export async function deleteStudent(studentId: string | number, reason?: string): Promise<void> {
  const q = new URLSearchParams()
  if (reason) q.set('reason', reason)
  return request(`/api/v1/academic/students/${studentId}?${q.toString()}`, {
    method: 'DELETE'
  })
}

export interface StudentBatchDeleteResult {
  deleted_count: number
  deleted_ids: string[]
}

export async function batchDeleteStudents(
  studentIds: (string | number)[],
  reason?: string
): Promise<StudentBatchDeleteResult> {
  return request('/api/v1/academic/students/batch-delete', {
    method: 'POST',
    body: JSON.stringify({
      student_ids: studentIds.map(Number),
      reason
    })
  })
}

export interface PeriodDefinitionItem {
  id: string
  semester_id: string
  period_no: number
  start_time: string | null
  end_time: string | null
}

export async function listPeriodDefinitions(semesterId: string | number): Promise<{ items: PeriodDefinitionItem[] }> {
  return request(`/api/v1/academic/semesters/${semesterId}/period-definitions`)
}

export async function upsertPeriodDefinition(
  semesterId: string | number,
  periodNo: number,
  body: { start_time?: string | null; end_time?: string | null; reason?: string }
): Promise<PeriodDefinitionItem> {
  return request(`/api/v1/academic/semesters/${semesterId}/period-definitions/${periodNo}`, {
    method: 'PUT',
    body: JSON.stringify(body)
  })
}

export async function deletePeriodDefinition(
  semesterId: string | number,
  periodId: string | number,
  reason?: string
): Promise<void> {
  const q = new URLSearchParams()
  if (reason) q.set('reason', reason)
  return request(`/api/v1/academic/semesters/${semesterId}/period-definitions/${periodId}?${q.toString()}`, {
    method: 'DELETE'
  })
}

export interface CalendarOverrideItem {
  id: string
  semester_id: string
  date: string
  override_type: 'STOP' | 'MAKEUP'
  source_teaching_week?: number | null
  source_teaching_weekday?: number | null
  reason?: string | null
}

export async function listCalendarOverrides(semesterId: string | number): Promise<{ items: CalendarOverrideItem[] }> {
  return request(`/api/v1/academic/semesters/${semesterId}/calendar-overrides`)
}

export async function createCalendarOverride(
  semesterId: string | number,
  payload: {
    date: string
    override_type: 'STOP' | 'MAKEUP'
    source_teaching_week?: number
    source_teaching_weekday?: number
    reason?: string
  }
): Promise<CalendarOverrideItem> {
  return request(`/api/v1/academic/semesters/${semesterId}/calendar-overrides`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function deleteCalendarOverride(
  semesterId: string | number,
  overrideId: string | number,
  reason?: string
): Promise<void> {
  const q = new URLSearchParams()
  if (reason) q.set('reason', reason)
  return request(`/api/v1/academic/semesters/${semesterId}/calendar-overrides/${overrideId}?${q.toString()}`, {
    method: 'DELETE'
  })
}

export async function updateSemester(
  semesterId: string | number,
  payload: {
    name?: string
    start_date?: string
    end_date?: string
    first_monday?: string
    total_weeks?: number
    status?: 'ACTIVE' | 'ARCHIVED'
    reason?: string
  }
): Promise<SemesterItem> {
  return request(`/api/v1/academic/semesters/${semesterId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export async function exportCourseSchedulesExcel(semesterId: string | number): Promise<Blob> {
  const token = localStorage.getItem('access_token') || ''
  const response = await fetch(`/api/v1/course-schedules/export?semester_id=${semesterId}`, {
    headers: {
      Authorization: `Bearer ${token}`
    }
  })
  if (!response.ok) {
    throw new Error(`课表导出失败: HTTP ${response.status}`)
  }
  return response.blob()
}


