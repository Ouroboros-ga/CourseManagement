import { request } from './http'
export interface SharedMeeting { weekday: number; start_period: number; end_period: number; room: string; teacher: string; weeks: number[]; times?: { week: number; start: string | null; end: string | null }[] }
export interface SharedFacts { semester_id: string; course_name: string; meetings: SharedMeeting[] }
export interface IdentityCandidate { teaching_class_id: string; college_id: string; college_name: string; class_name: string; facts: SharedFacts; already_linked: boolean }
export interface IdentityPreview { revision: string; facts: SharedFacts; already_linked: boolean; effective_from: string; historical_tasks_unchanged: boolean }
const root = (cid: string, tid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/academic/teaching-classes/${encodeURIComponent(tid)}/shared-identity`
export const identityCandidates = (cid: string, tid: string) => request<{ items: IdentityCandidate[]; automatic_merge: boolean; message?: string }>(`${root(cid, tid)}/candidates`)
export const previewIdentity = (cid: string, tid: string, target_teaching_class_id: string, reason: string) => request<IdentityPreview>(`${root(cid, tid)}/preview`, { method: 'POST', body: JSON.stringify({ target_teaching_class_id, reason }) })
export const confirmIdentity = (cid: string, tid: string, target_teaching_class_id: string, reason: string, revision: string) => request(`${root(cid, tid)}/confirm`, { method: 'POST', body: JSON.stringify({ target_teaching_class_id, reason, revision }) })
