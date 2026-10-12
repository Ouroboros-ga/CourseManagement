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
  word_available?: boolean
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
  attendance_rate?: number | null
}

export interface ClassStatsItem {
  class_id?: string | null
  class_name: string
  head_teacher?: string | null
  counselor?: string | null
  expected_count: number
  abnormal_count: number
  normal_count: number
  leave_count: number
  late_count: number
  absent_count: number
  abnormal_rate?: number | null
  attendance_rate?: number | null
  class_ratio_available: boolean
  excluded_task_count: number
}

export interface AbnormalDetailItem {
  task_id: string
  attendance_type: 'ABSENT' | 'LATE' | 'LEAVE' | string
  student_no: string
  name: string
  class_name_snapshot?: string | null
  inspection_date?: string
  date_display?: string
  course_name?: string
  inspection_type?: string
  start_period?: number | null
  end_period?: number | null
  classroom?: string | null
  teacher_name?: string | null
}

export interface TaskStatsItem {
  task_id: string
  inspection_date: string
  week_no: number
  course_name_snapshot?: string | null
  class_name_snapshot?: string | null
  classroom_snapshot?: string | null
  teacher_name_snapshot?: string | null
  start_period?: number | null
  end_period?: number | null
  expected_count: number
  normal_count: number
  leave_count: number
  late_count: number
  absent_count: number
  abnormal_count: number
  attendance_rate?: number | null
  expected_count_adjusted: boolean
  class_ratio_available: boolean
}

export interface AttendanceStatsResponse {
  semester_id: string
  week_no?: number | null
  date_from?: string | null
  date_to?: string | null
  eligible_task_count: number
  overall: OverallStats
  classes: ClassStatsItem[]
  tasks?: TaskStatsItem[] | null
  details?: AbnormalDetailItem[] | null
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
  include_tasks?: boolean
}): Promise<AttendanceStatsResponse> {
  const query = new URLSearchParams()
  query.set('semester_id', String(params.semester_id))
  if (params.week_no) query.set('week_no', String(params.week_no))
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)
  if (params.include_tasks !== undefined) query.set('include_tasks', String(params.include_tasks))
  else query.set('include_tasks', 'true')

  return request<AttendanceStatsResponse>(`/api/v1/statistics/attendance?${query.toString()}`)
}

export async function exportAttendanceAnalytics(params: {
  semester_id: number
  week_no?: number
  date_from?: string
  date_to?: string
}): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken()
  const query = new URLSearchParams()
  query.set('semester_id', String(params.semester_id))
  if (params.week_no) query.set('week_no', String(params.week_no))
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)

  const res = await fetch(`/api/v1/statistics/attendance/export?${query.toString()}`, {
    method: 'GET',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!res.ok) {
    let msg = `导出考勤数据分析失败: HTTP ${res.status}`
    try {
      const errJson = await res.json()
      if (errJson.message) msg = errJson.message
    } catch {}
    throw new Error(msg)
  }

  const disposition = res.headers.get('Content-Disposition')
  let filename = `attendance_analytics_${params.week_no ? `w${params.week_no}` : 'export'}.xlsx`
  if (disposition) {
    const match = disposition.match(/filename="?([^";]+)"?/)
    if (match && match[1]) {
      filename = decodeURIComponent(match[1])
    }
  }

  const blob = await res.blob()
  return { blob, filename }
}

export async function exportAttendanceDetailWord(params: {
  semester_id: number
  week_no?: number
  date_from?: string
  date_to?: string
}): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken()
  const query = new URLSearchParams()
  query.set('semester_id', String(params.semester_id))
  if (params.week_no) query.set('week_no', String(params.week_no))
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)

  const res = await fetch(`/api/v1/statistics/attendance/export-detail-doc?${query.toString()}`, {
    method: 'GET',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!res.ok) {
    let msg = `导出考勤异常详表失败: HTTP ${res.status}`
    try {
      const errJson = await res.json()
      if (errJson.message) msg = errJson.message
    } catch {}
    throw new Error(msg)
  }

  const disposition = res.headers.get('Content-Disposition')
  let filename = `attendance_detail_${params.week_no ? `w${params.week_no}` : 'export'}.docx`
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    if (utf8Match && utf8Match[1]) {
      filename = decodeURIComponent(utf8Match[1])
    } else {
      const match = disposition.match(/filename="?([^";]+)"?/)
      if (match && match[1]) {
        filename = decodeURIComponent(match[1])
      }
    }
  }

  const blob = await res.blob()
  return { blob, filename }
}

export async function exportStudyAttendanceExcel(params: {
  semester_id: number
  week_no?: number
  date_from?: string
  date_to?: string
}): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken()
  const query = new URLSearchParams()
  query.set('semester_id', String(params.semester_id))
  if (params.week_no) query.set('week_no', String(params.week_no))
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)

  const res = await fetch(`/api/v1/statistics/attendance/export-study-excel?${query.toString()}`, {
    method: 'GET',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!res.ok) {
    let msg = `导出自习考勤表失败: HTTP ${res.status}`
    try {
      const errJson = await res.json()
      if (errJson.message) msg = errJson.message
    } catch {}
    throw new Error(msg)
  }

  const disposition = res.headers.get('Content-Disposition')
  let filename = `study_attendance_${params.week_no ? `w${params.week_no}` : 'export'}.xlsx`
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    if (utf8Match && utf8Match[1]) {
      filename = decodeURIComponent(utf8Match[1])
    } else {
      const match = disposition.match(/filename="?([^";]+)"?/)
      if (match && match[1]) {
        filename = decodeURIComponent(match[1])
      }
    }
  }

  const blob = await res.blob()
  return { blob, filename }
}

export async function downloadReportVersionFile(
  versionId: string | number,
  kind: 'EXCEL' | 'SNAPSHOT' | 'WORD' | 'DETAIL_WORD' | 'STUDY_EXCEL' = 'EXCEL'
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
  let ext = 'json'
  if (kind === 'EXCEL' || kind === 'STUDY_EXCEL') ext = 'xlsx'
  else if (kind === 'WORD' || kind === 'DETAIL_WORD') ext = 'docx'
  let filename = `attendance_report_${versionId}.${ext}`
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    if (utf8Match && utf8Match[1]) {
      filename = decodeURIComponent(utf8Match[1])
    } else {
      const match = disposition.match(/filename="?([^";]+)"?/)
      if (match && match[1]) {
        filename = decodeURIComponent(match[1])
      }
    }
  }

  const blob = await res.blob()
  return { blob, filename }
}
