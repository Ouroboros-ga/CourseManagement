import { request } from './http'

export interface InspectionTaskItem {
  id: string
  task_key: string
  semester_id: string
  inspection_type: string
  inspection_date: string
  start_period: number
  end_period: number
  status: string
  deadline_assessment?: string | null
  deadline_at?: string | null
  course_name?: string | null
  course_code?: string | null
  classroom_name?: string | null
  teaching_class_name?: string | null
  teaching_class_id?: string | null
  course_name_snapshot?: string | null
  class_name_snapshot?: string | null
  classroom_snapshot?: string | null
  require_photo_snapshot?: boolean
  expected_count_snapshot?: number
  expected_count_current?: number
  roster_version?: number
  assigned_volunteer_id?: string | null
  assigned_volunteer_name?: string | null
  assignment?: {
    volunteer_user_id: string
    assign_method?: string
    volunteer_name?: string
    volunteer_student_no?: string
    volunteer_class_name?: string
    assigned_at?: string
  } | null
  lock_version?: number
  created_at?: string
}

export interface TaskListQuery {
  page?: number
  page_size?: number
  semester_id?: string
  week_no?: number
  inspection_date?: string
  status?: string
  teaching_class_id?: string
  administrative_class_id?: string | number
  include_canceled?: boolean
}

export interface PaginatedResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface CourseOccurrence {
  course_schedule_id: string
  inspection_date: string
  start_period: number
  end_period: number
  course_name: string
  course_code?: string
  teacher_name?: string
  teaching_class_id: string
  teaching_class_name?: string
  class_name?: string
  student_count?: number
  expected_count?: number
  classroom?: string
  classroom_name?: string
  existing_task_id?: string | null
  existing_task_status?: string | null
  selectable: boolean
  disabled_reason?: string | null
}

export interface OccurrencesQueryResult {
  items: CourseOccurrence[]
  page: number
  page_size: number
  total: number
  selection_revision: string
  selection_scope: {
    semester_id?: string
    date_from?: string
    date_to?: string
    teaching_class_ids?: number[]
  }
}

export async function listTasks(query: TaskListQuery): Promise<PaginatedResult<InspectionTaskItem>> {
  const params = new URLSearchParams()
  if (query.page) params.set('page', String(query.page))
  if (query.page_size) params.set('page_size', String(query.page_size))
  if (query.semester_id) params.set('semester_id', query.semester_id)
  if (query.week_no) params.set('week_no', String(query.week_no))
  if (query.inspection_date) params.set('inspection_date', query.inspection_date)
  if (query.status) params.set('status', query.status)
  if (query.teaching_class_id) params.set('teaching_class_id', query.teaching_class_id)
  if (query.administrative_class_id) params.set('administrative_class_id', String(query.administrative_class_id))
  if (query.include_canceled !== undefined) params.set('include_canceled', String(query.include_canceled))

  return request<PaginatedResult<InspectionTaskItem>>(`/api/v1/inspection-tasks?${params.toString()}`)
}

export async function getTask(id: string): Promise<InspectionTaskItem> {
  return request<InspectionTaskItem>(`/api/v1/inspection-tasks/${id}`)
}

export async function queryCourseOccurrences(params: {
  semester_id: string
  date_from: string
  date_to: string
  teaching_class_ids?: number[]
  administrative_class_id?: string | number
  page?: number
  page_size?: number
}): Promise<OccurrencesQueryResult> {
  const searchParams = new URLSearchParams({
    semester_id: params.semester_id,
    date_from: params.date_from,
    date_to: params.date_to,
    page: String(params.page || 1),
    page_size: String(params.page_size || 500)
  })
  if (params.administrative_class_id) {
    searchParams.set('administrative_class_id', String(params.administrative_class_id))
  }
  if (params.teaching_class_ids?.length) {
    params.teaching_class_ids.forEach(id => searchParams.append('teaching_class_ids', String(id)))
  }
  return request<OccurrencesQueryResult>(`/api/v1/inspection-course-occurrences?${searchParams.toString()}`)
}

