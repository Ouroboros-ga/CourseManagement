import { computed, onUnmounted, shallowRef, watch } from 'vue'
import {
  groupSamplingApi,
  type AdministrativeClassOption,
  type GroupSampleAssignmentResult,
  type GroupSampleBody,
  type GroupSampleGenerateResult,
  type GroupSamplePreview,
  type GroupSamplingApi
} from '../api/groupSampling'

export interface GroupSamplingContext {
  collegeId: () => string
  groupId: () => string
  semesterId: () => string
  canGenerate: () => boolean
  canAssign: () => boolean
}

export interface SamplingForm {
  date_from: string
  date_to: string
  selectedClassIds: string[]
  counts: Record<string, number>
  require_photo: boolean
}

const initialForm = (): SamplingForm => ({ date_from: '', date_to: '', selectedClassIds: [], counts: {}, require_photo: true })
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const errorMessage = (error: unknown) => typeof error === 'object' && error !== null && 'message' in error && typeof error.message === 'string' ? error.message : '抽查操作失败'
const isConflict = (error: unknown) => typeof error === 'object' && error !== null && 'status' in error && (error as { status?: unknown }).status === 409
const stableFormKey = (form: SamplingForm) => JSON.stringify({
  date_from: form.date_from,
  date_to: form.date_to,
  selectedClassIds: [...form.selectedClassIds].sort(),
  counts: Object.fromEntries(Object.entries(form.counts).sort(([a], [b]) => a.localeCompare(b))),
  require_photo: form.require_photo
})
function dateSpanValid(from: string, to: string) {
  const start = Date.parse(from), end = Date.parse(to)
  const days = (end - start) / 86_400_000
  return Number.isFinite(days) && days >= 0 && days < 31
}

