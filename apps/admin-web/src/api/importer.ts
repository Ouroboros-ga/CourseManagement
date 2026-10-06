import { request } from './http'

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

