import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { uploadImportFile, previewImportArchive, previewImportSet, confirmImportSet, type ImportPreviewResult, type ImportSetPlan, type ImportSetResult } from '../api/importer'

export function useImportWizard() {
  const session = useSessionStore()
  const target = ref('admin_roster'), teachingClassId = ref(''), courseTypeId = ref('')
  const files = ref<File[]>([]), drafts = ref<Array<ImportPreviewResult & { filename: string }>>([])
  const selectedIds = ref<string[]>([]), plan = ref<ImportSetPlan | null>(null), result = ref<ImportSetResult | null>(null)
  const busy = ref(false), error = ref(''), uploadErrors = ref<string[]>([])
  const failuresExcluded = ref(false)
  const canConfirm = computed(() => !!plan.value?.can_confirm && !busy.value && !result.value
    && (!uploadErrors.value.length || failuresExcluded.value))
  let generation = 0, active = true
  const scopeContext = () => JSON.stringify([session.currentUser?.id, session.workspaceCollegeId,
    session.currentSemesterId, session.workspace?.authorization_revision])
  const context = () => JSON.stringify([scopeContext(), target.value, teachingClassId.value, courseTypeId.value])
  let previousScope = scopeContext()
  const selection = () => JSON.stringify(selectedIds.value)
  const canUpload = computed(() => !!target.value && !!files.value.length && files.value.length <= 20 && !!session.workspaceCollegeId
    && (['admin_roster', 'class_duty'].includes(target.value) || !!session.currentSemesterId)
    && (target.value !== 'roster' || !!teachingClassId.value))
  watch(context, () => {
    generation++; plan.value = null; result.value = null; drafts.value = []; selectedIds.value = []
    if (scopeContext() !== previousScope) files.value = []
    previousScope = scopeContext()
    error.value = ''; uploadErrors.value = []; failuresExcluded.value = false; busy.value = false
  })
  watch(selection, () => { generation++; plan.value = null; result.value = null; busy.value = false }, { flush: 'sync' })
  watch(files, () => { generation++; plan.value = null; result.value = null; drafts.value = []; selectedIds.value = []; uploadErrors.value = []; failuresExcluded.value = false; error.value = ''; busy.value = false }, { flush: 'sync' })
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
    busy.value = true; error.value = ''; uploadErrors.value = []; failuresExcluded.value = false
    try {
      for (const file of pendingFiles) {
        if (!current()) return
        if (file.size > 10 * 1024 * 1024) { uploadErrors.value.push(`${file.name}：超过 10 MiB`); continue }
        try {
          const options = {
            semester_id: ['admin_roster', 'class_duty'].includes(target.value) ? undefined : session.currentSemesterId,
            teaching_class_id: target.value === 'roster' ? teachingClassId.value : undefined,
            course_type_id: courseTypeId.value || undefined,
            replace: false
          }
          if (/\.zip$/i.test(file.name)) {
            const archive = await previewImportArchive(session.workspaceCollegeId, target.value, file, options)
            if (!current()) return
            found.push(...archive.files)
            uploadErrors.value.push(...archive.errors.map(item => `${file.name} / ${item.filename}：${item.message}`))
          } else {
            const draft = await uploadImportFile(target.value, file, options)
            if (!current()) return
            found.push({ ...draft, filename: file.webkitRelativePath || file.name })
          }
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
    if (selectedIds.value.length > 20) { error.value = '本次展开后超过 20 个表格，请移除部分文件后核对；尚未保存正式数据。'; return }
    const current = ticket()
    busy.value = true; error.value = ''; plan.value = null
    try {
      const response = await previewImportSet(session.workspaceCollegeId, [...selectedIds.value])
      if (current()) plan.value = response
    } catch (e) { if (current()) error.value = e instanceof Error ? e.message : '核对失败' }
    finally { if (current.isLatest()) busy.value = false }
  }
  async function confirm() {
    if (!canConfirm.value || !plan.value) return
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
  function removeDraft(id: string) {
    drafts.value = drafts.value.filter(row => row.id !== id)
    selectedIds.value = selectedIds.value.filter(row => row !== id)
    if (!drafts.value.length) { files.value = []; plan.value = null; result.value = null }
  }
  function excludeUploadFailures() { failuresExcluded.value = true }
  function reset() { files.value = []; selectedIds.value = []; drafts.value = []; plan.value = null; result.value = null; error.value = ''; uploadErrors.value = []; failuresExcluded.value = false }
  async function resume(draft: ImportPreviewResult & { filename: string }) {
    reset()
    target.value = draft.target
    teachingClassId.value = draft.teaching_class_id || ''
    await nextTick()
    drafts.value = [draft]; selectedIds.value = [draft.id]
    await review()
  }
  return { target, teachingClassId, courseTypeId, files, drafts, selectedIds, plan, result, busy, error, uploadErrors, failuresExcluded, canConfirm, canUpload, upload, review, confirm, removeDraft, excludeUploadFailures, reset, resume }
}
