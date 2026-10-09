import { request } from './http'

export type AttendanceType = 'NORMAL' | 'LEAVE' | 'LATE' | 'ABSENT'
export type AttendanceSourceType = 'SUBMISSION' | 'CORRECTION' | 'OBJECTION_FINAL'

export interface AttendanceTaskBrief {
  task_id: string
  inspection_date: string
  inspection_type: string
  course_name_snapshot?: string | null
  class_name_snapshot?: string | null
  classroom_snapshot?: string | null
  start_period?: number | null
  end_period?: number | null
  period_text?: string | null
  week_no?: number | null
}

export interface AttendanceObjectionBrief {
  id: string
  status: string
  initial_status: string
  final_status: string
  desired_type: AttendanceType
  reason?: string | null
  created_at?: string | null
}

export interface AttendanceRecord {
  id: string
  task_id: string
  student_id: string
  student_no?: string | null
  name?: string | null
  effective_type: AttendanceType
  current_version: number
  source_submission_item_id?: string | null
  task?: AttendanceTaskBrief | null
  created_at: string
  has_objection?: boolean
  objection_id?: string | null
  objection_status?: string | null
  objection_summary?: AttendanceObjectionBrief | null
  period?: string | null
  classroom?: string | null
}

export interface AttendanceVersionItem {
  id: string
  attendance_record_id: string
  version_no: number
  attendance_type: AttendanceType
  source_type: AttendanceSourceType
  source_id?: string | null
  changed_by?: string | null
  reason?: string | null
  created_at: string
}

export interface ListAttendanceParams {
  task_id?: number
  semester_id?: number
  effective_type?: AttendanceType
  page?: number
  page_size?: number
}

export async function listAttendance(params: ListAttendanceParams = {}): Promise<{
  items: AttendanceRecord[]
  page: number
  page_size: number
  total: number
}> {
  const query = new URLSearchParams()
  if (params.task_id) query.set('task_id', String(params.task_id))
  if (params.semester_id) query.set('semester_id', String(params.semester_id))
  if (params.effective_type) query.set('effective_type', params.effective_type)
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))

  const qs = query.toString()
  return request<{ items: AttendanceRecord[]; page: number; page_size: number; total: number }>(
    `/api/v1/attendance${qs ? `?${qs}` : ''}`
  )
}

export async function getAttendanceRecord(recordId: string | number): Promise<AttendanceRecord> {
  return request<AttendanceRecord>(`/api/v1/attendance/${recordId}`)
}

export async function listAttendanceVersions(recordId: string | number): Promise<AttendanceVersionItem[]> {
  return request<AttendanceVersionItem[]>(`/api/v1/attendance/${recordId}/versions`)
}

export async function correctAttendanceRecord(
  recordId: string | number,
  body: {
    attendance_type: AttendanceType
    reason?: string
    current_version: number
  }
): Promise<AttendanceRecord> {
  return request<AttendanceRecord>(`/api/v1/attendance/${recordId}/corrections`, {
    method: 'POST',
    body: JSON.stringify(body)
  })
}
