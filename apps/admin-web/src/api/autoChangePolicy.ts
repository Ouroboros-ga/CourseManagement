import { request } from './http'
import { listGroups } from './campus'

export interface AutoChangePolicy {
  enabled: boolean
  version: number
  authorizer_user_id: string | null
}
export interface AutoChangePolicyUpdate {
  semester_id: string
  enabled: boolean
  current_version: number
}
const path = (cid: string, gid: string) =>
  `/api/v1/colleges/${encodeURIComponent(cid)}/groups/${encodeURIComponent(gid)}/inspection/auto-change-policy`

export const autoChangePolicyApi = {
  listGroups,
  get: (cid: string, gid: string, sid: string) => request<AutoChangePolicy>(
    `${path(cid, gid)}?${new URLSearchParams({ semester_id: sid })}`
  ),
  update: (cid: string, gid: string, body: AutoChangePolicyUpdate) => request<AutoChangePolicy>(
    path(cid, gid), { method: 'PUT', body: JSON.stringify(body) }
  )
}
