import { request } from './workspaceHttp'

export type AttendanceType = 'NORMAL' | 'LEAVE' | 'LATE' | 'ABSENT'
export type AttendanceSourceType = 'SUBMISSION' | 'CORRECTION' | 'OBJECTION_FINAL'

export interface AttendanceTaskBrief {
  time_basis?: string
  time_label?: string | null
  task_id: string
  responsible_college_id?: string | null
  responsible_college_name?: string | null
  semester_status?: 'ACTIVE' | 'ARCHIVED' | null
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
  photo_file_ids?: string[]
  has_objection?: boolean
  objection_id?: string | null
  objection_status?: string | null
  objection_summary?: AttendanceObjectionBrief | null
  period?: string | null
  classroom?: string | null
  administrative_class_id?: string | null
  administrative_class_name?: string | null
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
  task_id?: string | number
  semester_id?: string | number
  effective_type?: AttendanceType
  page?: number
  page_size?: number
  start_date?: string
  end_date?: string
  keyword?: string
  course_type_id?: string
  administrative_class_id?: string
  unknown_class?: boolean
  abnormal_only?: boolean
}

export interface AttendanceCounts {
  record_count: number; task_count: number; normal_count: number
  late_count: number; absent_count: number; leave_count: number
}
export interface AttendanceGroup extends AttendanceCounts {
  time_basis?: string
  time_label?: string | null
  task_id?: string; course_name?: string | null; teaching_class_name?: string | null
  inspection_date?: string; start_period?: number; end_period?: number; classroom?: string | null
  volunteer_name?: string | null; administrative_class_id?: string | null; class_name?: string | null
}
export type AttendanceGroupBy = 'task' | 'administrative_class'
export const attendanceLabels: Record<AttendanceType, string> = { NORMAL: '正常', LEAVE: '请假', LATE: '迟到', ABSENT: '旷课' }
export function attendanceQuery(params: ListAttendanceParams): string {
  const query = new URLSearchParams()
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(name, String(value))
  }
  return query.toString()
}
export function listAttendanceGroups(groupBy: AttendanceGroupBy, params: ListAttendanceParams) {
  return request<{ items: AttendanceGroup[]; total: number; page: number; page_size: number; summary: AttendanceCounts }>(
    `/api/v1/attendance/groups?${attendanceQuery(params)}&group_by=${groupBy}`)
}

export async function listAttendance(params: ListAttendanceParams = {}): Promise<{
  items: AttendanceRecord[]
  page: number
  page_size: number
  total: number
}> {
  const qs = attendanceQuery(params)
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

export function correctArchivedAttendance(collegeId: string, recordId: string, body: { attendance_type: AttendanceType; reason: string; current_version: number }) {
  return request<AttendanceRecord>(`/api/v1/colleges/${encodeURIComponent(collegeId)}/attendance/${encodeURIComponent(recordId)}/archived-corrections`, { method: 'POST', body: JSON.stringify(body) })
}
