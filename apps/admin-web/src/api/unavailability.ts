import { request } from './http'
export interface Unavailability {
  id: string; student_id: string; name?: string; student_no?: string
  starts_at: string; ends_at: string; reason: string; lock_version: number
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELED'; scope: 'ALL_GROUPS'
}
export interface UnavailabilityBody { student_id: string; semester_id: string; starts_at: string; ends_at: string; reason: string }
export interface UnavailabilityImpact { revision: string; lock_version: number; retained_assignment_count: number; scope: 'ALL_GROUPS' }
const root = (cid: string, gid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/groups/${encodeURIComponent(gid)}/unavailability`
const json = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) })
export const listUnavailability = (cid: string, gid: string, sid: string, page: number) => request<{ items: Unavailability[]; total: number }>(`${root(cid,gid)}?${new URLSearchParams({ semester_id: sid, page: String(page) })}`)
export const createUnavailability = (cid: string, gid: string, body: UnavailabilityBody) => request<Unavailability>(root(cid,gid), json(body))
export const getUnavailabilityImpact = (cid: string, gid: string, id: string) => request<UnavailabilityImpact>(`${root(cid,gid)}/${id}/impact`)
export const decideUnavailability = (cid: string, gid: string, row: Unavailability, status: 'APPROVED' | 'REJECTED' | 'CANCELED', note: string, impact_revision = '') => request<Unavailability>(`${root(cid,gid)}/${row.id}/decision`, json({ status, note, lock_version: row.lock_version, impact_revision }))
