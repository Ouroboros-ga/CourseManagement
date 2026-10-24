import { request } from './http'

export type MemberStatus = 'ACTIVE' | 'INACTIVE'
export type MemberKind = 'members'
export type GroupMemberKind = MemberKind

export interface GroupMember {
  id: string
  student_id: string
  semester_id: string
  effective_from: string
  effective_to: string
  status: MemberStatus
  lock_version: number
  student_no?: string
  name?: string
}

export interface MemberCandidate {
  id: string
  student_no: string
  name: string
}

export interface MemberImpact {
  lock_version: number
  retained_future_task_ids: string[]
  existing_assignments_preserved: true
}

export interface MemberCreatePayload {
  student_id: string
  semester_id: string
  effective_from: string
  effective_to: string
  enable_qualification?: boolean
}

export interface MemberUpdatePayload {
  lock_version: number
  effective_from: string
  effective_to: string
  status: MemberStatus
  confirm_future_assignments: boolean
}

export interface MemberRevokePayload {
  lock_version: number
  confirm_future_assignments: boolean
}

export interface GroupMemberApi {
  list(kind: MemberKind, collegeId: string, groupId: string, semesterId: string): Promise<GroupMember[]>
  candidates(collegeId: string, groupId: string, semesterId: string, from: string, to: string, keyword: string): Promise<MemberCandidate[]>
  create(kind: MemberKind, collegeId: string, groupId: string, payload: MemberCreatePayload): Promise<GroupMember>
  impact(kind: MemberKind, collegeId: string, groupId: string, id: string): Promise<MemberImpact>
  update(kind: MemberKind, collegeId: string, groupId: string, id: string, payload: MemberUpdatePayload): Promise<GroupMember>
  revoke(kind: MemberKind, collegeId: string, groupId: string, id: string, payload: MemberRevokePayload): Promise<GroupMember>
}

const base = (collegeId: string, groupId: string) =>
  `/api/v1/colleges/${encodeURIComponent(collegeId)}/groups/${encodeURIComponent(groupId)}`
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

export const groupMemberApi: GroupMemberApi = {
  list: (kind, collegeId, groupId, semesterId) => request<GroupMember[]>(
    `${base(collegeId, groupId)}/${kind}?semester_id=${encodeURIComponent(semesterId)}`
  ),
  candidates: (collegeId, groupId, semesterId, from, to, keyword) => {
    const query = new URLSearchParams({ semester_id: semesterId, effective_from: from, effective_to: to, keyword })
    return request<MemberCandidate[]>(`${base(collegeId, groupId)}/member-candidates?${query}`)
  },
  create: (kind, collegeId, groupId, payload) => request<GroupMember>(
    `${base(collegeId, groupId)}/${kind}`, json('POST', payload)
  ),
  impact: (kind, collegeId, groupId, id) => request<MemberImpact>(
    `${base(collegeId, groupId)}/${kind}/${encodeURIComponent(id)}/impact`
  ),
  update: (kind, collegeId, groupId, id, payload) => request<GroupMember>(
    `${base(collegeId, groupId)}/${kind}/${encodeURIComponent(id)}`, json('PATCH', payload)
  ),
  revoke: (kind, collegeId, groupId, id, payload) => request<GroupMember>(
    `${base(collegeId, groupId)}/${kind}/${encodeURIComponent(id)}/revoke`, json('POST', payload)
  )
}

export interface MemberImportPreview {
  revision: string; count: number; can_commit: boolean; qualifications_to_enable: number; unchanged: number
  issues: { student_no: string; message: string }[]
  items: { student_id?: string; student_no: string; name: string; status: 'ADD' | 'UNCHANGED' | 'BLOCKED'; message?: string; source_row?: number; qualification_action?: 'ENABLE' | 'KEEP' }[]
}
export interface MemberImportResult { created: number; unchanged: number; qualifications_enabled: number }
export interface MemberImportForm { semester_id: string; effective_from: string; effective_to: string; enable_qualification: boolean }
function fileBody(file: File, body: MemberImportForm, revision?: string) {
  const data = new FormData()
  data.set('file', file)
  for (const [key, value] of Object.entries(body)) data.set(key, String(value))
  if (revision) data.set('revision', revision)
  return data
}
export const memberImportApi = {
  template: (cid: string, gid: string) => request<Blob>(`${base(cid, gid)}/members/import-template`, {}, false, 'blob'),
  preview: (cid: string, gid: string, file: File, body: MemberImportForm) => request<MemberImportPreview>(`${base(cid, gid)}/members/import/preview`, { method: 'POST', body: fileBody(file, body) }),
  commit: (cid: string, gid: string, file: File, body: MemberImportForm, revision: string) => request<MemberImportResult>(`${base(cid, gid)}/members/import/commit`, { method: 'POST', body: fileBody(file, body, revision) })
}
