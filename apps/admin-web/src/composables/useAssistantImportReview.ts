import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { assistantImportsApi, parseImportReview, type ImportReviewSummary, type ResumableImport } from '../api/assistantImports'
import { validAgentId } from '../api/assistantReports'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context { key: string; taskId: string; collegeId: string; semesterId: string; available: boolean }
export function useAssistantImportReview(context: () => Context, resume: (drafts: ResumableImport[]) => void) {
  const summary = shallowRef<ImportReviewSummary | null>(null), taskStatus = shallowRef('')
  const loading = shallowRef(false), opening = shallowRef(false), error = shallowRef('')
  const key = () => JSON.stringify(context()), reads = new ContextEpoch(key), opens = new ContextEpoch(key)
  let disposed = false
  const available = () => !disposed && context().available && !!context().collegeId && !!context().semesterId
  const groups = computed(() => [...new Set(summary.value?.files.map(file => file.target) || [])].map(target => ({
    target, files: summary.value!.files.filter(file => file.target === target)
  })))
  const failure = (cause: unknown) => cause instanceof Error ? cause.message : '资料读取失败，请刷新重试'
  async function refresh() {
    if (opening.value) return
    const ticket = reads.begin(), scope = context()
    summary.value = null; taskStatus.value = ''; error.value = ''
    if (!available()) { error.value = '当前学院或学期暂不可读取该核对任务'; return }
    if (!validAgentId(scope.taskId)) { error.value = '核对任务编号无效，请从助手重新打开'; return }
    loading.value = true
    try {
      const result = await assistantImportsApi.read(scope.taskId)
      if (!ticket.isCurrent()) return
      if (!result || typeof result !== 'object') throw new Error('核对任务读取不完整')
      const row = result as Record<string, unknown>
      if (row.task_id !== scope.taskId || typeof row.status !== 'string'
        || !['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED'].includes(row.status)) throw new Error('核对任务读取不完整')
      taskStatus.value = row.status
      if (row.status === 'SUCCEEDED') {
        const result = row.result as { status?: unknown; data?: unknown } | null
        if (result?.status !== 'SUCCEEDED') throw new Error('核对任务没有有效结果')
        summary.value = parseImportReview(result.data, scope.collegeId, scope.semesterId)
      }
    } catch (cause) { if (ticket.isCurrent()) { summary.value = null; error.value = failure(cause) } }
    finally { if (ticket.isLatest()) loading.value = false }
  }
  async function open(target: string) {
    if (!available() || loading.value || opening.value || !summary.value || error.value) return
    const files = summary.value.files.filter(file => file.target === target)
    if (!files.length) return
    const ticket = opens.begin(), scope = context(), drafts: ResumableImport[] = []
    opening.value = true
    try {
      for (const file of files) {
        const draft = await assistantImportsApi.batch(file.batch_id)
        if (!ticket.isCurrent()) return
        if (draft.id !== file.batch_id || draft.target !== target || draft.status !== 'PREVIEW'
          || (draft.semester_id != null && draft.semester_id !== scope.semesterId)) throw new Error('资料预览已变化，请重新读取核对任务')
        drafts.push({ ...draft, filename: `资料预览 ${file.batch_id}` })
      }
      if (ticket.isCurrent()) resume(drafts)
    } catch (cause) { if (ticket.isCurrent()) { summary.value = null; error.value = failure(cause) } }
    finally { if (ticket.isLatest()) opening.value = false }
  }
  watch(key, () => {
    reads.invalidate(); opens.invalidate(); summary.value = null; taskStatus.value = ''
    loading.value = false; opening.value = false; error.value = ''; void refresh()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { disposed = true; reads.invalidate(); opens.invalidate() })
  return { summary, groups, taskStatus, loading, opening, error, refresh, open }
}
