import { request } from './http'
import type { CollegePeriodTime } from './collegeTime'
import type { TimeProfile } from './timeProfiles'

export interface TemplateVersion {
  id: string; template_id: string; version: number; name: string; periods: CollegePeriodTime[]
}
export interface SchoolTimeTemplate {
  id: string; school_id: string; name: string; status: 'ACTIVE' | 'INACTIVE'
  latest_version: number; lock_version: number; latest: TemplateVersion
}
export interface TemplateUpdate {
  profile_id: string; profile_name: string; template_id: string; template_name: string
  source_version: number; latest_version: number; template_status: 'ACTIVE' | 'INACTIVE'
  update_available: boolean; message: string
}
const schoolRoot = (sid: string) => `/api/v1/schools/${encodeURIComponent(sid)}/time-templates`
const collegeRoot = (cid: string, sid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/academic/semesters/${encodeURIComponent(sid)}`
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })
export const listSchoolTimeTemplates = (sid: string) => request<SchoolTimeTemplate[]>(schoolRoot(sid))
export const listTemplateVersions = (sid: string, tid: string) => request<TemplateVersion[]>(`${schoolRoot(sid)}/${tid}/versions`)
export const saveSchoolTimeTemplate = (sid: string, name: string, periods: CollegePeriodTime[], row: SchoolTimeTemplate | null) => request(`${schoolRoot(sid)}${row ? `/${row.id}` : ''}`, json(row ? 'PATCH' : 'POST', { name, periods, ...(row ? { lock_version: row.lock_version } : {}) }))
export const setSchoolTemplateStatus = (sid: string, row: SchoolTimeTemplate) => request(`${schoolRoot(sid)}/${row.id}/status`, json('POST', { lock_version: row.lock_version, status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' }))
export const listCollegeTemplates = (cid: string) => request<SchoolTimeTemplate[]>(`/api/v1/colleges/${encodeURIComponent(cid)}/time-templates`)
export const listTemplateUpdates = (cid: string, sid: string) => request<TemplateUpdate[]>(`${collegeRoot(cid, sid)}/time-template-updates`)
export const importTemplateDraft = (cid: string, sid: string, template_version_id: string, name: string, effective_from: string) => request<TimeProfile>(`${collegeRoot(cid, sid)}/time-versions/profiles/from-template`, json('POST', { template_version_id, name, effective_from }))
