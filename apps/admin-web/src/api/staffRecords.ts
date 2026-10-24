/** 教职工本人工作视图接口：查课卡片、明细、汇总、导出、正式课次与课次教室、考勤更正与责任区异议。
 *
 * 全部走 `/api/v1/me/**`，不依赖学院选择器，也不使用全院权限；
 * 服务端按有效任职关系逐请求判定，前端只按响应里的 `allowed_actions` 与 `can_review` 显示动作。
 * ID 一律字符串，避免 JavaScript 截断 BIGINT。
 */
import { getAccessToken, request } from './http'
import type { ObjectionItem } from './objections'

export type StaffView = 'teaching' | 'responsible'

export interface StaffCollegeBrief {
  id: string
  name: string
}

export interface StaffAttendanceCounts {
  total: number
  NORMAL: number
  LEAVE: number
  LATE: number
  ABSENT: number
}

export interface StaffRecordCard {
  task_id: string
  teaching_class_id?: string | null
  occurrence_key: string
  course_name: string
  class_name_snapshot?: string | null
  responsible_college: StaffCollegeBrief
  inspection_date: string
  starts_at?: string | null
  ends_at?: string | null
  start_period?: number | null
  end_period?: number | null
  classroom?: string | null
  location_revision?: string | null
  attendance_state: string
  scope: { view: StaffView; count_basis: string }
  counts?: StaffAttendanceCounts | null
  allowed_actions: string[]
}

export interface StaffStudentAttendance {
  attendance_record_id: string
  task_id: string
  student_id: string
  student_no: string
  name: string
  administrative_class_name_snapshot?: string | null
  effective_type: string
  current_version: number
  photo_file_ids: string[]
  allowed_actions: string[]
  restriction_reason?: string | null
}

export interface StaffRecordPage<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface StaffSummaryCollege {
  college_id: string
  college_name: string
  task_count: number
  student_counts: StaffAttendanceCounts
}

export interface StaffSummary {
  view: StaffView
  scope_description: string
  task_count: number
  recorded_task_count: number
  unrecorded_task_count: number
  student_counts: StaffAttendanceCounts
  college_summaries: StaffSummaryCollege[]
}

export interface StaffRecordFilters {
  semester_id?: string | number
  inspection_date?: string
  date_from?: string
  date_to?: string
  teaching_class_id?: string | number
  administrative_class_id?: string | number
  responsible_college_id?: string | number
  course_name?: string
}

const search = (params: Record<string, unknown>) => {
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') usp.set(key, String(value))
  }
  const text = usp.toString()
  return text ? `?${text}` : ''
}

export function listRecordCards(view: StaffView, filters: StaffRecordFilters = {}, page = 1, pageSize = 50) {
  return request<StaffRecordPage<StaffRecordCard>>(
    `/api/v1/me/inspection-records${search({ view, page, page_size: pageSize, ...filters })}`
  )
}

export function getRecordCard(taskId: string, view: StaffView) {
  return request<StaffRecordCard>(`/api/v1/me/inspection-records/${encodeURIComponent(taskId)}${search({ view })}`)
}

export function listTaskAttendance(taskId: string, view: StaffView, effectiveType = '', page = 1, pageSize = 50) {
  return request<StaffRecordPage<StaffStudentAttendance>>(
    `/api/v1/me/inspection-records/${encodeURIComponent(taskId)}/attendance${search({ view, effective_type: effectiveType, page, page_size: pageSize })}`
  )
}

export function getRecordsSummary(view: StaffView, filters: StaffRecordFilters = {}) {
  return request<StaffSummary>(`/api/v1/me/inspection-records/summary${search({ view, ...filters })}`)
}

/** 导出与列表共用同一谓词：文件名由服务端给出（含学期与视图口径），前端不改写。 */
export async function exportRecords(
  view: StaffView,
  filters: StaffRecordFilters = {}
): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken()
  const res = await fetch(
    `/api/v1/me/inspection-records/export${search({ view, ...filters })}`,
    {
      method: 'GET',
      credentials: 'include',
      headers: {
        Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/octet-stream, */*',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    }
  )
  if (!res.ok) {
    let message = `导出失败: HTTP ${res.status}`
    try {
      const payload = await res.json()
      if (payload?.message) message = payload.message
    } catch {
      /* 非 JSON 错误体保留状态码提示 */
    }
    throw new Error(message)
  }
  const disposition = res.headers.get('Content-Disposition') || ''
  const extended = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  const filename = extended?.[1]
    ? decodeURIComponent(extended[1])
    : plain?.[1] || `教职工查课记录_${view}.xlsx`
  return { blob: await res.blob(), filename }
}

