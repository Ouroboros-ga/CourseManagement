import { computed, onUnmounted, ref, watch } from 'vue'
import { confirmPersonLinks, previewPersonLinks, type PersonLinkKind, type PersonLinkPlan } from '../api/importer'

export function usePersonLinks(context: () => { cid: string; kind: PersonLinkKind; semester: string; identity: string }) {
  const plan = ref<PersonLinkPlan | null>(null), busy = ref(false), error = ref(''), saved = ref('')
  let generation = 0
  const key = () => JSON.stringify(context())
  watch(key, () => { generation++; plan.value = null; busy.value = false; error.value = ''; saved.value = '' }, { flush: 'sync' })
  onUnmounted(() => { generation++ })
  const canConfirm = computed(() => !!plan.value && plan.value.summary.person_links_create > 0 && !busy.value)
  function capture() {
    const value = { ...context() }, version = ++generation, captured = key()
    return { value, current: () => version === generation && captured === key(),
      body: { kind: value.kind, ...(value.kind === 'teaching' ? { semester_id: value.semester } : {}) } }
  }
  async function preview() {
    if (busy.value || !context().cid || context().kind === 'teaching' && !context().semester) return
    const request = capture()
    busy.value = true; error.value = ''; saved.value = ''; plan.value = null
    try {
      const result = await previewPersonLinks(request.value.cid, request.body)
      if (request.current()) plan.value = result
    } catch (e) { if (request.current()) error.value = e instanceof Error ? e.message : '关联核对失败' }
    finally { if (request.current()) busy.value = false }
  }
  async function confirm() {
    if (!canConfirm.value || !plan.value) return false
    const request = capture(), revision = plan.value.revision
    busy.value = true; error.value = ''
    try {
      const result = await confirmPersonLinks(request.value.cid, { ...request.body, revision })
      if (!request.current()) return false
      saved.value = `已补充 ${result.person_links_created} 条关联；${result.person_links_pending} 条仍需处理。`
      plan.value = null
      return true
    } catch (e) {
      if (request.current()) { error.value = e instanceof Error ? e.message : '关联未保存，请重新核对'; plan.value = null }
      return false
    } finally { if (request.current()) busy.value = false }
  }
  return { plan, busy, error, saved, canConfirm, preview, confirm }
}
