import { request } from './http'
export interface ArchivePreview {
  revision: string; can_archive: boolean; status: string; semester_id: string
  blockers: Record<string, string[]>; published_report_version_ids: string[]
}
export interface CampusDimension {
  responsible_college_name: string | null; student_college_name: string | null
  checked_task_count: number; check_person_times: number; distinct_student_count: number
  distinct_student_occurrence_count: number; result_distribution: Record<string, number>
}
export interface CampusDimensions {
  task_count: number; checked_task_count: number; check_person_times: number; distinct_student_count: number
  distinct_student_occurrence_count: number; deduplication_note: string; dimensions: CampusDimension[]
}
const archiveRoot = (sid: string) => `/api/v1/school/academic/semesters/${encodeURIComponent(sid)}/archive`
export const previewArchive = (sid: string, reason: string) => request<ArchivePreview>(`${archiveRoot(sid)}/preview`, { method: 'POST', body: JSON.stringify({ reason }) })
export const confirmArchive = (sid: string, reason: string, revision: string) => request(`${archiveRoot(sid)}/confirm`, { method: 'POST', body: JSON.stringify({ reason, revision }) })
export const campusDimensions = (sid: string, cid?: string) => request<CampusDimensions>(cid ? `/api/v1/colleges/${encodeURIComponent(cid)}/statistics/semesters/${encodeURIComponent(sid)}/campus-dimensions` : `/api/v1/school/statistics/semesters/${encodeURIComponent(sid)}/campus-dimensions`)
