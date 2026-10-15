import { request } from './http'
import type { CollegeTimeConfiguration, CollegeTimePreview } from './collegeTime'

export interface SchoolTimeTemplate {
  id: string; name: string; version: number; configuration: CollegeTimeConfiguration
}
export interface TemplateAdoptionPreview extends CollegeTimePreview {
  configuration: CollegeTimeConfiguration; retained_college_exceptions: string[]; template_id: string
}
export interface TemplateSelection { template_id: string; effective_from: string; confirm_existing_tasks: boolean }
const root = (cid: string, sid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/academic/semesters/${encodeURIComponent(sid)}/school-time-templates`
export const listSchoolDefaults = (cid: string, sid: string) => request<SchoolTimeTemplate[]>(root(cid, sid))
export const publishSchoolDefaults = (sid: string, name: string, configuration: CollegeTimeConfiguration, period_template_version_id?: string) => request<SchoolTimeTemplate>(`/api/v1/school/academic/semesters/${encodeURIComponent(sid)}/time-templates`, { method: 'POST', body: JSON.stringify({ ...configuration, name, period_template_version_id }) })
export const previewSchoolDefaults = (cid: string, sid: string, selection: TemplateSelection) => request<TemplateAdoptionPreview>(`${root(cid, sid)}/preview`, { method: 'POST', body: JSON.stringify(selection) })
export const adoptSchoolDefaults = (cid: string, sid: string, selection: TemplateSelection, revision: string) => request(`${root(cid, sid)}/adopt`, { method: 'POST', body: JSON.stringify({ ...selection, revision }) })
