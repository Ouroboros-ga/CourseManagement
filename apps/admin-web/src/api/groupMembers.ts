import { request } from './http'

export type MemberStatus = 'ACTIVE' | 'INACTIVE'
export type MemberKind = 'members' | 'support-authorizations'
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
  candidates(collegeId: string, groupId: string, semesterId: string, from: string, to: string, keyword: string, school: boolean): Promise<MemberCandidate[]>
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
  candidates: (collegeId, groupId, semesterId, from, to, keyword, school) => {
    const query = new URLSearchParams({ semester_id: semesterId, effective_from: from, effective_to: to, keyword })
    if (school) query.set('school', 'true')
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
