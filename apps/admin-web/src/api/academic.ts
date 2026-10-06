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

export interface StudentItem {
  id: string
  student_no: string
  name: string
  administrative_class_id?: string | null
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

export async function listStudents(params: {
  page?: number
  page_size?: number
  keyword?: string
  status?: string
} = {}): Promise<{ items: StudentItem[]; total: number; page: number; page_size: number }> {
  const q = new URLSearchParams()
  if (params.page) q.set('page', String(params.page))
  q.set('page_size', String(params.page_size || 50))
  if (params.keyword) q.set('keyword', params.keyword)
  if (params.status) q.set('status', params.status)
  return request(`/api/v1/academic/students?${q.toString()}`)
}

export async function listVolunteerQualifications(semesterId: string): Promise<{
  items: VolunteerQualificationItem[]
  total: number
}> {
  const q = new URLSearchParams()
  q.set('semester_id', semesterId)
  q.set('page_size', '100')
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