export interface StaffOccurrenceLocation {
  occurrence_key: string
  base_location?: string | null
  current_location?: string | null
  overridden: boolean
  revision: number
  affected_task_ids: string[]
}

export function getOccurrenceLocation(teachingClassId: string, occurrenceKey: string) {
  return request<StaffOccurrenceLocation>(
    `/api/v1/me/teaching-classes/${encodeURIComponent(teachingClassId)}/occurrences/${encodeURIComponent(occurrenceKey)}/location`
  )
}

export interface StaffTeachingOccurrence {
  occurrence_key: string
  teaching_class_id: string
  semester_id: string
  inspection_date: string
  weekday: number
  start_period: number
  end_period: number
  course_names: string[]
  class_names: string[]
  base_location?: string | null
  current_location?: string | null
  overridden: boolean
  revision: number
  task_ids: string[]
}

export interface StaffTeachingOccurrencePage {
  items: StaffTeachingOccurrence[]
  total: number
  page: number
  page_size: number
  date_from: string
  date_to: string
  scope_description: string
}

/** 本人正式课次日历：查课卡片只覆盖被抽到的课，换教室不以“先被抽查”为前提。 */
export function listTeachingOccurrences(
  dateFrom: string,
  dateTo: string,
  page = 1,
  pageSize = 50,
  teachingClassId?: string
) {
  return request<StaffTeachingOccurrencePage>(
    `/api/v1/me/teaching-occurrences${search({
      date_from: dateFrom, date_to: dateTo, page, page_size: pageSize,
      teaching_class_id: teachingClassId
    })}`
  )
}

export function changeOccurrenceLocation(
  teachingClassId: string,
  occurrenceKey: string,
  // revision 必传：后端契约取消了“不传即跳过版本校验”的分支。
  body: { location: string | null; revision: number; reason?: string | null }
) {
  return request<StaffOccurrenceLocation>(
    `/api/v1/me/teaching-classes/${encodeURIComponent(teachingClassId)}/occurrences/${encodeURIComponent(occurrenceKey)}/location`,
    { method: 'PATCH', body: JSON.stringify(body) }
  )
}

export interface StaffAttendanceCorrection {
  id: string
  effective_type: string
  current_version: number
  has_objection?: boolean
  objection_status?: string | null
}

/** 本人授课记录的直接更正；current_version 过期返回 409，不覆盖他人认定。 */
export function correctTeachingAttendance(
  recordId: string,
  body: { attendance_type: string; current_version: number; reason?: string }
) {
  return request<StaffAttendanceCorrection>(
    `/api/v1/me/teaching-attendance/${encodeURIComponent(recordId)}/corrections`,
    { method: 'POST', body: JSON.stringify(body) }
  )
}

export interface AttendanceVersion {
  id: string
  attendance_record_id: string
  version_no: number
  attendance_type: string
  source_type: string
  source_id?: string | null
  changed_by?: string | null
  reason?: string | null
  created_at?: string | null
}

/** 卡片允许 view_history 就必须有对应的本人历史入口，不能只过滤列表。 */
export function listAttendanceRecordVersions(recordId: string, view: StaffView) {
  // 两种工作视图的明细都会给出 view_history，历史入口因此必须带视图，由服务端按同一谓词判定。
  return request<AttendanceVersion[]>(
    `/api/v1/me/attendance-records/${encodeURIComponent(recordId)}/versions?view=${view}`
  )
}

export interface ResponsibleObjectionItem {
  objection: ObjectionItem
  task_id?: string | null
  responsible_college_id?: string | null
  responsible_college_name?: string | null
  can_review: boolean
  review_block_reason?: string | null
}

export interface ResponsibleObjectionPage {
  items: ResponsibleObjectionItem[]
  total: number
  page: number
  page_size: number
}

export function listResponsibleObjections(
  params: { final_status?: string; initial_status?: string; semester_id?: string | number; administrative_class_id?: string | number; page?: number; page_size?: number } = {}
) {
  return request<ResponsibleObjectionPage>(`/api/v1/me/responsible-objections${search({ ...params })}`)
}

export function getResponsibleObjection(objectionId: string) {
  return request<ResponsibleObjectionItem>(`/api/v1/me/responsible-objections/${encodeURIComponent(objectionId)}`)
}

export function reviewResponsibleObjection(
  objectionId: string,
  body: { decision: 'APPROVED' | 'REJECTED'; final_type?: string | null; comment?: string | null; current_version: number; precheck_job_id?: string | null; manual_precheck_reason?: string }
) {
  return request<ObjectionItem>(
    `/api/v1/me/responsible-objections/${encodeURIComponent(objectionId)}/review`,
    { method: 'POST', body: JSON.stringify(body) }
  )
}
