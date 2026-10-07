import { request } from './http'

export interface SemesterItem {
  id: string
  code: string
  name: string
  status: 'ACTIVE' | 'ARCHIVED'
  start_date: string
  total_weeks: number
  lock_version: number
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
  q.set('page_size', '1000')
  return request(`/api/v1/academic/volunteer-qualifications?${q.toString()}`)
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

