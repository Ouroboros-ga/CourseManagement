import { request } from './http'

export interface OverviewItem {
  id: string; label: string; count: number
  status: 'ACTION_REQUIRED' | 'COMPLETE' | 'AVAILABLE' | 'EMPTY'
  scope_label: string
  destination: { path: string; query: Record<string, string> }
}
export interface WorkspaceOverview {
  college_id: string; semester_id: string; semester_status: string; as_of: string
  items: OverviewItem[]; scheduling_note: string
  runtime: { academic_scoped: boolean; business_scoped: boolean; scheduling: boolean }
}
export const getWorkspaceOverview = (cid: string, sid: string) => request<WorkspaceOverview>(
  `/api/v1/colleges/${encodeURIComponent(cid)}/overview?semester_id=${encodeURIComponent(sid)}`)
