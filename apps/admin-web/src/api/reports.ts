import { request, getAccessToken } from './http'

export interface ReportSummaryItem {
  report_id: string
  semester_id: string
  week_no: number
  latest_version_id?: string | null
  latest_version_no?: number | null
  latest_version_created_at?: string | null
  source_changed: boolean
}

export interface ListReportsResult {
  items: ReportSummaryItem[]
  page: number
  page_size: number
  total: number
}

export interface ReportVersionSummary {
  id: string
  version_no: number
  status: 'GENERATING' | 'PUBLISHED' | 'FAILED'
  source_revision: number
  rule_version: number
  template_version: number
  generated_at?: string | null
  created_at: string
  generated_by?: string | null
  reason?: string | null
  snapshot_available: boolean
  excel_available: boolean
  behind_source: boolean
  rule_outdated: boolean
  template_outdated: boolean
}

export interface ReportVersionsResponse {
  report_id: string
  semester_id: string
  week_no: number
  scope: 'COLLEGE' | 'CLASS'
  current_source_revision: number
  current_rule_version: number
  current_template_version: number
  latest_version_no: number
  latest_updated_at?: string | null
  latest_behind_source: boolean
  items: ReportVersionSummary[]
}

export interface WeeklyVersionCreateRequest {
  semester_id: number
  week_no: number
  scope?: 'COLLEGE'
  reason?: string
}

export interface GenerateReportResponse {
  report_id: string
  semester_id: string
  week_no: number
  scope: string
  version: ReportVersionSummary
  current_source_revision: number
  message: string
}

export interface OverallStats {
  statistics_available: boolean
  expected_count: number
  abnormal_count: number
  normal_count: number
  leave_count: number
  late_count: number
  absent_count: number
  abnormal_rate?: number | null
}

export interface ClassStatsItem {
  class_name: string
  expected_count: number
  abnormal_count: number
  normal_count: number
  leave_count: number
  late_count: number
  absent_count: number
  abnormal_rate?: number | null
  class_ratio_available: boolean
  excluded_task_count: number
}

export interface AttendanceStatsResponse {
  semester_id: string
  week_no?: number | null
  date_from?: string | null
  date_to?: string | null
  eligible_task_count: number
  overall: OverallStats
  classes: ClassStatsItem[]
}

export async function listReports(params: {
  semester_id?: number
  week_no?: number
  page?: number
  page_size?: number
} = {}): Promise<ListReportsResult> {
  const query = new URLSearchParams()
  if (params.semester_id) query.set('semester_id', String(params.semester_id))
  if (params.week_no) query.set('week_no', String(params.week_no))
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))

  const qs = query.toString()
  return request<ListReportsResult>(`/api/v1/reports${qs ? `?${qs}` : ''}`)
}

export async function listReportVersions(reportId: string | number): Promise<ReportVersionsResponse> {
  return request<ReportVersionsResponse>(`/api/v1/reports/${reportId}/versions`)
}

export async function generateWeeklyReportVersion(body: WeeklyVersionCreateRequest): Promise<GenerateReportResponse> {
  return request<GenerateReportResponse>('/api/v1/reports/weekly/versions', {
    method: 'POST',
    body: JSON.stringify({
      ...body,
      scope: body.scope || 'COLLEGE'
    })
  })
}

export async function getAttendanceStats(params: {
  semester_id: number
  week_no?: number
  date_from?: string
  date_to?: string
}): Promise<AttendanceStatsResponse> {
  const query = new URLSearchParams()
  query.set('semester_id', String(params.semester_id))
  if (params.week_no) query.set('week_no', String(params.week_no))
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)

  return request<AttendanceStatsResponse>(`/api/v1/statistics/attendance?${query.toString()}`)
}

export async function downloadReportVersionFile(
  versionId: string | number,
  kind: 'EXCEL' | 'SNAPSHOT' = 'EXCEL'
): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken()
  const res = await fetch(`/api/v1/report-versions/${versionId}/download?kind=${kind}`, {
    method: 'GET',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!res.ok) {
    let msg = `下载周报失败: HTTP ${res.status}`
    try {
      const errJson = await res.json()
      if (errJson.message) msg = errJson.message
    } catch {}
    throw new Error(msg)
  }

  const disposition = res.headers.get('Content-Disposition')
  let filename = `attendance_report_${versionId}.${kind === 'EXCEL' ? 'xlsx' : 'json'}`
  if (disposition) {
    const match = disposition.match(/filename="?([^";]+)"?/)
    if (match && match[1]) {
      filename = decodeURIComponent(match[1])
    }
  }

  const blob = await res.blob()
  return { blob, filename }
}
