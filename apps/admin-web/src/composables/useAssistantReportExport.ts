import { shallowRef, watch, onScopeDispose } from 'vue'
import { assistantReportsApi, parseReportAction, validAgentId, type ReportAction } from '../api/assistantReports'
import type { DownloadResponse } from '../api/http'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context { key: string; taskId: string; collegeId: string; semesterId: string; available: boolean }
const message = (cause: unknown) => cause instanceof Error ? cause.message : '无法读取导出任务，请刷新核对'
export function useAssistantReportExport(context: () => Context, saveFile: (file: DownloadResponse) => void) {
  const plan = shallowRef<ReportAction | null>(null), taskStatus = shallowRef('')
  const loading = shallowRef(false), downloading = shallowRef(false), error = shallowRef(''), notice = shallowRef('')
  const key = () => JSON.stringify(context()), reads = new ContextEpoch(key), downloads = new ContextEpoch(key)
  let disposed = false
  const available = () => !disposed && context().available && !!context().collegeId && !!context().semesterId
  async function refresh() {
    if (downloading.value) return
    const ticket = reads.begin(), scope = context()
    plan.value = null; taskStatus.value = ''; error.value = ''; notice.value = ''
    if (!available()) { if (!disposed) error.value = '当前学院或学期暂不可读取该导出任务'; return }
    if (!validAgentId(scope.taskId)) { error.value = '导出任务编号无效，请从助手重新打开'; return }
    loading.value = true
    try {
      const result = await assistantReportsApi.read(scope.taskId)
      if (!ticket.isCurrent()) return
      if (!result || typeof result !== 'object') throw new Error('导出任务读取不完整')
      const row = result as Record<string, unknown>
      if (row.task_id !== scope.taskId || typeof row.status !== 'string'
        || !['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED'].includes(row.status)) throw new Error('导出任务读取不完整')
      taskStatus.value = row.status
      if (row.status === 'SUCCEEDED') {
        const payload = row.result as { status?: unknown; data?: unknown } | null
        if (payload?.status !== 'SUCCEEDED') throw new Error('导出任务没有有效结果')
        plan.value = parseReportAction(payload.data, scope.collegeId, scope.semesterId)
      }
    } catch (cause) { if (ticket.isCurrent()) { plan.value = null; error.value = message(cause) } }
    finally { if (ticket.isLatest()) loading.value = false }
  }
  async function download() {
    if (!available() || !plan.value || loading.value || downloading.value || error.value) return
    const ticket = downloads.begin(), prepared = plan.value
    downloading.value = true; notice.value = ''; error.value = ''
    try {
      const file = await assistantReportsApi.download(prepared)
      if (!ticket.isCurrent()) return
      saveFile(file)
      notice.value = '已发起文件下载，请核对下载文件'
    } catch (cause) {
      if (ticket.isCurrent()) { plan.value = null; error.value = `${message(cause)}；请刷新任务后重新核对` }
    } finally { if (ticket.isLatest()) downloading.value = false }
  }
  watch(key, () => {
    reads.invalidate(); downloads.invalidate()
    plan.value = null; taskStatus.value = ''; loading.value = false; downloading.value = false
    error.value = ''; notice.value = ''; void refresh()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { disposed = true; reads.invalidate(); downloads.invalidate() })
  return { plan, taskStatus, loading, downloading, error, notice, refresh, download }
}
