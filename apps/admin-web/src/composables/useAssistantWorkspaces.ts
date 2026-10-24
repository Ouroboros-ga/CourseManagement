import { computed, shallowRef, watch, onScopeDispose } from 'vue'
import { assistantWorkspacesApi as api, parseWorkspace, type ImportWorkspace, type WorkspaceScope } from '../api/assistantWorkspaces'
import { validAgentId } from '../api/assistantReports'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context extends WorkspaceScope { key: string; active: boolean; available: boolean }
const pointer = 'management-assistant-imports'
export function useAssistantWorkspaces(context: () => Context, options: { storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> } = {}) {
  const sources = shallowRef<ImportWorkspace[]>([]), busy = shallowRef(false), error = shallowRef(''), notice = shallowRef(''), pendingKey = shallowRef('')
  let ids: string[] = [], file: File | null = null, disposed = false, polls = 0, timer: ReturnType<typeof setTimeout> | undefined
  let storage = options.storage
  try { storage ??= typeof window !== 'undefined' ? window.sessionStorage : undefined } catch { /* Optional recovery. */ }
  const key = () => JSON.stringify([context().key, context().collegeId, context().semesterId, context().available])
  const epoch = new ContextEpoch(key), scope = () => ({ collegeId: context().collegeId, semesterId: context().semesterId })
  const available = () => !disposed && context().available && validAgentId(context().collegeId) && validAgentId(context().semesterId)
  const retryPending = computed(() => !!pendingKey.value)
  function stop() { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  function remember() { try { storage?.setItem(pointer, JSON.stringify({ key: context().key, ...scope(), ids, pendingKey: pendingKey.value })) } catch { /* No bytes or file names are stored. */ } }
  function forget() { try { storage?.removeItem(pointer) } catch { /* Optional recovery. */ } }
  function clear() { epoch.invalidate(); stop(); ids = []; file = null; sources.value = []; pendingKey.value = ''; busy.value = false; error.value = ''; notice.value = ''; polls = 0 }
  function apply(row: ImportWorkspace) { if (!ids.includes(row.workspace_id)) ids = [...ids, row.workspace_id].slice(-20); sources.value = [...sources.value.filter(s => s.workspace_id !== row.workspace_id), row]; remember() }
  function failed(cause: unknown) {
    error.value = cause instanceof Error ? cause.message : '资料暂时无法读取，请刷新核对'
    const problem = cause as { status?: number; code?: string }
    if ([401, 403].includes(Number(problem?.status)) || (Number(problem?.status) === 409 && problem?.code !== 'IDEMPOTENCY_KEY_REUSED')) { ids = []; sources.value = []; pendingKey.value = ''; file = null; forget() }
  }
  function schedule() {
    stop()
    if (available() && context().active && !error.value && polls < 450 && sources.value.some(s => ['QUEUED', 'PROCESSING', 'PREVIEW_QUEUED', 'PREVIEW_PROCESSING'].includes(s.state))) timer = setTimeout(() => { polls++; void refresh(false) }, 2000)
  }
  async function refresh(manual = true) {
    if (!available() || busy.value) return
    if (manual) polls = 0
    const ticket = epoch.begin(), current = scope(); stop(); busy.value = true; error.value = ''; notice.value = ''
    try {
      let recoveredId = ''
      if (pendingKey.value) {
        try {
          const result = parseWorkspace(await api.lookup(pendingKey.value, current), current)
          if (!ticket.isCurrent()) return
          apply(result); recoveredId = result.workspace_id; pendingKey.value = ''; file = null; remember()
        } catch (cause) { if (Number((cause as { status?: number })?.status) !== 404) throw cause; if (ticket.isCurrent()) error.value = '上次上传回执待确认，请重新选择原文件核对' }
      }
      for (const id of [...ids]) {
        if (id === recoveredId) continue
        try {
          const result = parseWorkspace(await api.read(id, current), current, id)
          if (!ticket.isCurrent()) return
          apply(result)
        } catch (cause) {
          if (!ticket.isCurrent()) return
          if (![404, 410].includes(Number((cause as { status?: number })?.status))) throw cause
          ids = ids.filter(value => value !== id); sources.value = sources.value.filter(value => value.workspace_id !== id)
          notice.value = '部分资料已过期或不可用，其余资料仍可继续核对。'; remember()
        }
      }
    } catch (cause) { if (ticket.isCurrent()) { sources.value = []; failed(cause) } }
    finally { if (ticket.isLatest()) { busy.value = false; schedule() } }
  }
  async function upload(chosen: File) {
    if (!available() || busy.value) return
    file = chosen; pendingKey.value ||= crypto.randomUUID(); remember()
    const ticket = epoch.begin(), current = scope(), requestKey = pendingKey.value
    busy.value = true; error.value = ''; stop(); polls = 0
    try {
      const result = parseWorkspace(await api.upload(chosen, current, requestKey), current)
      if (!ticket.isCurrent()) return
      apply(result); file = null; pendingKey.value = ''; remember()
    } catch (cause) { if (ticket.isCurrent()) failed(cause) }
    finally { if (ticket.isLatest()) { busy.value = false; schedule() } }
  }
  async function retryUpload() { if (file) await upload(file); else await refresh() }
  async function cancel(id: string) {
    if (!available() || busy.value || !ids.includes(id)) return
    const ticket = epoch.begin(), current = scope(); busy.value = true; error.value = ''; stop()
    try { const row = parseWorkspace(await api.cancel(id, current), current, id); if (ticket.isCurrent()) apply(row) }
    catch (cause) { if (ticket.isCurrent()) failed(cause) }
    finally { if (ticket.isLatest()) { busy.value = false; schedule() } }
  }
  watch(key, (_next, previous) => {
    clear()
    if (previous !== undefined || !available()) { forget(); return }
    try {
      const saved = JSON.parse(storage?.getItem(pointer) || 'null')
      if (saved?.key === context().key && saved.collegeId === context().collegeId && saved.semesterId === context().semesterId && Array.isArray(saved.ids) && saved.ids.length <= 20 && saved.ids.every(validAgentId) && typeof saved.pendingKey === 'string' && (!saved.pendingKey || /^[A-Za-z0-9_-]{1,64}$/.test(saved.pendingKey))) { ids = saved.ids; pendingKey.value = saved.pendingKey }
      else forget()
    } catch { forget() }
    if (context().active) void refresh()
  }, { immediate: true, flush: 'sync' })
  watch(() => context().active, active => { stop(); if (active) void refresh() }, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; epoch.invalidate(); stop(); file = null })
  return { sources, busy, error, notice, retryPending, upload, retryUpload, refresh, cancel }
}
