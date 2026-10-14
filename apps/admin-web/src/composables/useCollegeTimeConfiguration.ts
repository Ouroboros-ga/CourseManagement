import { computed, onUnmounted, shallowRef, watch } from 'vue'
import {
  listCollegeTimeVersions, previewCollegeTime, publishCollegeTime,
  type CollegeTimeConfiguration, type CollegeTimePreview, type CollegeTimePublished, type CollegeTimeVersion
} from '../api/collegeTime'
import { useSessionStore } from '../stores/session'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'

const initialForm = (): CollegeTimeConfiguration => ({
  effective_from: '',
  periods: [{ period_no: 1, start_time: '08:00', end_time: '08:45' }],
  calendar: [],
  grid_slot_mapping: {},
  confirm_existing_tasks: false
})

const formKey = (form: CollegeTimeConfiguration) => JSON.stringify({
  effective_from: form.effective_from,
  periods: form.periods,
  calendar: form.calendar,
  grid_slot_mapping: form.grid_slot_mapping || {}
})
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export function useCollegeTimeConfiguration(collegeId: () => string) {
  const session = useSessionStore()
  const semesterId = shallowRef('')
  const form = shallowRef<CollegeTimeConfiguration>(initialForm())
  const previewResult = shallowRef<CollegeTimePreview | CollegeTimePublished | null>(null)
  const previewSnapshot = shallowRef<Omit<CollegeTimeConfiguration, 'confirm_existing_tasks'> | null>(null)
  const versions = shallowRef<CollegeTimeVersion[]>([])
  const error = shallowRef(''), message = shallowRef('')
  const loadingVersions = shallowRef(false), submitting = shallowRef(false)
  const busy = computed(() => loadingVersions.value || submitting.value)
  const context = computed(() => `${identityContext(session.currentUser)}:${collegeId()}:${semesterId.value}`)
  const versionEpoch = new ContextEpoch(() => context.value)
  const previewEpoch = new ContextEpoch(() => `${context.value}:${formKey(form.value)}`)
  const publishEpoch = new ContextEpoch(() => `${context.value}:${formKey(form.value)}`)

  watch(context, () => {
    versionEpoch.invalidate(); previewEpoch.invalidate(); publishEpoch.invalidate()
    versions.value = []; previewResult.value = null; previewSnapshot.value = null
    form.value = initialForm()
    loadingVersions.value = false; submitting.value = false
    error.value = ''; message.value = ''
    if (collegeId() && semesterId.value) void loadVersions()
  }, { flush: 'sync' })
  watch(() => formKey(form.value), () => {
    previewEpoch.invalidate(); publishEpoch.invalidate()
    previewResult.value = null; previewSnapshot.value = null
    submitting.value = false
    message.value = ''
  }, { flush: 'sync' })
  onUnmounted(() => {
    versionEpoch.invalidate(); previewEpoch.invalidate(); publishEpoch.invalidate()
  })

  async function loadVersions() {
    const cid = collegeId(), sid = semesterId.value
    if (!cid || !sid) { versions.value = []; return }
    const ticket = versionEpoch.begin()
    loadingVersions.value = true; error.value = ''
    try {
      const result = await listCollegeTimeVersions(cid, sid)
      if (ticket.isCurrent()) versions.value = result
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '读取作息版本失败'
    } finally {
      if (ticket.isCurrent()) loadingVersions.value = false
    }
  }

  async function preview() {
    const cid = collegeId(), sid = semesterId.value
    if (!cid || !sid || !form.value.effective_from || submitting.value) return
    const snapshot = clone(form.value)
    const ticket = previewEpoch.begin()
    previewResult.value = null; previewSnapshot.value = null
    error.value = ''; message.value = ''; submitting.value = true
    try {
      const result = await previewCollegeTime(cid, sid, snapshot)
      if (ticket.isCurrent()) {
        previewResult.value = result
        const { confirm_existing_tasks: _confirm, ...configuration } = snapshot
        previewSnapshot.value = configuration
      }
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '作息预览失败'
    } finally {
      if (ticket.isCurrent()) submitting.value = false
    }
  }

  async function publish() {
    const preview = previewResult.value, snapshot = previewSnapshot.value
    const cid = collegeId(), sid = semesterId.value
    if (!preview || !snapshot || !cid || !sid || submitting.value) return
    if (preview.retained_future_task_ids.length > 0 && !form.value.confirm_existing_tasks) {
      error.value = '未来已有任务将保留原作息快照，请勾选确认后发布'
      return
    }
    const currentFormKey = formKey(form.value)
    const ticket = publishEpoch.begin()
    const payload: CollegeTimeConfiguration = {
      ...clone(snapshot), confirm_existing_tasks: form.value.confirm_existing_tasks
    }
    submitting.value = true; error.value = ''; message.value = ''
    try {
      const result = await publishCollegeTime(cid, sid, payload, preview.revision)
      if (!ticket.isCurrent() || currentFormKey !== formKey(form.value)) return
      previewResult.value = null; previewSnapshot.value = null
      message.value = `已发布第 ${result.version} 版作息；未来已有任务保留原快照。`
      await loadVersions()
    } catch (e) {
      if (ticket.isCurrent()) {
        previewResult.value = null; previewSnapshot.value = null
        error.value = e instanceof Error ? e.message : '发布失败，请重新预览'
      }
    } finally {
      if (ticket.isCurrent()) submitting.value = false
    }
  }

  return { semesterId, form, previewResult, versions, busy, error, message, loadVersions, preview, publish }
}
