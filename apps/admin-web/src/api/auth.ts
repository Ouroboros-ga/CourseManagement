import { setAccessToken, clearAccessToken } from './http'
import { request } from './workspaceHttp'

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
}

export interface CurrentUser {
  id: string
  username: string
  display_name: string
  roles: string[]
  permissions: string[]
  bound_student_id?: string | null
  student_number?: string | null
  real_name?: string | null
  class_name?: string | null
  lock_version: number
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const data = await request<LoginResult>('/api/v1/auth/web/login', {
    method: 'POST',
    body: JSON.stringify({ username, password })
  })
  setAccessToken(data.access_token)
  return data
}

export async function refresh(): Promise<string | null> {
  try {
    const data = await request<{ access_token: string }>('/api/v1/auth/refresh', {
      method: 'POST'
    })
    setAccessToken(data.access_token)
    return data.access_token
  } catch {
    clearAccessToken()
    return null
  }
}

export async function getMe(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/v1/me')
}

export async function logout(): Promise<void> {
  try {
    await request('/api/v1/auth/logout', { method: 'POST' })
  } finally {
    clearAccessToken()
  }
}

export async function batchIssueBindingTokens(body: {
  class_id?: string
  student_ids?: string[]
  days_valid?: number
  reason?: string
}): Promise<{
  total_issued: number
  items: Array<{
    student_id: string
    student_no: string
    name: string
    class_name?: string
    college?: string
    binding_code: string
    expires_at: string
    is_bound: boolean
  }>
}> {
  return request('/api/v1/students/batch-binding-tokens', {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

export async function exportBindingTokensExcel(body: {
  class_id?: string
  student_ids?: string[]
  days_valid?: number
  reason?: string
}): Promise<Blob> {
  return request<Blob>('/api/v1/students/export-binding-tokens', {
    method: 'POST',
    body: JSON.stringify(body)
  }, false, 'blob')
}

export async function resetStudentBinding(userId: string, body?: { new_student_no?: string | null; reason?: string }) {
  return request(`/api/v1/users/${userId}/student-binding-reset`, {
    method: 'POST',
    body: JSON.stringify(body || { reason: '管理员在后台重置解绑' })
  })
}


