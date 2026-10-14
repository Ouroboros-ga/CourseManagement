import { request } from './http'

export type ScopedAcademicKind = 'administrative-classes' | 'students' | 'teaching-classes' | 'schedules' | 'courses' | 'semesters' | 'qualifications'
export interface ScopedAcademicRow { id: string; ownership_version?: number; [field: string]: unknown }
export interface ScopedAcademicPage { items: ScopedAcademicRow[]; total: number; page: number; page_size: number }
export interface ScopedClassBody { class_code?: string; class_name: string; grade_year?: number | null; reason?: string; ownership_version?: number }
const root = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/academic`
export function listScopedAcademic(cid: string, kind: ScopedAcademicKind, page: number, keyword: string) {
  const query = new URLSearchParams({ page: String(page), page_size: '20', keyword })
  return request<ScopedAcademicPage>(`${root(cid)}/${kind}?${query}`)
}
export const createScopedClass = (cid: string, body: ScopedClassBody) => request<ScopedAcademicRow>(`${root(cid)}/administrative-classes`, { method: 'POST', body: JSON.stringify(body) })
export const updateScopedClass = (cid: string, row: ScopedAcademicRow, body: ScopedClassBody) => request<ScopedAcademicRow>(`${root(cid)}/administrative-classes/${encodeURIComponent(row.id)}`, { method: 'PATCH', body: JSON.stringify({ ...body, ownership_version: row.ownership_version }) })
