/**
 * 统一 HTTP 客户端封装 (遵循技术方案与 API 契约)
 * - access token 仅存放于模块内存中，严禁写入 localStorage/URL
 * - refresh token 由服务端的 HttpOnly Cookie 发送 (credentials: 'include')
 * - 401 自动串行刷新，至多重试一次
 * - 成功信封返回 payload.data，204 返回 undefined
 */

let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function clearAccessToken(): void {
  accessToken = null
}

export interface ApiErrorPayload {
  code: string
  message: string
  fieldErrors?: Record<string, string>
  requestId?: string
}

export class ApiError extends Error {
  status: number
  code: string
  fieldErrors?: Record<string, string>
  requestId?: string

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code
    this.fieldErrors = payload.fieldErrors
    this.requestId = payload.requestId
  }
}

let refreshPromise: Promise<string | null> | null = null

async function executeRefresh(): Promise<string | null> {
  try {
    const res = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json'
      }
    })
    if (!res.ok) {
      clearAccessToken()
      return null
    }
    const json = await res.json()
    const newToken = json.data?.access_token || null
    setAccessToken(newToken)
    return newToken
  } catch {
    clearAccessToken()
    return null
  } finally {
    refreshPromise = null
  }
}

export async function request<T = unknown>(
  url: string,
  init: RequestInit = {},
  isRetry = false
): Promise<T> {
  const headers = new Headers(init.headers || {})
  headers.set('Accept', 'application/json')

  if (!headers.has('Content-Type') && init.body && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }

  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const response = await fetch(url, {
    ...init,
    headers,
    credentials: 'include'
  })

  // 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  // 401 Unauthorized handling (token expired)
  if (response.status === 401 && !isRetry && !url.includes('/auth/refresh') && !url.includes('/auth/web/login')) {
    if (!refreshPromise) {
      refreshPromise = executeRefresh()
    }
    const refreshedToken = await refreshPromise
    if (refreshedToken) {
      return request<T>(url, init, true)
    }
    throw new ApiError(401, { code: 'UNAUTHORIZED', message: '登录状态已失效，请重新登录' })
  }

  if (!response.ok) {
    let payload: any = {
      code: 'UNKNOWN_ERROR',
      message: `请求失败: HTTP ${response.status}`
    }
    try {
      const data = await response.json()
      if (data && typeof data === 'object') {
        payload = data
        if (!payload.message && payload.detail) {
          if (typeof payload.detail === 'string') {
            payload.message = payload.detail
          } else if (Array.isArray(payload.detail)) {
            const fieldMap: Record<string, string> = {
              username: '教工工号/账号',
              display_name: '真实姓名',
              initial_password: '初始密码',
              current_password: '当前密码',
              old_password: '当前旧密码',
              new_password: '新密码',
              lock_version: '版本号'
            }
            payload.message = payload.detail
              .map((item: any) => {
                const lastLoc = item.loc ? item.loc[item.loc.length - 1] : ''
                const fieldName = fieldMap[lastLoc] || lastLoc
                return fieldName ? `【${fieldName}】${item.msg}` : item.msg
              })
              .join('；')
          }
        }
      }
    } catch {
      // Non-json response
    }
    throw new ApiError(response.status, payload)
  }

  const result = await response.json()
  return result.data as T
}
