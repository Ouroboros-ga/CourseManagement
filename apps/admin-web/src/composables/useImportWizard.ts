import { computed, onUnmounted, ref, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { uploadImportFile, previewImportSet, confirmImportSet, type ImportPreviewResult, type ImportSetPlan, type ImportSetResult } from '../api/importer'

export function useImportWizard() {
  const session = useSessionStore()
  const target = ref('admin_roster'), teachingClassId = ref('')
  const files = ref<File[]>([]), drafts = ref<Array<ImportPreviewResult & { filename: string }>>([])
  const selectedIds = ref<string[]>([]), plan = ref<ImportSetPlan | null>(null), result = ref<ImportSetResult | null>(null)
  const busy = ref(false), error = ref(''), uploadErrors = ref<string[]>([])
  let generation = 0, active = true
  const context = () => JSON.stringify([session.currentUser?.id, session.workspaceCollegeId,
    session.currentSemesterId, session.workspace?.authorization_revision, target.value, teachingClassId.value])
  const selection = () => JSON.stringify(selectedIds.value)
  const canUpload = computed(() => !!target.value && !!files.value.length && files.value.length <= 20 && !!session.workspaceCollegeId
    && (['admin_roster', 'class_duty'].includes(target.value) || !!session.currentSemesterId)
    && (target.value !== 'roster' || !!teachingClassId.value))
  watch(context, () => {
    generation++; plan.value = null; result.value = null; drafts.value = []; selectedIds.value = []
    files.value = []; error.value = ''; uploadErrors.value = []; busy.value = false
  })
  watch(selection, () => { generation++; plan.value = null; result.value = null; busy.value = false }, { flush: 'sync' })
  watch(files, () => { generation++; plan.value = null; result.value = null; drafts.value = []; selectedIds.value = []; uploadErrors.value = []; error.value = ''; busy.value = false }, { flush: 'sync' })
  onUnmounted(() => { active = false; generation++ })
  function ticket() {
    const captured = context(), selected = selection(), revision = ++generation
    const check = () => active && revision === generation && captured === context() && selected === selection()
    check.isLatest = () => !active || revision === generation
    return check
  }
  async function upload() {
    if (!canUpload.value || busy.value) return
    selectedIds.value = []; drafts.value = []; plan.value = null; result.value = null
    const current = ticket(), pendingFiles = [...files.value], found: typeof drafts.value = []
    busy.value = true; error.value = ''; uploadErrors.value = []
    try {
      for (const file of pendingFiles) {
        if (!current()) return
        if (file.size > 10 * 1024 * 1024) { uploadErrors.value.push(`${file.name}：超过 10 MiB`); continue }
        try {
          const draft = await uploadImportFile(target.value, file, {
            semester_id: ['admin_roster', 'class_duty'].includes(target.value) ? undefined : session.currentSemesterId,
            teaching_class_id: target.value === 'roster' ? teachingClassId.value : undefined,
            replace: false
          })
          if (!current()) return
          found.push({ ...draft, filename: file.name })
          drafts.value = [...found]
        } catch (e) {
          if (current()) uploadErrors.value.push(`${file.name}：${e instanceof Error ? e.message : '解析失败'}`)
        }
      }
      if (current()) { busy.value = false; selectedIds.value = found.map(row => row.id) }
    } finally { if (current.isLatest()) busy.value = false }
  }
  async function review() {
    if (busy.value || !selectedIds.value.length) return
    const current = ticket()
    busy.value = true; error.value = ''; plan.value = null
    try {
      const response = await previewImportSet(session.workspaceCollegeId, [...selectedIds.value])
      if (current()) plan.value = response
    } catch (e) { if (current()) error.value = e instanceof Error ? e.message : '核对失败' }
    finally { if (current.isLatest()) busy.value = false }
  }
  async function confirm() {
    if (!plan.value?.can_confirm || busy.value || result.value) return
    const reviewed = plan.value, current = ticket()
    busy.value = true; error.value = ''
    try {
      const response = await confirmImportSet(session.workspaceCollegeId, [...reviewed.batch_ids], reviewed.revision)
      if (current()) result.value = response
    } catch (e) {
      if (current()) {
        error.value = e instanceof Error ? e.message : '未收到确认结果，可重试同一集合，不会重复写入'
        if (e && typeof e === 'object' && 'status' in e && e.status === 409) plan.value = null
      }
    } finally { if (current.isLatest()) busy.value = false }
  }
  return { target, teachingClassId, files, drafts, selectedIds, plan, result, busy, error, uploadErrors, canUpload, upload, review, confirm }
}
