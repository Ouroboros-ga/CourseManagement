import { request } from './http'
export interface TeacherCollege { user_id: string; college_id: string | null; lock_version: number; handoff?: Record<string, unknown> }
export interface ManagerFunctions { user_id: string; college_id: string; allowed_actions: string[]; configurable_actions: string[]; lock_version: number }
export interface EnrollmentCommand { kind: 'TRANSFER' | 'RETURN' | 'SUSPEND' | 'GRADUATE' | 'WITHDRAW'; effective_date: string; target_class_id: string | null; lock_version: number; idempotency_key: string; reason: string | null; correct_existing?: boolean }
export interface EnrollmentResult { id: string; student_id: string; student_no: string; state: string; kind: string; effective_date: string; lock_version: number; impact: Record<string, unknown> }
export interface EnrollmentHistory { student_id: string; student_no: string; lock_version: number; changes: EnrollmentResult[]; enrollments: { id: string; effective_from: string; effective_to: string | null; status: string; historical_confirmed: boolean; superseded: boolean; snapshot: Record<string, unknown> }[] }
export interface DataPlan { id: string; lock_version: number; rows: { student_no: string; name: string; action: string; errors: string[] }[]; missing_student_ids: string[]; missing_students?: {id: string; student_no: string; name: string}[]; errors?: unknown[]; status: string }
const root = '/api/v1/academic'
const body = (method: string, value: unknown) => ({ method, body: JSON.stringify(value) })
export const getTeacherCollege = (id: string) => request<TeacherCollege>(`${root}/teacher-colleges/${id}`)
export const setTeacherCollege = (id: string, college_id: string, lock_version: number) => request<TeacherCollege>(`${root}/teacher-colleges/${id}`, body('PUT', { college_id, lock_version }))
export const getManagerFunctions = (id: string) => request<ManagerFunctions>(`${root}/student-manager-functions/${id}`)
export const setManagerFunctions = (id: string, allowed_actions: string[], lock_version: number) => request<ManagerFunctions>(`${root}/student-manager-functions/${id}`, body('PUT', { allowed_actions, lock_version }))
export const enrollmentHistory = (id: string) => request<EnrollmentHistory>(`${root}/students/${id}/enrollment-history`)
export const previewEnrollment = (id: string, command: EnrollmentCommand) => request<Record<string, unknown>>(`${root}/students/${id}/enrollment-changes/preview`, body('POST', command))
export const applyEnrollment = (id: string, command: EnrollmentCommand) => request<EnrollmentResult>(`${root}/students/${id}/enrollment-changes`, body('POST', command))
export const cancelEnrollment = (id: string, changeId: string, lock_version: number) => request<EnrollmentResult>(`${root}/students/${id}/enrollment-changes/${changeId}/cancel`, body('POST', { lock_version }))
export const previewStudentFile = (college_id: string, file: File, purpose: string) => {
  const form = new FormData(); form.append('college_id', college_id); form.append('file', file); form.append('purpose', purpose)
  return request<DataPlan>(`${root}/student-data/preview-file`, { method: 'POST', body: form })
}
export const confirmStudentFile = (plan: DataPlan) => request<DataPlan>(`${root}/student-data/${plan.id}/confirm`, body('POST', { lock_version: plan.lock_version }))
export const exportStudentFile = (college: string, archive: boolean) => request<Blob>(`${root}/student-data/export?college_id=${college}&include_archive=${archive}`, {}, false, 'blob')
export interface HandoffTask { id: string; college_id: string | null; inspection_date: string; course_name: string | null; class_name: string | null; expected_count_current: number; roster_review_required: boolean; expected_count_review_required: boolean; lock_version: number }
export const pendingHandoffTasks = () => request<{ items: HandoffTask[] }>(`${root}/enrollment-handoff/tasks`)
export const reviewHandoffTask = (task: HandoffTask) => request(`${root}/enrollment-handoff/tasks/${task.id}/review`, body('POST', { lock_version: task.lock_version, confirm_roster: true, confirm_expected_count: true }))
