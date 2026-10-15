import { onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

let confirmEdits: () => boolean = () => true
let clearEdits: (element: Element) => void = () => {}
export function confirmWorkspaceChange() { return confirmEdits() }
export function markWorkspaceSaved(element: Element | null) { if (element) clearEdits(element) }

/** 只关注编辑表单和对话框中的用户输入，不将列表筛选视作待保存业务。 */
export function useWorkspaceChanges() {
  const changed = new Set<Element>()
  const discard = () => {
    const visible = [...changed].some(node => node.isConnected && node.getClientRects().length > 0)
    if (visible && !window.confirm('当前有尚未保存的输入，切换将放弃这些内容。是否继续？')) return false
    changed.clear()
    return true
  }
  function track(event: Event) {
    const target = event.target
    if (!(target instanceof Element)) return
    const form = target.closest('[data-unsaved-form], [role="dialog"], .el-dialog')
    if (form) changed.add(form)
  }
  const beforeUnload = (event: BeforeUnloadEvent) => {
    if ([...changed].some(node => node.isConnected && node.getClientRects().length > 0)) {
      event.preventDefault()
      event.returnValue = ''
    }
  }
  onMounted(() => {
    confirmEdits = discard
    clearEdits = element => changed.delete(element)
    document.addEventListener('input', track)
    document.addEventListener('change', track)
    window.addEventListener('beforeunload', beforeUnload)
  })
  onUnmounted(() => {
    confirmEdits = () => true
    clearEdits = () => {}
    document.removeEventListener('input', track)
    document.removeEventListener('change', track)
    window.removeEventListener('beforeunload', beforeUnload)
  })
  onBeforeRouteLeave(() => discard())
}
