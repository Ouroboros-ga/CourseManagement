/** 教职工档案、任职关系、绑定码与本院基础数据选项的显式院级入口。 */
import { request } from './http'

const path = (cid: string, suffix = '') => `/api/v1/colleges/${encodeURIComponent(cid)}${suffix}`
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })
const query = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export interface StaffProfile {
  id: string
  school_id: string
  college_id: string
  staff_no: string
  name: string
  phone: string | null
  user_id: string | null
  status: 'ACTIVE' | 'INACTIVE'
  lock_version: number
  created_at: string
  updated_at: string
}
export interface StaffPage { items: StaffProfile[]; total: number; page: number; page_size: number }

export type StaffAnchor = 'LOCAL' | 'SHARED'
export interface TeachingAssignmentRow {
  id: string
  staff_id: string
  semester_id: string
  anchor_type: StaffAnchor
  teaching_class_id: string | null
  academic_offering_id: string | null
  effective_from: string
  effective_to: string | null
  lock_version: number
}
export type StaffDuty = 'HEAD_TEACHER' | 'COUNSELOR'
export interface ResponsibilityRow {
  id: string
  staff_id: string
  administrative_class_id: string
  duty: StaffDuty
  effective_from: string
  effective_to: string | null
  lock_version: number
}

export interface IssuedBindingToken { token_id: string; staff_id: string; plaintext_code: string; expires_at: string }

export interface ScopedAcademicRow { id: string; [field: string]: unknown }
export interface ScopedAcademicPage { items: ScopedAcademicRow[]; total: number; page: number; page_size: number }

export function listStaff(cid: string, params: { keyword?: string; status?: string; page?: number; page_size?: number } = {}) {
  return request<StaffPage>(path(cid, `/staff${query({ keyword: params.keyword, status: params.status, page: params.page, page_size: params.page_size })}`))
}
export function getStaff(cid: string, staffId: string) {
  return request<StaffProfile>(path(cid, `/staff/${encodeURIComponent(staffId)}`))
}
export function createStaff(cid: string, body: { staff_no: string; name: string; phone?: string | null; status?: 'ACTIVE' | 'INACTIVE'; reason?: string | null }) {
  return request<StaffProfile>(path(cid, '/staff'), json('POST', body))
}
export function updateStaff(cid: string, staffId: string, body: { lock_version: number; name?: string; phone?: string | null; status?: 'ACTIVE' | 'INACTIVE'; reason?: string | null }) {
  return request<StaffProfile>(path(cid, `/staff/${encodeURIComponent(staffId)}`), json('PATCH', body))
}
export function linkAccount(cid: string, staffId: string, body: { user_id: string; lock_version: number; reason?: string | null }) {
  return request<StaffProfile>(path(cid, `/staff/${encodeURIComponent(staffId)}/account`), json('PUT', body))
}
export function unlinkAccount(cid: string, staffId: string, lockVersion: number, reason?: string | null) {
  return request<StaffProfile>(path(cid, `/staff/${encodeURIComponent(staffId)}/account-unlink`), json('POST', { lock_version: lockVersion, reason: reason ?? null }))
}
export function issueBindingToken(cid: string, staffId: string, reason?: string | null) {
  return request<IssuedBindingToken>(path(cid, `/staff/${encodeURIComponent(staffId)}/binding-tokens`), json('POST', { reason: reason ?? null }))
}
export function revokeBindingToken(cid: string, tokenId: string, reason?: string | null) {
  return request<Record<string, unknown>>(path(cid, `/staff-binding-tokens/${encodeURIComponent(tokenId)}/revoke`), json('POST', { reason: reason ?? null }))
}

export function listTeachingAssignments(cid: string, params: { staff_id?: string; teaching_class_id?: string } = {}) {
  return request<TeachingAssignmentRow[]>(path(cid, `/teaching-staff-assignments${query({ staff_id: params.staff_id, teaching_class_id: params.teaching_class_id })}`))
}
export function createTeachingAssignment(cid: string, body: {
  staff_id: string; semester_id: string; anchor_type: StaffAnchor
  teaching_class_id?: string | null; academic_offering_id?: string | null
  effective_from: string; effective_to?: string | null; reason?: string | null
}) {
  return request<TeachingAssignmentRow>(path(cid, '/teaching-staff-assignments'), json('POST', {
    ...body,
    teaching_class_id: body.teaching_class_id ?? null,
    academic_offering_id: body.academic_offering_id ?? null
  }))
}
export function endTeachingAssignment(cid: string, relationId: string, body: { effective_to: string; lock_version: number; reason?: string | null }) {
  return request<TeachingAssignmentRow>(path(cid, `/teaching-staff-assignments/${encodeURIComponent(relationId)}/end`), json('POST', body))
}

export function listResponsibilities(cid: string, params: { staff_id?: string; administrative_class_id?: string; as_of?: string } = {}) {
  return request<ResponsibilityRow[]>(path(cid, `/class-staff-responsibilities${query({ staff_id: params.staff_id, administrative_class_id: params.administrative_class_id, as_of: params.as_of })}`))
}
export function createResponsibility(cid: string, body: {
  staff_id: string; administrative_class_id: string; duty: StaffDuty
  effective_from: string; effective_to?: string | null; reason?: string | null
}) {
  return request<ResponsibilityRow>(path(cid, '/class-staff-responsibilities'), json('POST', body))
}
export function endResponsibility(cid: string, relationId: string, body: { effective_to: string; lock_version: number; reason?: string | null }) {
  return request<ResponsibilityRow>(path(cid, `/class-staff-responsibilities/${encodeURIComponent(relationId)}/end`), json('POST', body))
}
export function responsibilityHandover(cid: string, relationId: string, body: { successor_staff_id: string; effective_on: string; lock_version: number; reason?: string | null }) {
  return request<Record<string, unknown>>(path(cid, `/class-staff-responsibilities/${encodeURIComponent(relationId)}/handover`), json('POST', body))
}

export function listScopedOptions(cid: string, kind: 'teaching-classes' | 'administrative-classes', params: { keyword?: string; semester_id?: string; page?: number; page_size?: number } = {}) {
  return request<ScopedAcademicPage>(path(cid, `/academic/${kind}${query({ keyword: params.keyword, semester_id: params.semester_id, page: params.page ?? 1, page_size: params.page_size ?? 100 })}`))
}
export function getScopedRow(cid: string, kind: 'teaching-classes' | 'administrative-classes', id: string) {
  return request<ScopedAcademicRow>(path(cid, `/academic/${kind}/${encodeURIComponent(id)}`))
}
