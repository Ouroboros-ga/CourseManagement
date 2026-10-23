import { ref, watch, onUnmounted } from 'vue'
import { listChangeRequests, type ChangeRequestItem, type ChangeRequestStatus } from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { ContextEpoch } from '../utils/contextEpoch'

export function useChangeRequests() {
  const session = useSessionStore()
  const rows = ref<ChangeRequestItem[]>([])
  const status = ref<ChangeRequestStatus | ''>('PENDING')
  const page = ref(1), total = ref(0), loading = ref(false), error = ref('')
  const epoch = new ContextEpoch(() => JSON.stringify([session.currentUser?.id,
    session.workspaceCollegeId, session.currentSemesterId, session.workspace?.authorization_revision,
    status.value, page.value]))
  onUnmounted(() => epoch.invalidate())
  async function reload() {
    const ticket = epoch.begin()
    rows.value = []; total.value = 0; error.value = ''
    if (!session.currentSemesterId) { loading.value = false; return }
    loading.value = true
    try {
      const result = await listChangeRequests({ semester_id: session.currentSemesterId,
        status: status.value || undefined, page: page.value })
      if (!ticket.isCurrent()) return
      total.value = result.total
      if (page.value > 1 && !result.items.length && result.total <= (page.value - 1) * 50) {
        page.value = Math.max(1, Math.ceil(result.total / 50)); return
      }
      rows.value = result.items
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '申请读取失败，请重试'
    } finally { if (ticket.isLatest()) loading.value = false }
  }
  watch(() => [session.currentUser?.id, session.workspaceCollegeId, session.currentSemesterId,
    session.workspace?.authorization_revision, status.value], () => {
    epoch.invalidate()
    if (page.value !== 1) page.value = 1
    else void reload()
  }, { immediate: true })
  watch(page, () => void reload())
  return { rows, status, page, total, loading, error, reload }
}
