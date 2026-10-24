import { shallowRef, watch, onScopeDispose } from 'vue'
import { assistantWorkspacesApi as api, parseWorkspace, type StoredSelection, type WorkspaceScope, type PreviewReceipt, type ImportWorkspace } from '../api/assistantWorkspaces'
import type { ImportPreviewResult } from '../api/importer'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context extends WorkspaceScope { key: string; available: boolean; selection?: StoredSelection; target: string; teachingClassId: string; courseTypeId: string }
export function useStoredImportPreview(context: () => Context, resume: (rows: Array<ImportPreviewResult & { filename: string }>) => Promise<void> | void) {
  const busy = shallowRef(false), waiting = shallowRef(false), error = shallowRef(''), message = shallowRef('')
  const key = () => JSON.stringify(context())
  const epoch = new ContextEpoch(key)
  let nonce = '', timer: ReturnType<typeof setTimeout> | undefined, polls = 0, disposed = false
  const stop = () => { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  function matches(p: PreviewReceipt, c: Context) {
    return p.target === c.target && p.teaching_class_id === (c.teachingClassId || null) && p.course_type_id === (c.courseTypeId || null)
      && JSON.stringify([...p.member_nos].sort((a, b) => a - b)) === JSON.stringify([...(c.selection?.memberNos || [])].sort((a, b) => a - b))
  }
  function schedule() { stop(); if (!disposed && waiting.value && polls < 450) timer = setTimeout(() => { polls++; void refresh() }, 2000) }
  async function apply(row: ImportWorkspace, c: Context, ticket: ReturnType<ContextEpoch['begin']>) {
    const p = row.preview
    if (!p || !matches(p, c)) throw new Error('本组处理回执尚未找到，请重新核对所选资料')
    if (nonce && p.request_key !== nonce) throw new Error('当前回执属于另一组请求，请刷新资料后继续')
    nonce = p.request_key
    waiting.value = ['QUEUED', 'RUNNING'].includes(p.status)
    message.value = waiting.value ? '后台正在生成变化预览，可稍后回来继续核对。' : ''
    if (['FAILED', 'CANCELED'].includes(p.status)) { nonce = ''; throw new Error('本组未生成预览，请检查资料后重新生成；其他分组的记录仍保留。') }
    if (p.status !== 'SUCCEEDED') return
    const rows: Array<ImportPreviewResult & { filename: string }> = []
    for (let i = 0; i < p.batch_ids.length; i++) {
      const draft = await api.batch(p.batch_ids[i]!)
      if (!ticket.isCurrent()) return
      if (draft.id !== p.batch_ids[i] || draft.target !== c.target || draft.status !== 'PREVIEW' || (draft.semester_id && draft.semester_id !== c.semesterId)) throw new Error('这组预览已保存、失效或范围不符，请到最近导入记录核对结果。')
      const member = row.inspection?.files.find(m => m.member_no === p.member_nos[i])
      if (!member || member.blocked) throw new Error('本组来源记录不完整，请重新核对')
      rows.push({ ...draft, filename: member.filename })
    }
    if (ticket.isCurrent()) await resume(rows)
  }
  async function run(submit: boolean) {
    const c = context()
    if (disposed || busy.value || !c.available || !c.selection) return
    const ticket = epoch.begin(), scope = { collegeId: c.collegeId, semesterId: c.semesterId }, id = c.selection.workspaceId
    stop(); busy.value = true; error.value = ''
    try {
      let row = parseWorkspace(await api.read(id, scope), scope, id)
      if (!ticket.isCurrent()) return
      const prior = [...row.preview_receipts].reverse().find(p => matches(p, c) && (!nonce || p.request_key === nonce))
      if (prior) row = { ...row, preview: prior }
      if (submit && (!row.preview || !matches(row.preview, c) || ['FAILED', 'CANCELED'].includes(row.preview.status))) {
        nonce ||= crypto.randomUUID()
        const body = { target: c.target, member_nos: c.selection.memberNos, request_key: nonce, ...(c.teachingClassId ? { teaching_class_id: c.teachingClassId } : {}), ...(c.courseTypeId ? { course_type_id: c.courseTypeId } : {}) }
        row = parseWorkspace(await api.prepare(id, scope, body), scope, id)
        if (!ticket.isCurrent()) return
      }
      await apply(row, c, ticket)
    } catch (cause) { if (ticket.isCurrent()) { waiting.value = false; message.value = ''; error.value = cause instanceof Error ? cause.message : '读取失败，请查询处理进度后重试' } }
    finally { if (ticket.isLatest()) { busy.value = false; schedule() } }
  }
  async function prepare() { polls = 0; await run(true) }
  async function refresh() { await run(false) }
  watch(key, () => { epoch.invalidate(); stop(); nonce = ''; polls = 0; busy.value = false; waiting.value = false; error.value = ''; message.value = '' }, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; epoch.invalidate(); stop() })
  return { busy, waiting, error, message, prepare, refresh }
}
