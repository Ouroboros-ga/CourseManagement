import { request, setAccessToken, clearAccessToken } from './http'

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
}

export interface CurrentUser {
  user_id: string
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
