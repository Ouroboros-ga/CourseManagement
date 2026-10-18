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
    changes: ImportChange[]; issues: Array<{ code?: string; severity: string; message: string; row?: number; field?: string; filename?: string }> }>
}
export interface ImportSetResult { status: string; batch_ids: string[]; files: Array<{ id: string; filename: string; summary: Record<string, unknown> }> }
const setRoot = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/imports/confirmation-set`
export type PersonLinkKind = 'teaching' | 'responsibility'
export interface PersonLinkRow {
  kind: PersonLinkKind; class_code?: string; course_code?: string; class_name?: string
  duty?: string; name: string; staff_no?: string; staff_id?: string
  action?: 'CREATE' | 'UNCHANGED'; message?: string
  effective_from: string; effective_to: string | null
}
export interface PersonLinkPlan {
  revision: string; summary: { person_links_create: number; person_links_existing: number; person_links_pending: number }
  links: PersonLinkRow[]; pending: PersonLinkRow[]
}
export const previewPersonLinks = (cid: string, body: { kind: PersonLinkKind; semester_id?: string }) => directRequest<PersonLinkPlan>(`${setRoot(cid)}/person-links/preview`, { method: 'POST', body: JSON.stringify(body) })
export const confirmPersonLinks = (cid: string, body: { kind: PersonLinkKind; semester_id?: string; revision: string }) => directRequest<{ person_links_created: number; person_links_pending: number }>(`${setRoot(cid)}/person-links/confirm`, { method: 'POST', body: JSON.stringify(body) })
export const previewImportSet = (cid: string, ids: string[]) => directRequest<ImportSetPlan>(`${setRoot(cid)}/preview`, { method: 'POST', body: JSON.stringify({ batch_ids: ids }) })
export const confirmImportSet = (cid: string, ids: string[], revision: string) => directRequest<ImportSetResult>(`${setRoot(cid)}/confirm`, { method: 'POST', body: JSON.stringify({ batch_ids: ids, revision }) })

export async function previewImportArchive(cid: string, target: string, file: File,
  options: { semester_id?: string; teaching_class_id?: string; course_type_id?: string; members?: string[] }) {
  const body = new FormData()
  body.append('file', file)
  body.append('target', target)
  for (const [key, value] of Object.entries(options)) if (value) body.append(key, Array.isArray(value) ? JSON.stringify(value) : value)
  return directRequest<{ files: Array<ImportPreviewResult & { filename: string }>; errors: Array<{ filename: string; message: string }> }>(
    `${setRoot(cid)}/zip-preview`, { method: 'POST', body })
}

export interface ImportCatalogItem {
  target: string; label: string; required: boolean; semester_required: boolean; manage_permission: string
}
export interface ImportInspectedFile {
  filename: string; target: string | null; blocked: boolean; message: string; archive_member: string | null
}
export interface ImportUploadSource { file: File; members?: string[] }
const intakeRoot = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/imports/intake`
export const getImportCatalog = (cid: string) => directRequest<{ types: ImportCatalogItem[]; max_files: number; max_file_bytes: number }>(`${intakeRoot(cid)}/catalog`)
export function inspectImportUpload(cid: string, file: File) {
  const body = new FormData()
  body.append('file', file, file.webkitRelativePath || file.name)
  return directRequest<{ files: ImportInspectedFile[]; business_data_applied: false }>(`${intakeRoot(cid)}/inspect`, { method: 'POST', body })
}
export async function downloadImportTemplatePack(cid: string) {
  const blob = await directRequest<Blob>(`${intakeRoot(cid)}/templates`, {}, false, 'blob')
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = '学院资料标准模板.zip'; link.click()
  URL.revokeObjectURL(url)
}

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
    course_type_id?: string | number
    replace?: boolean
  } = {}
): Promise<ImportPreviewResult> {
  const formData = new FormData()
  formData.append('file', file, file.webkitRelativePath || file.name)
  formData.append('target', target)
  if (options.semester_id !== undefined && options.semester_id !== null && options.semester_id !== '') {
    formData.append('semester_id', String(options.semester_id))
  }
  if (options.teaching_class_id !== undefined && options.teaching_class_id !== null && options.teaching_class_id !== '') {
    formData.append('teaching_class_id', String(options.teaching_class_id))
  }
  if (options.course_type_id !== undefined && options.course_type_id !== null && options.course_type_id !== '') {
    formData.append('course_type_id', String(options.course_type_id))
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

export interface ImportBatchListItem {
  id: string
  target: string
  status: string
  filename: string | null
  semester_id: string | null
  summary: Record<string, unknown>
  created_at: string
  expires_at: string
}

/** 学院最近导入列表（资料准备首页）；workspaceHttp 自动改写为学院工作区地址。 */
export async function listRecentImports(limit = 10): Promise<ImportBatchListItem[]> {
  return request<ImportBatchListItem[]>(`/api/v1/imports?limit=${limit}`)
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
  files: File[],
  courseTypeId?: string | number
): Promise<BulkImportResult> {
  const formData = new FormData()
  formData.append('semester_id', String(semesterId))
  if (courseTypeId !== undefined && courseTypeId !== null && courseTypeId !== '') {
    formData.append('course_type_id', String(courseTypeId))
  }
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

