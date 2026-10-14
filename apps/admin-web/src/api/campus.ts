import { request } from './http'

export interface College {
  id: string; school_id: string; code: string; name: string
  status: 'ACTIVE' | 'INACTIVE'; lock_version: number
  authorization_revision: number; configuration_revision: number
  capabilities: string[]; business_ready: boolean
}
export interface School { id: string; code: string; name: string }
export interface CourseType {
  id: string; college_id: string; code: string; name: string; description: string
  display_color: string; sort_order: number; status: 'ACTIVE' | 'INACTIVE'; lock_version: number
}
export type Effect = 'BLOCK' | 'WARN' | 'ALLOW'
export interface GroupConfiguration {
  course_type_ids: string[]; default_effect: Effect; type_overrides: Record<string, Effect>
  own_class_effect: Effect; task_conflict_effect: 'BLOCK'; daily_limit: number
  weekly_limit: number; count_scope: 'GROUP' | 'ALL_GROUPS'; buffer_minutes: number
}
export interface VolunteerGroup {
  id: string; college_id: string; name: string; owner_user_id: string
  status: 'DRAFT' | 'ACTIVE' | 'INACTIVE'; lock_version: number; config_version: number
  starts_on: string | null; ends_on: string | null; configuration: GroupConfiguration | null
}
export interface ScopedGrant {
  id: string; college_id: string; user_id: string; actions: string[]
  starts_at: string | null; expires_at: string | null; status: 'ACTIVE' | 'REVOKED'; lock_version: number
}
export const campusActionLabels: Record<string, string> = {
  'academic.read': '查看本院教学数据', 'academic.manage': '维护本院教学数据',
  'student.read': '查看本院学生与名单', 'student.manage': '维护本院学生与名单',
  'volunteer.read': '查看本院志愿者资格',
  'academic.course_type.read': '查看课程类型', 'academic.course_type.manage': '维护课程类型',
  'volunteer.group.read': '查看志愿者组', 'volunteer.group.manage': '维护组基本信息',
  'volunteer.member.manage': '维护组成员（接入中）', 'volunteer.config.publish': '发布组范围与规则'
}
const path = (cid: string, suffix = '') => `/api/v1/colleges/${encodeURIComponent(cid)}${suffix}`
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })
export const listWorkspaces = () => request<College[]>('/api/v1/me/workspaces')
export const listScopedData = (cid: string, kind: string, params: { query?: string; page_size?: number }) => request<{ items: Record<string, unknown>[]; total: number }>(path(cid, `/academic/${kind}?${new URLSearchParams({ keyword: params.query || '', page_size: String(params.page_size || 100) })}`))
export const getCollegeCapabilities = (cid: string) => request<College>(path(cid, '/capabilities'))
export const listSchools = () => request<School[]>('/api/v1/schools')
export const createSchool = (name: string, code: string) => request<School>('/api/v1/schools', json('POST', { name, code }))
export const createCollege = (sid: string, name: string, code: string) => request<College>(`/api/v1/schools/${sid}/colleges`, json('POST', { name, code }))
export const updateCollege = (cid: string, body: { name?: string; status?: string; lock_version: number }) => request<College>(path(cid), json('PATCH', body))
export const listCourseTypes = (cid: string) => request<CourseType[]>(path(cid, '/course-types'))
export const createCourseType = (cid: string, body: Pick<CourseType, 'name' | 'description' | 'display_color' | 'sort_order'>) => request<CourseType>(path(cid, '/course-types'), json('POST', body))
export const updateCourseType = (cid: string, row: CourseType, body: Partial<CourseType>) => request<CourseType>(path(cid, `/course-types/${row.id}`), json('PATCH', { ...body, lock_version: row.lock_version }))
export const deleteCourseType = (cid: string, row: CourseType) => request<void>(path(cid, `/course-types/${row.id}`), json('DELETE', { lock_version: row.lock_version }))
export const listGroups = (cid: string) => request<VolunteerGroup[]>(path(cid, '/volunteer-groups'))
export const createGroup = (cid: string, body: { name: string; owner_user_id: string; starts_on?: string | null; ends_on?: string | null }) => request<VolunteerGroup>(path(cid, '/volunteer-groups'), json('POST', body))
export const updateGroup = (cid: string, row: VolunteerGroup, body: { name?: string; status?: 'ACTIVE' | 'INACTIVE'; owner_user_id?: string; starts_on?: string | null; ends_on?: string | null }) => request<VolunteerGroup>(path(cid, `/groups/${row.id}`), json('PATCH', { ...body, lock_version: row.lock_version }))
export const deleteGroup = (cid: string, row: VolunteerGroup) => request<void>(path(cid, `/groups/${row.id}`), json('DELETE', { lock_version: row.lock_version }))
export const publishGroup = (cid: string, row: VolunteerGroup, configuration: GroupConfiguration) => request<VolunteerGroup>(path(cid, `/groups/${row.id}/configuration/publish`), json('POST', { ...configuration, lock_version: row.lock_version }))
export const listGrants = (cid: string) => request<ScopedGrant[]>(path(cid, '/grants'))
export const createGrant = (cid: string, user_id: string, actions: string[], expires_at: string | null) => request<ScopedGrant>(path(cid, '/grants'), json('POST', { user_id, actions, expires_at }))
export const revokeGrant = (cid: string, row: ScopedGrant) => request<ScopedGrant>(path(cid, `/grants/${row.id}/revoke`), json('POST', { lock_version: row.lock_version }))

export type OwnershipKind = 'administrative_class' | 'teaching_class' | 'import_batch' | 'report'
export type OwnershipMappings = Partial<Record<OwnershipKind, Record<string, string>>>
export interface OwnershipItem { id: string; label: string; legacy_college_text: string | null }
export interface OwnershipPreview {
  revision: string
  changes: { kind: string; id: string; college_id: string; ownership_version: number }[]
  conflicts: { kind: string; id: string; reason: string }[]
  unresolved: Record<string, number>
  business_ready: false
}
export const listUnresolvedOwnership = (kind: OwnershipKind, after = '0') => request<{ items: OwnershipItem[]; next_after_id: string | null }>(`/api/v1/campus/ownership/unresolved/${kind}?after_id=${encodeURIComponent(after)}`)
export const previewOwnership = (mappings: OwnershipMappings) => request<OwnershipPreview>('/api/v1/campus/ownership/preview', json('POST', { mappings }))
export const applyOwnership = (mappings: OwnershipMappings, revision: string) => request<{ updated: number; unresolved: Record<string, number>; business_ready: false }>('/api/v1/campus/ownership/apply', json('POST', { mappings, revision }))
