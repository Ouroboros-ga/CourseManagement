import { request } from './http'

export interface AdministrativeClassOption {
  id: string
  class_name: string
  class_code: string
  status: string
}

export interface AdministrativeClassPage {
  items: AdministrativeClassOption[]
  total: number
  page: number
  page_size: number
}

export interface GroupSampleBody {
  semester_id: string
  date_from: string
  date_to: string
  counts: Record<string, number>
  draw_id: string
  require_photo: boolean
}

export interface GroupSampleItem {
  task_key: string
  inspection_date: string
  week_no: number
  start_period: number
  end_period: number
  class_name_snapshot: string
  course_name_snapshot: string
  classroom_snapshot: string | null
  expected_count: number
}

export interface GroupSamplePreview {
  selection_revision: string
  candidate_count: number
  selected_count: number
  counts: Record<string, number>
  items: GroupSampleItem[]
}

export interface GroupSampleGenerateResult {
  created: number
  existed: number
  total_planned: number
  assignable_task_ids: string[]
  tasks: { task_id: string; created: boolean; status: string; assignment_id: string | null }[]
}

export interface GroupSampleAssignmentResult {
  assigned_count: number
  unassigned_count: number
  target_task_count: number
  assigned: { task_id: string; volunteer_user_id: string; warning_codes?: string[] }[]
  unassigned: { task_id: string; reason_code: string; message: string }[]
}

export interface GroupSamplingApi {
  listClassPage(collegeId: string, pageSize: number, page: number): Promise<AdministrativeClassPage>
  preview(collegeId: string, groupId: string, body: GroupSampleBody): Promise<GroupSamplePreview>
  generate(collegeId: string, groupId: string, body: GroupSampleBody & { selection_revision: string }): Promise<GroupSampleGenerateResult>
  assign(collegeId: string, groupId: string, body: { semester_id: string; task_ids: string[] }): Promise<GroupSampleAssignmentResult>
  previewAssignment(collegeId: string, groupId: string, body: { semester_id: string; task_ids: string[]; assignments?: Record<string, string>; reason?: string }): Promise<AssignmentPlan>
  commitAssignment(collegeId: string, groupId: string, planId: string, body: { revision: string; confirmations: AssignmentPlan['assigned'] }): Promise<GroupSampleAssignmentResult>
}

export interface AssignmentPlan {
  id: string
  revision: string
  expires_at: string
  assigned: { task_id: string; volunteer_user_id: string; warning_codes: string[] }[]
  unassigned: { task_id: string; reason_code: string; message: string }[]
  display?: {
    group_name: string
    semester_name: string
    tasks: Record<string, {
      course_name: string | null
      teaching_class_name: string | null
      classroom: string | null
      inspection_date: string
      start_period: number
      end_period: number
    }>
    volunteers: Record<string, {
      name: string
      student_no: string | null
      administrative_class_name: string | null
    }>
  }
}

const collegePath = (collegeId: string) => `/api/v1/colleges/${encodeURIComponent(collegeId)}`
const groupPath = (collegeId: string, groupId: string) =>
  `${collegePath(collegeId)}/groups/${encodeURIComponent(groupId)}/inspection`
const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const groupSamplingApi: GroupSamplingApi = {
  previewAssignment: (cid, gid, body) => request<AssignmentPlan>(`${groupPath(cid, gid)}/assignment-plans/preview`, post(body)),
  commitAssignment: (cid, gid, planId, body) => request<GroupSampleAssignmentResult>(`${groupPath(cid, gid)}/assignment-plans/${encodeURIComponent(planId)}/commit`, post(body)),
  listClassPage: (collegeId, pageSize, page) => request<AdministrativeClassPage>(
    `${collegePath(collegeId)}/academic/administrative-classes?page_size=${pageSize}&page=${page}`
  ),
  preview: (collegeId, groupId, body) => request<GroupSamplePreview>(
    `${groupPath(collegeId, groupId)}/sample-preview`, post(body)
  ),
  generate: (collegeId, groupId, body) => request<GroupSampleGenerateResult>(
    `${groupPath(collegeId, groupId)}/generate`, post(body)
  ),
  assign: (collegeId, groupId, body) => request<GroupSampleAssignmentResult>(
    `${groupPath(collegeId, groupId)}/assign`, post(body)
  )
}
