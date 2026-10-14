import { request } from './http'

export interface PublicationPreview {
  college_id: string; semester_id: string; semester_name: string
  source_revision: string; current_version: number; changed: boolean
  schedule_count: number; student_count: number
}
export interface PublicationResult { publication_id: string; version: number; changed: boolean }
const root = (cid: string, sid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/academic/semesters/${encodeURIComponent(sid)}`
export const previewAcademicPublication = (cid: string, sid: string) => request<PublicationPreview>(`${root(cid, sid)}/publication-preview`, { method: 'POST' })
export const publishAcademicTimetable = (cid: string, sid: string, revision: string) => request<PublicationResult>(`${root(cid, sid)}/publish`, { method: 'POST', body: JSON.stringify({ source_revision: revision }) })
