import { onUnmounted, shallowRef, watch } from 'vue'

/** 上下文变化立即清空数据；只允许最后一次且仍属于原上下文的响应回写。 */
export function useWorkspaceRead<T>(key: () => string, enabled: () => boolean, fetcher: () => Promise<T>) {
  const data = shallowRef<T | null>(null)
  const busy = shallowRef(false)
  const error = shallowRef('')
  let revision = 0, active = true
  async function load() {
    const ticket = ++revision, captured = key()
    const current = () => active && ticket === revision && captured === key()
    data.value = null; error.value = ''; busy.value = false
    if (!active || !enabled()) return
    busy.value = true
    try {
      const result = await fetcher()
      if (current()) data.value = result
    } catch (e) {
      if (current()) error.value = e instanceof Error ? e.message : '加载失败'
    } finally { if (!active || ticket === revision) busy.value = false }
  }
  watch([key, enabled], () => { void load() }, { immediate: true })
  onUnmounted(() => { active = false; revision++ })
  return { data, busy, error, load }
}
