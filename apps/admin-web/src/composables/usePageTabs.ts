import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export function usePageTabs(allowed: () => string[]) {
  const route = useRoute(), router = useRouter()
  const tab = computed({
    get: () => allowed().includes(String(route.query.tab || '')) ? String(route.query.tab) : allowed()[0] || '',
    set: value => { void router.replace({ query: { ...route.query, tab: String(value) } }) }
  })
  watch(() => `${route.path}:${String(route.query.tab || '')}:${allowed().join(',')}`, () => {
    if (allowed().length && !allowed().includes(String(route.query.tab || ''))) {
      void router.replace({ query: { ...route.query, tab: allowed()[0] } })
    }
  }, { immediate: true })
  return tab
}
