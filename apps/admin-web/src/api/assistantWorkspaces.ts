import { request } from './http'
import { validAgentId } from './assistantReports'
import { getImportBatch } from './importer'

export interface WorkspaceScope { collegeId: string; semesterId: string }
export interface WorkspaceMember { member_no: number; filename: string; target: string | null; blocked: boolean; message: string; archive_member: string | null; sha256: string; size_bytes: number; duplicate_of: number | null }
export interface StoredSelection { workspaceId: string; memberNos: number[]; filenames: string[] }
export interface PreviewReceipt { request_key: string; target: string; status: string; batch_ids: string[]; member_nos: number[]; error_code: string | null; teaching_class_id: string | null; course_type_id: string | null }
export interface ImportWorkspace { workspace_id: string; filename: string; state: string; inspection: { files: WorkspaceMember[]; source_sha256: string } | null; preview: PreviewReceipt | null; preview_receipts: PreviewReceipt[]; error_code: string | null }
const root = '/api/v1/assistant/management/imports'
const targets = ['admin_roster', 'faculty_staff', 'class_responsibility', 'timetable', 'grid_timetable', 'volunteer', 'roster', 'elective_course', 'teaching_assignment']
const states = ['QUEUED', 'PROCESSING', 'READY', 'FAILED', 'CANCELED', 'PREVIEW_QUEUED', 'PREVIEW_PROCESSING']
const fail = (): never => { throw new Error('资料记录不完整或与当前学院、学期不一致，请重新核对') }
function record(value: unknown): Record<string, any> { if (!value || typeof value !== 'object' || Array.isArray(value)) return fail(); return value as Record<string, any> }
function query(scope: WorkspaceScope) { if (!validAgentId(scope.collegeId) || !validAgentId(scope.semesterId)) return fail(); return { college_id: scope.collegeId, semester_id: scope.semesterId } }
function path(id: string) { if (!validAgentId(id)) return fail(); return `${root}/${id}` }
export function parseWorkspace(value: unknown, scope: WorkspaceScope, expectedId?: string): ImportWorkspace {
  query(scope); const row = record(value)
  if (!validAgentId(row.workspace_id) || (expectedId !== undefined && expectedId !== row.workspace_id) || row.college_id !== scope.collegeId || row.semester_id !== scope.semesterId || row.business_data_applied !== false || typeof row.filename !== 'string' || !row.filename || row.filename.length > 255 || !states.includes(row.state) || !(row.error_code === null || typeof row.error_code === 'string')) return fail()
  let inspection: ImportWorkspace['inspection'] = null
  if (row.inspection !== null) {
    const data = record(row.inspection)
    if (data.protocol_version !== 1 || data.business_data_applied !== false || !/^[a-f0-9]{64}$/.test(data.source_sha256) || !Array.isArray(data.files) || !data.files.length || data.files.length > 1000) return fail()
    const files: WorkspaceMember[] = [], names = new Set<string>(); let total = 0
    for (const raw of data.files) {
      const m = record(raw)
      if (m.member_no !== files.length + 1 || typeof m.filename !== 'string' || !m.filename || m.filename.length > 255 || names.has(m.filename) || !(m.target === null || targets.includes(m.target)) || typeof m.blocked !== 'boolean' || typeof m.message !== 'string' || m.message.length > 512 || !(m.archive_member === null || m.archive_member === m.filename) || !/^[a-f0-9]{64}$/.test(m.sha256) || !Number.isInteger(m.size_bytes) || m.size_bytes < 0 || m.size_bytes > 10 * 1024 * 1024) return fail()
      if (m.duplicate_of !== null && (!Number.isInteger(m.duplicate_of) || !files[m.duplicate_of - 1] || files[m.duplicate_of - 1].sha256 !== m.sha256)) return fail()
      total += m.size_bytes; names.add(m.filename)
      files.push({ member_no: m.member_no, filename: m.filename, target: m.target, blocked: m.blocked, message: m.message, archive_member: m.archive_member, sha256: m.sha256, size_bytes: m.size_bytes, duplicate_of: m.duplicate_of })
    }
    if (total > 200 * 1024 * 1024) return fail()
    inspection = { files, source_sha256: data.source_sha256 }
  }
  if (['READY', 'PREVIEW_QUEUED', 'PREVIEW_PROCESSING'].includes(row.state) && !inspection) return fail()
  function parseReceipt(value: unknown): PreviewReceipt {
    const p = record(value)
    if (typeof p.request_key !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(p.request_key) || !targets.includes(p.target) || !['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED'].includes(p.status) || !Array.isArray(p.batch_ids) || p.batch_ids.length > 100 || !p.batch_ids.every(validAgentId) || new Set(p.batch_ids).size !== p.batch_ids.length || !Array.isArray(p.member_nos) || !p.member_nos.length || p.member_nos.length > 100 || !p.member_nos.every((n: unknown) => Number.isInteger(n) && Number(n) >= 1 && Number(n) <= 1000) || new Set(p.member_nos).size !== p.member_nos.length || (p.status === 'SUCCEEDED' && p.batch_ids.length !== p.member_nos.length)) return fail()
    if (![p.teaching_class_id, p.course_type_id].every(value => value == null || validAgentId(value))) return fail()
    return { request_key: p.request_key, target: p.target, status: p.status, batch_ids: p.batch_ids, member_nos: p.member_nos, error_code: typeof p.error_code === 'string' ? p.error_code : null, teaching_class_id: p.teaching_class_id ?? null, course_type_id: p.course_type_id ?? null }
  }
  const preview = row.preview == null ? null : parseReceipt(row.preview)
  if (row.preview_receipts !== undefined && (!Array.isArray(row.preview_receipts) || row.preview_receipts.length > 100)) return fail()
  const receipts: PreviewReceipt[] = (row.preview_receipts || []).map(parseReceipt)
  if (new Set(receipts.map(p => p.request_key)).size !== receipts.length) return fail()
  return { workspace_id: row.workspace_id, filename: row.filename, state: row.state, inspection, preview, preview_receipts: receipts, error_code: row.error_code }
}
export const assistantWorkspacesApi = {
  read: (id: string, scope: WorkspaceScope) => request<unknown>(`${path(id)}?${new URLSearchParams(query(scope))}`),
  lookup: (key: string, scope: WorkspaceScope) => { if (!/^[A-Za-z0-9_-]{1,64}$/.test(key)) return fail(); return request<unknown>(`${root}/by-request/${key}?${new URLSearchParams(query(scope))}`) },
  upload: (file: File, scope: WorkspaceScope, key: string) => {
    if (!/\.(zip|xlsx?|csv)$/i.test(file.name) || !file.size || file.size > (/\.zip$/i.test(file.name) ? 50 : 10) * 1024 * 1024) throw new Error('ZIP 上限50 MiB，单表格上限10 MiB，请检查文件')
    const body = new FormData(); Object.entries({ ...query(scope), request_key: key }).forEach(([k, v]) => body.append(k, v)); body.append('file', file, file.webkitRelativePath || file.name)
    return request<unknown>(root, { method: 'POST', body })
  },
  cancel: (id: string, scope: WorkspaceScope) => request<unknown>(`${path(id)}/cancel`, { method: 'POST', body: JSON.stringify(query(scope)) }),
  prepare: (id: string, scope: WorkspaceScope, body: { target: string; member_nos: number[]; request_key: string; teaching_class_id?: string; course_type_id?: string }) => request<unknown>(`${path(id)}/previews`, { method: 'POST', body: JSON.stringify({ ...query(scope), ...body }) }),
  batch: getImportBatch
}
