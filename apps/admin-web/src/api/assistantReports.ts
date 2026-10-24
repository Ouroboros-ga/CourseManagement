import { request, type DownloadResponse } from './http'

const formats = {
  ANALYTICS_XLSX: { suffix: 'export', title: '考勤统计表（Excel）', extension: 'xlsx', mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
  DETAIL_DOCX: { suffix: 'export-detail-doc', title: '考勤明细（Word）', extension: 'docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
  STUDY_XLSX: { suffix: 'export-study-excel', title: '学风考勤表（Excel）', extension: 'xlsx', mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }
} as const
export type ReportFormat = keyof typeof formats
export interface ReportWindow { semester_id: string; week_no?: number; date_from?: string; date_to?: string }
export interface ReportAction {
  format: ReportFormat; title: string; college_id: string; window: ReportWindow; matching_task_count: number
}
export const validAgentId = (value: unknown): value is string => typeof value === 'string'
  && /^[1-9][0-9]{0,18}$/.test(value) && (value.length < 19 || value <= '9223372036854775807')
const fail = (): never => { throw new Error('导出任务内容不完整或与当前学院、学期不一致，请重新核对') }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail()
  return value as Record<string, unknown>
}
function reportFormat(value: unknown): ReportFormat {
  if (typeof value !== 'string' || !Object.prototype.hasOwnProperty.call(formats, value)) return fail()
  return value as ReportFormat
}
function day(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return fail()
  const parsed = new Date(`${value}T00:00:00Z`)
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) return fail()
  return value
}
function windowQuery(value: unknown): ReportWindow {
  const row = record(value)
  if (!validAgentId(row.semester_id) || Object.keys(row).some(key => !['semester_id', 'week_no', 'date_from', 'date_to'].includes(key))) return fail()
  if (row.week_no !== undefined) {
    if (typeof row.week_no !== 'number' || !Number.isInteger(row.week_no) || row.week_no < 1 || row.week_no > 60
      || row.date_from !== undefined || row.date_to !== undefined) return fail()
    return { semester_id: row.semester_id, week_no: row.week_no }
  }
  const start = day(row.date_from), end = day(row.date_to)
  const days = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000
  if (days < 0 || days > 92) return fail()
  return { semester_id: row.semester_id, date_from: start, date_to: end }
}
function downloadPath(collegeId: string, format: ReportFormat, window: ReportWindow) {
  if (!validAgentId(collegeId)) return fail()
  const query = new URLSearchParams({ semester_id: window.semester_id })
  if (window.week_no !== undefined) query.set('week_no', String(window.week_no))
  else { query.set('date_from', window.date_from!); query.set('date_to', window.date_to!) }
  return `/api/v1/colleges/${collegeId}/statistics/attendance/${formats[format].suffix}?${query}`
}
export function parseReportAction(value: unknown, collegeId: string, semesterId: string): ReportAction {
  const row = record(value), format = reportFormat(row.format), window = windowQuery(row.window)
  if (row.kind !== 'ATTENDANCE_REPORT_DOWNLOAD' || row.artifact_status !== 'NOT_GENERATED'
    || row.college_id !== collegeId || !validAgentId(collegeId) || window.semester_id !== semesterId
    || typeof row.matching_task_count !== 'number' || !Number.isSafeInteger(row.matching_task_count) || row.matching_task_count < 0) return fail()
  const download = record(row.download)
  if (download.method !== 'GET' || download.requires_login !== true || download.path !== downloadPath(collegeId, format, window)) return fail()
  return { format, title: formats[format].title, college_id: collegeId, window, matching_task_count: row.matching_task_count }
}
export const assistantReportsApi = {
  read: (taskId: string) => {
    if (!validAgentId(taskId)) throw new Error('导出任务编号无效，请从助手重新打开')
    return request<unknown>(`/api/v1/assistant/tasks/${taskId}`)
  },
  download: async (plan: ReportAction): Promise<DownloadResponse> => {
    // Reconstruct, rather than fetch any URL from the model or stored result.
    const format = reportFormat(plan.format), window = windowQuery(plan.window)
    const file = await request<DownloadResponse>(downloadPath(plan.college_id, format, window), { method: 'GET' }, false, 'download')
    const mime = file.blob.type.split(';')[0]?.toLowerCase()
    if (!file.blob.size || ![formats[format].mime, 'application/octet-stream'].includes(mime)) throw new Error('报表文件响应异常，请刷新任务后重试')
    return { blob: file.blob, filename: file.filename || `attendance_report.${formats[format].extension}` }
  }
}
