/** 全校操作日志读取。刻意使用 http 的原始 request：审计是全校入口，
 *  走 workspaceHttp 会在 business_scoped 打开时被改写成 /colleges/{cid}/audit-logs，
 *  页面会静默退化成只看当前学院。 */
import { request } from './http'

export interface AuditLogRow {
  id: string
  actor_user_id: string | null
  actor_name: string | null
  actor_username: string | null
  action: string
  resource_type: string
  resource_id: string | null
  created_at: string
}

export interface AuditLogDetail extends AuditLogRow {
  reason: string | null
  request_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface AuditLogPage { items: AuditLogRow[]; total: number; page: number; page_size: number }

export interface AuditLogFilter {
  from: string; to: string; action?: string; resourceType?: string; resourceId?: string
  page?: number; pageSize?: number
}

/** 服务端窗口上限；超出会被拒绝，因此前端先挡住再发请求。 */
export const AUDIT_WINDOW_MAX_DAYS = 31

export function auditWindowDays(from: string, to: string): number {
  return Math.floor((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86400000) + 1
}

export function listAuditLogs(filter: AuditLogFilter) {
  const query = new URLSearchParams({
    date_from: new Date(`${filter.from}T00:00:00+08:00`).toISOString(),
    date_to: new Date(`${filter.to}T23:59:59+08:00`).toISOString(),
    page: String(filter.page || 1),
    page_size: String(filter.pageSize || 50)
  })
  if (filter.action) query.set('action', filter.action)
  if (filter.resourceType) query.set('resource_type', filter.resourceType)
  if (filter.resourceId) query.set('resource_id', filter.resourceId)
  return request<AuditLogPage>(`/api/v1/audit-logs?${query}`)
}

export const auditLogDetail = (id: string) =>
  request<AuditLogDetail>(`/api/v1/audit-logs/${encodeURIComponent(id)}`)