export function useGroupSampling(context: GroupSamplingContext, api: GroupSamplingApi = groupSamplingApi, makeDrawId: () => string = () => globalThis.crypto.randomUUID()) {
  const classes = shallowRef<AdministrativeClassOption[]>([])
  const form = shallowRef<SamplingForm>(initialForm())
  const previewResult = shallowRef<GroupSamplePreview | null>(null)
  const previewBody = shallowRef<GroupSampleBody | null>(null)
  const generatedBody = shallowRef<GroupSampleBody | null>(null)
  const generateResult = shallowRef<GroupSampleGenerateResult | null>(null)
  const assignmentResult = shallowRef<GroupSampleAssignmentResult | null>(null)
  const assignmentPlan = shallowRef<import('../api/groupSampling').AssignmentPlan | null>(null)
  const confirmedWarnings = shallowRef<string[]>([])
  const canConfirmAssignment = computed(() => !!assignmentPlan.value && assignmentPlan.value.assigned.every(
    item => !item.warning_codes.length || confirmedWarnings.value.includes(item.task_id)
  ))
  const error = shallowRef('')
  const message = shallowRef('')
  const classLoading = shallowRef(false)
  const previewing = shallowRef(false)
  const writing = shallowRef(false)
  const busy = computed(() => classLoading.value || previewing.value || writing.value)
  const totalRequested = computed(() => form.value.selectedClassIds.reduce((sum, id) => sum + (form.value.counts[id] || 0), 0))
  const canPreview = computed(() => Boolean(
    context.canGenerate() && context.collegeId() && context.groupId() && context.semesterId() &&
    form.value.date_from && form.value.date_to && dateSpanValid(form.value.date_from, form.value.date_to) &&
    form.value.selectedClassIds.length > 0 && form.value.selectedClassIds.length <= 100 && form.value.selectedClassIds.every(id => {
      const count = form.value.counts[id]
      return Number.isInteger(count) && count >= 1 && count <= 50
    }) && totalRequested.value <= 500
  ))

  let contextEpoch = 0
  let classEpoch = 0
  let previewEpoch = 0
  let disposed = false
  const contextKey = () => [context.collegeId(), context.groupId(), context.semesterId(), context.canGenerate() ? 'generate' : 'read', context.canAssign() ? 'assign' : 'no-assign'].join(':')

  function clearFlow() {
    form.value = initialForm()
    previewResult.value = null; previewBody.value = null
    generatedBody.value = null; generateResult.value = null; assignmentResult.value = null
    assignmentPlan.value = null; confirmedWarnings.value = []
    error.value = ''; message.value = ''; classLoading.value = false; previewing.value = false; writing.value = false
  }

  watch(contextKey, () => {
    contextEpoch++; classEpoch++; previewEpoch++
    classes.value = []
    clearFlow()
    if (context.collegeId() && context.groupId() && context.semesterId() && context.canGenerate()) void loadClasses()
  }, { immediate: true, flush: 'sync' })

  watch(() => stableFormKey(form.value), () => {
    previewEpoch++
    previewResult.value = null; previewBody.value = null
    error.value = ''; message.value = ''
  }, { flush: 'sync' })

  onUnmounted(() => { disposed = true; contextEpoch++; classEpoch++; previewEpoch++ })

  async function loadClasses() {
    const cid = context.collegeId(), gid = context.groupId(), sid = context.semesterId()
    if (!cid || !gid || !sid || !context.canGenerate()) { classes.value = []; return }
    const ticket = ++classEpoch, contextTicket = contextEpoch, key = contextKey()
    classLoading.value = true; error.value = ''
    try {
      const result: AdministrativeClassOption[] = []
      let page = 1, total = Number.POSITIVE_INFINITY
      while (result.length < total) {
        const response = await api.listClassPage(cid, 100, page)
        if (ticket !== classEpoch || contextTicket !== contextEpoch || key !== contextKey() || disposed) return
        result.push(...response.items)
        total = response.total
        if (!response.items.length || page * 100 >= total) break
        page++
      }
      if (ticket === classEpoch && contextTicket === contextEpoch && key === contextKey() && !disposed) classes.value = result
    } catch (caught) {
      if (ticket === classEpoch && contextTicket === contextEpoch && key === contextKey() && !disposed) error.value = errorMessage(caught)
    } finally {
      if (disposed || ticket === classEpoch) classLoading.value = false
    }
  }

  function toggleClass(id: string, selected: boolean) {
    if (!context.canGenerate() || writing.value || generateResult.value) return
    const current = new Set(form.value.selectedClassIds)
    const counts = { ...form.value.counts }
    if (selected) {
      current.add(id)
      if (!counts[id]) counts[id] = 1
    } else {
      current.delete(id)
      delete counts[id]
    }
    form.value = { ...form.value, selectedClassIds: [...current], counts }
  }

  function setCount(id: string, value: number) {
    if (!context.canGenerate() || writing.value || generateResult.value || !form.value.selectedClassIds.includes(id)) return
    form.value = { ...form.value, counts: { ...form.value.counts, [id]: value } }
  }

  function setDateRange(dateFrom: string, dateTo: string) {
    if (!context.canGenerate() || writing.value || generateResult.value) return
    form.value = { ...form.value, date_from: dateFrom, date_to: dateTo }
  }

  function setRequirePhoto(value: boolean) {
    if (!context.canGenerate() || writing.value || generateResult.value) return
    form.value = { ...form.value, require_photo: value }
  }

  async function preview() {
    const cid = context.collegeId(), gid = context.groupId(), sid = context.semesterId()
    if (!canPreview.value || !cid || !gid || !sid || writing.value || generateResult.value) return
    const ticket = ++previewEpoch, contextTicket = contextEpoch, key = contextKey()
    const body: GroupSampleBody = clone({
      semester_id: sid,
      date_from: form.value.date_from,
      date_to: form.value.date_to,
      counts: Object.fromEntries(form.value.selectedClassIds.map(id => [id, form.value.counts[id]])),
      draw_id: makeDrawId(),
      require_photo: form.value.require_photo
    })
    const formKey = stableFormKey(form.value)
    previewResult.value = null; previewBody.value = null; error.value = ''; message.value = ''; previewing.value = true
    try {
      const response = await api.preview(cid, gid, clone(body))
      if (ticket === previewEpoch && contextTicket === contextEpoch && key === contextKey() && formKey === stableFormKey(form.value) && !disposed) {
        previewBody.value = body
        previewResult.value = clone(response)
      }
    } catch (caught) {
      if (ticket === previewEpoch && contextTicket === contextEpoch && key === contextKey() && formKey === stableFormKey(form.value) && !disposed) error.value = errorMessage(caught)
    } finally {
      if (disposed || ticket === previewEpoch) previewing.value = false
    }
  }

  async function generate() {
    const snapshot = previewBody.value, preview = previewResult.value
    const cid = context.collegeId(), gid = context.groupId(), key = contextKey()
    if (!snapshot || !preview || !context.canGenerate() || !cid || !gid || writing.value || generateResult.value) return
    if (snapshot.semester_id !== context.semesterId()) return
    const ticket = contextEpoch, body = clone(snapshot), revision = preview.selection_revision
    writing.value = true; error.value = ''; message.value = ''
    try {
      const response = await api.generate(cid, gid, { ...clone(body), selection_revision: revision })
      if (ticket !== contextEpoch || key !== contextKey() || disposed) return
      generatedBody.value = body
      generateResult.value = clone({ ...response, assignable_task_ids: [...response.assignable_task_ids] })
      assignmentResult.value = null
      message.value = `生成确认完成：新增 ${response.created} 项，已有 ${response.existed} 项。`
    } catch (caught) {
      if (ticket === contextEpoch && key === contextKey() && !disposed) {
        if (isConflict(caught)) {
          previewResult.value = null; previewBody.value = null; previewEpoch++
          error.value = '抽查范围或数据已变化，请重新预览后确认生成'
        } else error.value = errorMessage(caught)
      }
    } finally { if (disposed || ticket === contextEpoch) writing.value = false }
  }

  async function assign() {
    const generated = generateResult.value
    const cid = context.collegeId(), gid = context.groupId(), sid = context.semesterId(), key = contextKey()
    if (!generated || !generated.assignable_task_ids.length || !context.canAssign() || !cid || !gid || !sid || writing.value) return
    const ticket = contextEpoch
    const taskIds = [...generated.assignable_task_ids]
    writing.value = true; error.value = ''; message.value = ''
    try {
      const response = await api.previewAssignment(cid, gid, { semester_id: sid, task_ids: taskIds })
      if (ticket !== contextEpoch || key !== contextKey() || disposed) return
      assignmentPlan.value = clone(response)
      confirmedWarnings.value = []
      message.value = '请核对具体人员与警告后确认派发；当前尚未写入排班。'
    } catch (caught) {
      if (ticket === contextEpoch && key === contextKey() && !disposed) error.value = errorMessage(caught)
    } finally { if (disposed || ticket === contextEpoch) writing.value = false }
  }

  async function confirmAssignment() {
    const plan = assignmentPlan.value
    const cid = context.collegeId(), gid = context.groupId(), key = contextKey(), ticket = contextEpoch
    if (!plan || !canConfirmAssignment.value || !context.canAssign() || writing.value) return
    writing.value = true; error.value = ''
    try {
      const result = await api.commitAssignment(cid, gid, plan.id, { revision: plan.revision,
        confirmations: plan.assigned.filter(item => item.warning_codes.length) })
      if (ticket !== contextEpoch || key !== contextKey() || disposed) return
      assignmentResult.value = clone(result); assignmentPlan.value = null
      message.value = `排班处理完成：已排 ${result.assigned_count} 项，未排 ${result.unassigned_count} 项。`
    } catch (caught) {
      if (ticket === contextEpoch && key === contextKey() && !disposed) {
        error.value = errorMessage(caught)
        if (isConflict(caught)) { assignmentPlan.value = null; confirmedWarnings.value = [] }
      }
    } finally { if (disposed || ticket === contextEpoch) writing.value = false }
  }

  const activeClasses = computed(() => classes.value.filter(item => item.status === 'ACTIVE'))
  return {
    classes, activeClasses, form, previewResult, previewBody, generatedBody, generateResult,
    assignmentResult, assignmentPlan, confirmedWarnings, canConfirmAssignment, confirmAssignment,
    error, message, classLoading, previewing, writing, busy, totalRequested,
    canPreview, loadClasses, toggleClass, setCount, setDateRange, setRequirePhoto, preview, generate, assign
  }
}
