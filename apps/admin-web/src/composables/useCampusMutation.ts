import { onUnmounted, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'
import { useSessionStore } from '../stores/session'

export function useCampusMutation(collegeId: () => string, changed: () => void) {
  const session = useSessionStore()
  const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${collegeId()}`)
  const saving = shallowRef(false)
  let active = true
  onUnmounted(() => { active = false; epoch.invalidate() })
  async function run(operation: (cid: string) => Promise<unknown>) {
    if (!active || saving.value || !session.currentUser) return false
    const cid = collegeId()
    const ticket = epoch.begin()
    saving.value = true
    try {
      await operation(cid)
      if (!ticket.isCurrent()) return false
      ElMessage.success('已保存')
      changed()
      return true
    } catch (e) {
      if (ticket.isCurrent()) ElMessage.error(e instanceof Error ? e.message : '保存失败')
      return false
    } finally { saving.value = false }
  }
  return { saving, run }
}
