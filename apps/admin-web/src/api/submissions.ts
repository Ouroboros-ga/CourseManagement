import { request } from './http'

export interface AbnormalStudentItem {
  student_id: string
  student_no: string
  name: string
  attendance_type: 'LATE' | 'ABSENT' | 'LEAVE'
  note?: string | null
}

export interface ManagementSubmissionItem {
  id: string
  task_id: string
  attempt_no: number
  volunteer_user_id: string
  roster_version: number
  result: 'NORMAL' | 'ABNORMAL'
  review_status: 'PENDING' | 'APPROVED' | 'REJECTED'
  submitted_at: string
  deadline_version_id?: string | null
  late_at_submission: boolean
  note?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
  review_comment?: string | null
  abnormal_items: AbnormalStudentItem[]
  file_ids: string[]
  created_at: string
  updated_at: string
  task?: {
    id: string
    semester_id: string
    inspection_date: string
    class_name_snapshot?: string | null
    course_name_snapshot?: string | null
    classroom_snapshot?: string | null
  }
}

export interface ManagementSubmissionsQuery {
  semester_id?: string
  review_status?: 'PENDING' | 'APPROVED' | 'REJECTED'
  task_id?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export interface RosterStudentItem {
  student_id: string
  student_no: string
  name: string
  administrative_class_name?: string | null
}

export interface TaskRosterResult {
  task_id: string
  roster_version: number
  total_students: number
  students: RosterStudentItem[]
}

export async function listManagementSubmissions(query: ManagementSubmissionsQuery = {}): Promise<{
  items: ManagementSubmissionItem[]
  total: number
  page: number
  page_size: number
}> {
  const params = new URLSearchParams()
  if (query.semester_id) params.set('semester_id', query.semester_id)
  if (query.review_status) params.set('review_status', query.review_status)
  if (query.task_id) params.set('task_id', query.task_id)
  if (query.date_from) params.set('date_from', query.date_from)
  if (query.date_to) params.set('date_to', query.date_to)
  if (query.page) params.set('page', String(query.page))
  if (query.page_size) params.set('page_size', String(query.page_size))

  return request(`/api/v1/management/submissions?${params.toString()}`)
}

export async function getManagementSubmission(submissionId: string): Promise<ManagementSubmissionItem> {
  return request(`/api/v1/management/submissions/${submissionId}`)
}

export async function reviewSubmission(
  submissionId: string,
  payload: {
    decision: 'APPROVED' | 'REJECTED'
    comment?: string
  }
): Promise<{
  submission_id: string
  review_status: string
  reviewed_at: string
}> {
  return request(`/api/v1/submissions/${submissionId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function getTaskRoster(taskId: string, rosterVersion?: number): Promise<TaskRosterResult> {
  const params = new URLSearchParams()
  if (rosterVersion) params.set('roster_version', String(rosterVersion))
  return request(`/api/v1/inspection-tasks/${taskId}/students?${params.toString()}`)
}
