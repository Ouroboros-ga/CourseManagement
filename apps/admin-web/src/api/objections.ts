import { request } from './http'
import type { AttendanceType } from './attendance'

export type ObjectionType = AttendanceType
export type ObjectionInitialStatus = 'PENDING' | 'PASSED' | 'REJECTED'
export type ObjectionFinalStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface ObjectionItem {
  id: string
  attendance_record_id: string
  student_id: string
  base_attendance_version: number
  reason: string
  desired_type: ObjectionType
  initial_status: ObjectionInitialStatus
  initial_reviewed_by?: string | null
  initial_reviewed_at?: string | null
  initial_comment?: string | null
  final_status: ObjectionFinalStatus
  final_reviewed_by?: string | null
  final_reviewed_at?: string | null
  final_comment?: string | null
  final_attendance_type?: ObjectionType | null
  file_ids: string[]
  created_at: string
  updated_at: string
}

export interface ListObjectionsParams {
  attendance_record_id?: number
  final_status?: ObjectionFinalStatus
  initial_status?: ObjectionInitialStatus
  page?: number
  page_size?: number
}

export interface ListObjectionsResult {
  items: ObjectionItem[]
  page: number
  page_size: number
  total: number
}

export interface FileAccessInfo {
  url: string
  method: string
  expires_in: number
  expires_at: string
}

export async function listObjections(params: ListObjectionsParams = {}): Promise<ListObjectionsResult> {
  const query = new URLSearchParams()
  if (params.attendance_record_id) query.set('attendance_record_id', String(params.attendance_record_id))
  if (params.final_status) query.set('final_status', params.final_status)
  if (params.initial_status) query.set('initial_status', params.initial_status)
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))

  const qs = query.toString()
  return request<ListObjectionsResult>(`/api/v1/objections${qs ? `?${qs}` : ''}`)
}

export async function getObjection(objectionId: string | number): Promise<ObjectionItem> {
  return request<ObjectionItem>(`/api/v1/objections/${objectionId}`)
}

export async function initialReviewObjection(
  objectionId: string | number,
  body: {
    decision: 'PASSED' | 'REJECTED'
    comment?: string
  }
): Promise<ObjectionItem> {
  return request<ObjectionItem>(`/api/v1/objections/${objectionId}/initial-review`, {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

export async function finalReviewObjection(
  objectionId: string | number,
  body: {
    decision: 'APPROVED' | 'REJECTED'
    final_type?: ObjectionType
    comment?: string
    current_version: number
  }
): Promise<ObjectionItem> {
  return request<ObjectionItem>(`/api/v1/objections/${objectionId}/final-review`, {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

export async function getFileAccess(fileId: string | number): Promise<FileAccessInfo> {
  return request<FileAccessInfo>(`/api/v1/files/${fileId}/access`)
}
