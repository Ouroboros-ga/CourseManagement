import { request } from './http'
import type { GroupMember } from './groupMembers'
import type { GroupConfiguration } from './campus'
export interface PermissionSource {
  kind: string; id?: string; owner_group_id?: string | null; actions: string[]
  scope: { kind: string; ids: string[] }; expires_at?: string | null
}
export interface OwnerCandidate { id: string; display_name: string; username: string | null }
export interface HandoverPreview {
  revision: string; old_owner_user_id: string; new_owner_user_id: string; new_owner_name: string
  new_owner_web_login_ready?: boolean
  grant_actions: string[]; revoke_dedicated_grant_ids: string[]; old_owner_retained_sources: PermissionSource[]
  retained_task_ids: string[]; existing_assignments_preserved: boolean
}
export interface PreparationBody {
  source_semester_id: string; member_ids: string[]; effective_from: string; effective_to: string
  teaching_class_mapping: Record<string, string>
}
export interface PreparationPreview {
  revision: string; can_confirm: boolean; configuration: GroupConfiguration
  items: { source_member_id: string; student_id: string; ready: boolean; reason?: string }[]
  source_config_id: string; identities_reused: boolean
}
export interface PreparationSource {
  configuration: GroupConfiguration; members: GroupMember[]
  teaching_classes: { id: string; name: string; semester_id: string }[]; uses_semester_specific_rules: boolean
}
const root = (cid: string, gid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/volunteer-groups/${encodeURIComponent(gid)}`
const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })
export const ownerCandidates = (cid: string, gid: string, keyword: string) => request<OwnerCandidate[]>(`${root(cid, gid)}/handover/candidates?${new URLSearchParams({ keyword })}`)
export const previewHandover = (cid: string, gid: string, owner_user_id: string, reason: string) => request<HandoverPreview>(`${root(cid, gid)}/handover/preview`, json({ owner_user_id, reason }))
export const confirmHandover = (cid: string, gid: string, owner_user_id: string, reason: string, revision: string) => request(`${root(cid, gid)}/handover/confirm`, json({ owner_user_id, reason, revision }))
export const myPermissionSources = (cid: string) => request<PermissionSource[]>(`/api/v1/colleges/${encodeURIComponent(cid)}/permission-sources/me`)
export const previewPreparation = (cid: string, gid: string, sid: string, body: PreparationBody) => request<PreparationPreview>(`${root(cid, gid)}/semesters/${encodeURIComponent(sid)}/preparation/preview`, json(body))
export const confirmPreparation = (cid: string, gid: string, sid: string, body: PreparationBody, revision: string) => request(`${root(cid, gid)}/semesters/${encodeURIComponent(sid)}/preparation/confirm`, json({ ...body, revision }))
export const preparationSource = (cid: string, gid: string, sid: string, sourceSid: string, includeTeachingClasses = true) => request<PreparationSource>(`${root(cid, gid)}/semesters/${encodeURIComponent(sid)}/preparation/source/${encodeURIComponent(sourceSid)}?include_teaching_classes=${includeTeachingClasses}`)

export function organizationOverview(cid: string, semesterId: string, asOf?: string) {
  const query = new URLSearchParams({ semester_id: semesterId })
  if (asOf) query.set('as_of', asOf)
  return request<{ items: Record<string, { configuration: GroupConfiguration | null; member_count: number; specific: boolean; error: string }> }>(`/api/v1/colleges/${encodeURIComponent(cid)}/volunteer-groups/semester-overview?${query}`)
}
