import { ref, computed, watch, type WritableComputedRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export function usePageTabs(allowed: () => string[]): WritableComputedRef<string> {
  const route = useRoute(), router = useRouter()

  const resolveTarget = (queryVal?: string) => {
    const list = allowed()
    const target = queryVal !== undefined ? queryVal : String(route.query.tab || '')
    if (list.includes(target)) return target
    return list[0] || ''
  }

  const current = ref<string>(resolveTarget())

  watch(
    () => [route.path, String(route.query.tab || ''), allowed().join(',')] as const,
    ([, queryTab]) => {
      const list = allowed()
      if (list.length === 0) return
      const target = resolveTarget(queryTab)
      if (current.value !== target) {
        current.value = target
      }
      if (!list.includes(queryTab) && target) {
        void router.replace({ query: { ...route.query, tab: target } }).catch(() => {})
      }
    },
    { immediate: true }
  )

  const tab = computed<string>({
    get: () => current.value,
    set: (value: string) => {
      const strVal = String(value)
      const list = allowed()
      if (list.includes(strVal)) {
        current.value = strVal
        if (route.query.tab !== strVal) {
          void router.replace({ query: { ...route.query, tab: strVal } }).catch(() => {})
        }
      }
    }
  })

  return tab
}
