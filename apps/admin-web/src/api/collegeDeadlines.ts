import { request } from './http'

export interface CollegeDeadline {
  semester_id: string
  inspection_date: string
  deadline_at: string
  version: number
  task_count: number
  reason?: string | null
}
export interface DeadlineVersion {
  version_no: number
  deadline_at: string
  created_at: string
  reason?: string | null
}
const base = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/submission-deadlines/days`
const query = (sid: string) => `?semester_id=${encodeURIComponent(sid)}`
export const collegeDeadlineApi = {
  list: (cid: string, sid: string) => request<CollegeDeadline[]>(base(cid) + query(sid)),
  update: (cid: string, sid: string, day: string, body: { time: string; lock_version: number; reason?: string }) =>
    request<CollegeDeadline>(`${base(cid)}/${encodeURIComponent(day)}${query(sid)}`, {
      method: 'PUT', body: JSON.stringify(body)
    }),
  history: (cid: string, sid: string, day: string) => request<DeadlineVersion[]>(
    `${base(cid)}/${encodeURIComponent(day)}/versions${query(sid)}`)
}