export async function generateExactTasks(body: {
  semester_id: string
  inspection_type: string
  selection_revision: string
  selection_scope: Record<string, unknown>
  occurrences: Array<{ course_schedule_id: string; inspection_date: string }>
}): Promise<{
  created: number
  existed: number
  tasks: Array<{ task_id: string; status: string }>
  assignable_task_ids: string[]
}> {
  return request('/api/v1/inspection-tasks/generate', {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

export interface AutoAssignResult {
  semester_id: string
  target_task_count: number
  assigned_count: number
  unassigned_count: number
  assigned: Array<{ task_id: string; volunteer_user_id: string }>
  unassigned: Array<{ task_id: string; reason_code: string; message: string }>
}

export async function triggerAutoAssign(body: {
  semester_id: string | number
  task_ids?: (string | number)[]
  inspection_date?: string
  date_from?: string
  date_to?: string
  candidate_user_ids?: (string | number)[]
  reason?: string
}): Promise<AutoAssignResult> {
  const payload: Record<string, unknown> = {
    semester_id: Number(body.semester_id)
  }
  if (body.task_ids && body.task_ids.length > 0) {
    payload.task_ids = body.task_ids.map(Number)
  }
  if (body.inspection_date) payload.inspection_date = body.inspection_date
  if (body.date_from) payload.date_from = body.date_from
  if (body.date_to) payload.date_to = body.date_to
  if (body.candidate_user_ids && body.candidate_user_ids.length > 0) {
    payload.candidate_user_ids = body.candidate_user_ids.map(Number)
  }
  if (body.reason) payload.reason = body.reason

  return request<AutoAssignResult>('/api/v1/assignments/auto', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function updateTask(
  id: string,
  body: {
    classroom?: string
    start_period?: number
    end_period?: number
    course_name?: string
    reason?: string
  }
): Promise<InspectionTaskItem> {
  return request<InspectionTaskItem>(`/api/v1/inspection-tasks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body)
  })
}

export interface SmartSampleResult {
  semester_id: number
  week_no: number
  total_candidates: number
  sampled_count: number
  occurrences: Array<{ course_schedule_id: number; inspection_date: string }>
  items: Array<{
    course_schedule_id: string
    inspection_date: string
    start_period: number
    end_period: number
    teaching_class_id: string
    class_name: string | null
    course_name: string | null
    classroom: string | null
    expected_count: number
  }>
}

export async function smartSampleOccurrences(body: {
  semester_id: number
  week_no: number
  morning_only?: boolean
  max_tasks_per_class?: number
  sample_ratio?: number
  exclude_already_generated?: boolean
  random_seed?: number
}): Promise<SmartSampleResult> {
  return request<SmartSampleResult>('/api/v1/inspection-course-occurrences/smart-sample', {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

export async function deleteTask(
  taskId: string | number,
  reason?: string,
  force = false
): Promise<{ deleted: boolean; task_id: string }> {
  const params = new URLSearchParams()
  if (reason) params.set('reason', reason)
  if (force) params.set('force', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  return request<{ deleted: boolean; task_id: string }>(`/api/v1/inspection-tasks/${taskId}${qs}`, {
    method: 'DELETE'
  })
}

export async function batchDeleteTasks(body: {
  task_ids: (number | string)[]
  reason?: string
  force?: boolean
}): Promise<{ deleted_count: number; deleted_ids: string[] }> {
  return request<{ deleted_count: number; deleted_ids: string[] }>('/api/v1/inspection-tasks/batch-delete', {
    method: 'POST',
    body: JSON.stringify({
      task_ids: body.task_ids.map(Number),
      reason: body.reason,
      force: body.force || false
    })
  })
}

export interface SemesterVolunteerItem {
  user_id: string
  student_id: string
  student_no: string
  name: string
  class_name: string | null
  has_wechat: boolean
}

export async function listSemesterVolunteers(
  semesterId: string | number,
  keyword?: string
): Promise<SemesterVolunteerItem[]> {
  const params = new URLSearchParams()
  params.set('semester_id', String(semesterId))
  if (keyword) params.set('keyword', keyword)
  return request<SemesterVolunteerItem[]>(`/api/v1/inspection/volunteers?${params.toString()}`)
}

export async function assignTask(
  taskId: string | number,
  body: { volunteer_user_id?: string | number; student_id?: string | number; lock_version: number; reason?: string }
): Promise<InspectionTaskItem> {
  return request<InspectionTaskItem>(`/api/v1/inspection-tasks/${taskId}/assignment`, {
    method: 'PUT',
    body: JSON.stringify(body)
  })
}


