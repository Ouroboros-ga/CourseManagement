import { computed, onUnmounted, ref, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { inspectImportUpload, type ImportInspectedFile, type ImportSetResult, type ImportUploadSource } from '../api/importer'

interface Entry extends Omit<ImportInspectedFile, 'target'> {
  id: number; target: string; source: File; saved: boolean; excluded: boolean
}
const order = ['faculty_staff', 'admin_roster', 'class_responsibility', 'grid_timetable', 'timetable', 'teaching_assignment', 'roster', 'elective_course', 'volunteer']

/** 仅维护当前页面的文件队列；各类型仍由既有导入向导独立预览、提交。 */
export function useImportIntake() {
  const session = useSessionStore(), entries = ref<Entry[]>([])
  const receipts = ref<ImportSetResult['files']>([]), busy = ref(false), error = ref(''), revision = ref(0)
  let generation = 0, nextId = 0, active = true
  const context = () => JSON.stringify([session.currentUser?.id, session.workspaceCollegeId, session.currentSemesterId, session.workspace?.authorization_revision])
  function reset() { generation++; entries.value = []; receipts.value = []; busy.value = false; error.value = ''; revision.value++ }
  watch(context, reset, { flush: 'sync' })
  onUnmounted(() => { active = false; generation++ })
  const groups = computed(() => order.map(target => ({ target, entries: entries.value.filter(e => e.target === target && !e.excluded) })).filter(g => g.entries.length))
  async function addFiles(files: File[]) {
    if (busy.value || !session.workspaceCollegeId) return
    if (files.length > 20) { error.value = '每次最多添加 20 个文件或压缩包，请分批处理。'; return }
    const ticket = ++generation, captured = context()
    const current = () => active && ticket === generation && captured === context()
    busy.value = true; error.value = ''
    try {
      for (const source of files) {
        if (!current()) return
        const filename = source.webkitRelativePath || source.name
        let inspected: ImportInspectedFile[]
        try {
          if (source.size > 10 * 1024 * 1024) throw new Error('文件超过 10 MiB，请拆分')
          inspected = (await inspectImportUpload(session.workspaceCollegeId, source)).files
        } catch (e) {
          inspected = [{ filename, target: null, archive_member: null, blocked: true, message: e instanceof Error ? e.message : '读取失败，请重新添加' }]
        }
        if (!current()) return
        const retained = entries.value.filter(e => e.saved || e.source.name !== source.name || (e.source.webkitRelativePath || e.source.name) !== filename)
        if (retained.filter(e => !e.excluded && !e.saved).length + inspected.length > 20) {
          error.value = '展开后待处理表格超过 20 个。请先处理当前文件，再添加其余文件。'; break
        }
        // 修正文件重新添加时仅替换未保存的同路径来源，保留已有成功记录。
        entries.value = retained
        entries.value.push(...inspected.map(row => ({ ...row, id: ++nextId, target: row.target || '', source, saved: false, excluded: false })))
        revision.value++
      }
    } finally { if (current()) busy.value = false }
  }
  function changeType(id: number, target: string) {
    const row = entries.value.find(e => e.id === id)
    if (!row || row.saved || busy.value) return
    row.target = target; revision.value++
  }
  function exclude(id: number) {
    const row = entries.value.find(e => e.id === id)
    if (!row || row.saved || busy.value) return
    row.excluded = !row.excluded; revision.value++
  }
  function sources(target: string): ImportUploadSource[] {
    const selected = entries.value.filter(e => e.target === target && !e.excluded && !e.saved && !e.blocked)
    const result: ImportUploadSource[] = []
    for (const row of selected) {
      if (row.archive_member) {
        let source = result.find(r => r.file === row.source)
        if (!source) { source = { file: row.source, members: [] }; result.push(source) }
        source.members!.push(row.archive_member)
      } else result.push({ file: row.source })
    }
    return result
  }
  function markSaved(target: string, result: ImportSetResult) {
    const names = new Set(result.files.map(f => f.filename))
    for (const row of entries.value) {
      if (row.target === target && !row.excluded && names.has(row.filename)) row.saved = true
    }
    receipts.value.push(...result.files.filter(f => !receipts.value.some(old => old.id === f.id)))
  }
  return { entries, groups, receipts, busy, error, revision, addFiles, changeType, exclude, sources, markSaved, reset }
}
