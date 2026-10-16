import { request } from './workspaceHttp'
import { request as directRequest } from './http'

export interface ImportChange {
  action: 'CREATE' | 'UPDATE' | 'UNCHANGED'; entity: string; key: string
  before: Record<string, unknown> | null; after: Record<string, unknown> | null
  source: { filename: string; row?: number; sheet?: string; column?: string }
}
export interface ImportSetPlan {
  revision: string; batch_ids: string[]; can_confirm: boolean; impact_note: string
  files: Array<{ id: string; filename: string; target: string; summary: Record<string, unknown>
    changes: ImportChange[]; issues: Array<{ severity: string; message: string; row?: number; field?: string; filename?: string }> }>
}
export interface ImportSetResult { status: string; batch_ids: string[]; files: Array<{ id: string; filename: string; summary: Record<string, unknown> }> }
const setRoot = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/imports/confirmation-set`
export const previewImportSet = (cid: string, ids: string[]) => directRequest<ImportSetPlan>(`${setRoot(cid)}/preview`, { method: 'POST', body: JSON.stringify({ batch_ids: ids }) })
export const confirmImportSet = (cid: string, ids: string[], revision: string) => directRequest<ImportSetResult>(`${setRoot(cid)}/confirm`, { method: 'POST', body: JSON.stringify({ batch_ids: ids, revision }) })

export interface ImportPreviewResult {
  id: string
  target: string
  status: string
  semester_id?: string | null
  teaching_class_id?: string | null
  summary: Record<string, any>
  errors: Array<{ code: string; message: string; field?: string; row?: number; severity: string }>
  warnings: Array<{ code: string; message: string; field?: string; row?: number; severity: string }>
  expires_at: string
  can_confirm: boolean
}

export interface ImportConfirmResult {
  id: string
  target: string
  status: string
  summary: Record<string, any>
}

export async function uploadImportFile(
  target: string,
  file: File,
  options: {
    semester_id?: string | number
    teaching_class_id?: string | number
    replace?: boolean
  } = {}
): Promise<ImportPreviewResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('target', target)
  if (options.semester_id !== undefined && options.semester_id !== null && options.semester_id !== '') {
    formData.append('semester_id', String(options.semester_id))
  }
  if (options.teaching_class_id !== undefined && options.teaching_class_id !== null && options.teaching_class_id !== '') {
    formData.append('teaching_class_id', String(options.teaching_class_id))
  }
  formData.append('replace', options.replace !== false ? 'true' : 'false')

  return request<ImportPreviewResult>('/api/v1/imports', {
    method: 'POST',
    body: formData
  })
}

export async function confirmImportBatch(batchId: string | number): Promise<ImportConfirmResult> {
  return request<ImportConfirmResult>(`/api/v1/imports/${batchId}/confirm`, {
    method: 'POST'
  })
}

export async function getImportBatch(batchId: string | number): Promise<ImportPreviewResult> {
  return request<ImportPreviewResult>(`/api/v1/imports/${batchId}`)
}

export interface BulkImportResult {
  total_files: number
  rosters_count: number
  timetables_count: number
  classes_created: number
  students_created: number
  students_updated: number
  students_transferred: number
  total_students?: number
  courses_created: number
  schedules_created: number
  file_results: Array<{
    filename: string
    type: string
    status: string
    error?: string
    summary?: Record<string, any>
  }>
}

export async function uploadBulkImport(
  semesterId: string | number,
  files: File[]
): Promise<BulkImportResult> {
  const formData = new FormData()
  formData.append('semester_id', String(semesterId))
  for (const f of files) {
    formData.append('files', f)
  }
  return request<BulkImportResult>('/api/v1/imports/bulk', {
    method: 'POST',
    body: formData
  })
}

export async function downloadImportTemplateFile(target: string): Promise<void> {
  const blob = await request<Blob>(
    `/api/v1/import-templates/${encodeURIComponent(target)}/file`,
    { method: 'GET' },
    false,
    'blob'
  )
  const targetNames: Record<string, string> = {
    admin_roster: '行政班与学生名单模板.xlsx',
    grid_timetable: '教学课表模板.xlsx',
    course_duty: '值勤排班模板.xlsx',
    self_study: '早晚自习排班模板.xlsx'
  }
  const filename = targetNames[target] || `${target}_template.xlsx`
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(link.href)
}

