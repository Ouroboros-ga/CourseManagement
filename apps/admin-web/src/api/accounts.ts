import { request } from './http'

export interface TeacherAccountItem {
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
  username: string
  display_name: string
  initial_password?: string
}

export interface TeacherAccountUpdatePayload {
  display_name?: string
  status?: 'ACTIVE' | 'DISABLED'
  lock_version: number
}

export interface RoleAssignmentTarget {
  user_id: string
  username: string
  display_name: string
  roles: string[]
  lock_version: number
}

export async function listTeacherAccounts(params: {
  page?: number
  page_size?: number
  query?: string
  status?: string
} = {}): Promise<ListTeacherAccountsResult> {
  const q = new URLSearchParams()
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
  body: { new_password?: string } = {}
): Promise<void> {
  return request<void>(`/api/v1/teacher-accounts/${userId}/password-reset`, {
    method: 'POST',
    body: JSON.stringify({
      new_password: body.new_password || 'Teacher@123456'
    })
  })
}

export async function changeMyPassword(body: {
  old_password: string
  new_password: string
}): Promise<void> {
  return request<void>('/api/v1/me/password-change', {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

export async function listRoleTargets(): Promise<{ items: RoleAssignmentTarget[] }> {
  return request<{ items: RoleAssignmentTarget[] }>('/api/v1/role-assignment-targets')
}

export async function updateUserRoles(
  userId: string | number,
  roles: string[]
): Promise<void> {
  return request<void>(`/api/v1/users/${userId}/roles`, {
    method: 'PUT',
    body: JSON.stringify({ roles })
  })
}
