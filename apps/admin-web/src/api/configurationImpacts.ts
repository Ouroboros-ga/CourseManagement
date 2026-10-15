import { request } from './http'
export interface ConfigurationImpactItem {
  id: string; task_id: string; source_kind: string; source_id: string; source_version: number
  snapshot: { inspection_date: string; course_name: string; group_id: string | null; activity_start_at: string | null; activity_end_at: string | null }
  status: 'OPEN' | 'KEEP' | 'CANCEL' | 'REASSIGNED'; lock_version: number
  current_task_lock_version: number; assignment_revision: string; canceled: boolean
  current_assignment: { id: string; volunteer_user_id: string } | null
}
const root = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/configuration-impacts`
export const listConfigurationImpacts = (cid: string, page: number, status: string) => request<{ items: ConfigurationImpactItem[]; total: number }>(`${root(cid)}?${new URLSearchParams({ page: String(page), page_size: '50', ...(status ? { status } : {}) })}`)
export const resolveConfigurationImpact = (cid: string, row: ConfigurationImpactItem, decision: 'KEEP' | 'CANCEL' | 'REASSIGNED', note: string) => request<ConfigurationImpactItem>(`${root(cid)}/${row.id}/resolve`, { method: 'POST', body: JSON.stringify({ decision, note, lock_version: row.lock_version, task_lock_version: row.current_task_lock_version, assignment_revision: row.assignment_revision }) })
