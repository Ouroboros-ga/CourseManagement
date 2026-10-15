import { request } from './http'
import type { CollegeTimeConfiguration, CollegeTimePreview } from './collegeTime'
export interface TimeProfile { id: string; name: string; status: 'DRAFT' | 'ACTIVE' | 'ARCHIVED'; lock_version: number; draft_configuration: CollegeTimeConfiguration; source_template_version_id?: string | null }
const root = (cid: string, sid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/academic/semesters/${encodeURIComponent(sid)}/time-versions/profiles`
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })
export const listTimeProfiles = (cid: string, sid: string) => request<TimeProfile[]>(root(cid, sid))
export const saveTimeProfile = (cid: string, sid: string, name: string, configuration: CollegeTimeConfiguration, row: TimeProfile | null) => request<TimeProfile>(root(cid, sid) + (row ? `/${row.id}` : ''), json(row ? 'PATCH' : 'POST', { name, configuration, ...(row ? { lock_version: row.lock_version } : {}) }))
export const previewTimeProfile = (cid: string, sid: string, pid: string) => request<CollegeTimePreview>(root(cid, sid) + `/${pid}/preview`)
export const publishTimeProfile = (cid: string, sid: string, row: TimeProfile, revision: string) => request(root(cid, sid) + `/${row.id}/publish`, json('POST', { lock_version: row.lock_version, revision, confirm_existing_tasks: true }))
export const archiveTimeProfile = (cid: string, sid: string, row: TimeProfile) => request(root(cid, sid) + `/${row.id}/archive`, json('POST', { lock_version: row.lock_version }))
export const previewTimeBinding = (cid: string, sid: string, tid: string, profile_id: string | null) => request<CollegeTimePreview>(root(cid, sid) + `/teaching-classes/${tid}/binding/preview`, json('POST', { profile_id }))
export const bindTimeProfile = (cid: string, sid: string, tid: string, profile_id: string | null, revision: string) => request(root(cid, sid) + `/teaching-classes/${tid}/binding`, json('POST', { profile_id, revision }))
