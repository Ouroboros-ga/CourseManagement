import { computed, ref, watch } from 'vue'

/** Render a bounded snapshot/preview in pages; this does not replace API pagination. */
export function useDisplayPage<T>(source: () => readonly T[]) {
  const page = ref(1)
  const total = computed(() => source().length)
  const rows = computed(() => source().slice((page.value - 1) * 50, page.value * 50))
  watch(source, () => { page.value = 1 })
  watch(total, count => { page.value = Math.min(page.value, Math.max(1, Math.ceil(count / 50))) })
  return { page, total, rows }
}
