import { request } from './http'
import { getImportBatch, type ImportPreviewResult } from './importer'
import { validAgentId } from './assistantReports'

const targets = ['volunteer', 'admin_roster', 'roster', 'timetable', 'grid_timetable', 'elective_course', 'faculty_staff', 'class_duty', 'class_responsibility', 'teaching_assignment'] as const
export interface ImportReviewFile { batch_id: string; target: string; changes: Record<string, number>; error_count: number; warning_count: number }
export interface ImportReviewSummary { college_id: string; semester_id: string; files: ImportReviewFile[]; can_confirm: boolean }
export type ResumableImport = ImportPreviewResult & { filename: string }
const fail = (): never => { throw new Error('资料核对结果与当前工作区不一致，请返回助手重新发起') }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail()
  return value as Record<string, unknown>
}
function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) return fail()
  return value
}
export function parseImportReview(value: unknown, collegeId: string, semesterId: string): ImportReviewSummary {
  const row = record(value)
  if (!validAgentId(collegeId) || !validAgentId(semesterId) || row.kind !== 'IMPORT_PREVIEW_REVIEW'
    || row.college_id !== collegeId || row.semester_id !== semesterId
    || row.business_data_applied !== false || row.requires_human_confirmation !== true
    || typeof row.can_confirm !== 'boolean' || !Array.isArray(row.files)
    || !row.files.length || row.files.length > 100) return fail()
  const seen = new Set<string>()
  const files = row.files.map(value => {
    const file = record(value), changes = record(file.changes)
    if (!validAgentId(file.batch_id) || seen.has(file.batch_id)
      || typeof file.target !== 'string' || !targets.includes(file.target as typeof targets[number])) return fail()
    seen.add(file.batch_id)
    const normalized: Record<string, number> = {}
    for (const [key, value] of Object.entries(changes)) {
      if (!['CREATE', 'UPDATE', 'UNCHANGED'].includes(key)) return fail()
      normalized[key] = count(value)
    }
    return { batch_id: file.batch_id, target: file.target, changes: normalized,
      error_count: count(file.error_count), warning_count: count(file.warning_count) }
  })
  return { college_id: collegeId, semester_id: semesterId, files, can_confirm: row.can_confirm }
}
export const assistantImportsApi = {
  read: (taskId: string) => request<unknown>(`/api/v1/assistant/tasks/${taskId}`),
  batch: (batchId: string) => getImportBatch(batchId)
}
