import { request } from './http'

export interface TeacherAccountItem {
  can_view_school_summary?: boolean
  id: string
  username: string
  display_name: string
  status: 'ACTIVE' | 'DISABLED' | 'BANNED'
  lock_version: number
  roles?: string[]
}

export interface ListTeacherAccountsResult {
  items: TeacherAccountItem[]
  total: number
  page: number
  page_size: number
}

export interface TeacherAccountCreatePayload {
  can_view_school_summary?: boolean
  college_id: string
  username: string
  display_name: string
  initial_password?: string
}

export interface TeacherAccountUpdatePayload {
  can_view_school_summary?: boolean
  display_name?: string
  status?: 'ACTIVE' | 'DISABLED'
  lock_version: number
}

export interface RoleAssignmentTarget {
  id: string
  username?: string | null
  display_name: string
  status: 'ACTIVE' | 'DISABLED' | 'BANNED'
  roles: string[]
  lock_version: number
  student_id?: string | null
  has_wechat: boolean
}

export interface OptionalPermissionState {
  code: string
  enabled: boolean
}

export interface OptionalPermissionTargetItem {
  id: string
  display_name: string
  status: string
  permissions: OptionalPermissionState[]
  lock_version: number
}

export interface OptionalPermissionTargetsResponse {
  items: OptionalPermissionTargetItem[]
  configurable_codes: string[]
}

export async function listTeacherAccounts(params: {
  role_codes?: string[]
  page?: number
  page_size?: number
  query?: string
  status?: string
} = {}): Promise<ListTeacherAccountsResult> {
  const q = new URLSearchParams()
  params.role_codes?.forEach(code => q.append('role_codes', code))
  if (params.page) q.set('page', String(params.page))
  if (params.page_size) q.set('page_size', String(params.page_size))
  if (params.query) q.set('query', params.query.trim())
  if (params.status) q.set('status', params.status)

  const qs = q.toString()
  return request<ListTeacherAccountsResult>(`/api/v1/teacher-accounts${qs ? `?${qs}` : ''}`)
}

export async function createTeacherAccount(body: TeacherAccountCreatePayload): Promise<TeacherAccountItem> {
  return request<TeacherAccountItem>('/api/v1/teacher-accounts', {
    method: 'POST',
    body: JSON.stringify({
      college_id: body.college_id,
      can_view_school_summary: body.can_view_school_summary ?? false,
      username: body.username.trim(),
      display_name: body.display_name.trim(),
      initial_password: body.initial_password || 'Teacher@123456'
    })
  })
}

export async function updateTeacherAccount(
  userId: string | number,
  body: TeacherAccountUpdatePayload
): Promise<TeacherAccountItem> {
  return request<TeacherAccountItem>(`/api/v1/teacher-accounts/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(body)
  })
}

export async function resetTeacherPassword(
  userId: string | number,
  body: { new_password?: string; lock_version?: number } = {}
): Promise<void> {
  return request<void>(`/api/v1/accounts/${userId}/password-reset`, {
    method: 'POST',
    body: JSON.stringify({
      new_password: body.new_password || 'Teacher@123456',
      lock_version: body.lock_version ?? 0
    })
  })
}

export async function resetManagerPassword(
  userId: string | number,
  body: { new_password?: string; lock_version?: number } = {}
): Promise<void> {
  return request<void>(`/api/v1/accounts/${userId}/password-reset`, {
    method: 'POST',
    body: JSON.stringify({
      new_password: body.new_password || 'Student@123456',
      lock_version: body.lock_version ?? 0
    })
  })
}

export async function changeMyPassword(body: {
  old_password: string
  new_password: string
}): Promise<void> {
  return request<void>('/api/v1/me/password-change', {
    method: 'POST',
    body: JSON.stringify({
      current_password: body.old_password,
      old_password: body.old_password,
      new_password: body.new_password
    })
  })
}

export function listRoleTargetPage(params: { page?: number; keyword?: string; role_code?: string; student_candidates?: boolean } = {}) {
  const query = new URLSearchParams({ paged: 'true', page: String(params.page || 1), page_size: '50' })
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.role_code) query.set('role_code', params.role_code)
  if (params.student_candidates) query.set('student_candidates', 'true')
  return request<{ items: RoleAssignmentTarget[]; assignable_roles: string[]; total: number }>(`/api/v1/role-assignment-targets?${query}`)
}

export async function listRoleTargets(studentIds?: string[]): Promise<{ items: RoleAssignmentTarget[]; assignable_roles: string[] }> {
  if (studentIds?.length === 0) return { items: [], assignable_roles: [] }
  return request<{ items: RoleAssignmentTarget[]; assignable_roles: string[] }>(`/api/v1/role-assignment-targets${studentIds ? '?' + new URLSearchParams(studentIds.map(id => ['student_ids', id])) : ''}`)
}

export async function updateUserRoles(
  userId: string | number,
  payload: {
    roles: string[]
    lock_version: number
    reason?: string
  }
): Promise<{ roles: string[]; lock_version: number }> {
  return request(`/api/v1/users/${userId}/roles`, {
    method: 'PUT',
    body: JSON.stringify({
      roles: payload.roles,
      lockVersion: payload.lock_version,
      reason: payload.reason
    })
  })
}

export async function listOptionalPermissionTargets(userIds?: string[]): Promise<OptionalPermissionTargetsResponse> {
  if (userIds?.length === 0) return { items: [], configurable_codes: [] }
  return request(`/api/v1/optional-permission-targets${userIds ? '?' + new URLSearchParams(userIds.map(id => ['user_ids', id])) : ''}`)
}

export async function updateOptionalPermission(
  userId: string | number,
  code: string,
  payload: {
    enabled: boolean
    lock_version: number
    reason?: string
  }
): Promise<{ code: string; enabled: boolean; lock_version: number }> {
  return request(`/api/v1/users/${userId}/optional-permissions/${code}`, {
    method: 'PUT',
    body: JSON.stringify({
      enabled: payload.enabled,
      lockVersion: payload.lock_version,
      reason: payload.reason
    })
  })
}
