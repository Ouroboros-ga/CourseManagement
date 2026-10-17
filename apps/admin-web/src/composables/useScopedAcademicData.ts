import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { listScopedAcademic, type ScopedAcademicKind, type ScopedAcademicRow } from '../api/scopedAcademic'
import { useSessionStore } from '../stores/session'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'

const resources: { value: ScopedAcademicKind; label: string; permission: string }[] = [
  { value: 'administrative-classes', label: '行政班', permission: 'academic.read' },
  { value: 'students', label: '学生', permission: 'student.read' },
  { value: 'teaching-classes', label: '教学班', permission: 'academic.read' },
  { value: 'schedules', label: '课表', permission: 'academic.read' },
  { value: 'courses', label: '学校共享课程目录', permission: 'academic.read' },
  { value: 'semesters', label: '学校共享学期目录', permission: 'academic.read' },
  { value: 'qualifications', label: '志愿者资格', permission: 'volunteer.read' }
]
export function useScopedAcademicData(collegeId: () => string, capabilities: () => string[], allowedKinds?: () => ScopedAcademicKind[] | undefined) {
  const session = useSessionStore()
  const options = computed(() => resources.filter(item => capabilities().includes(item.permission) && (!allowedKinds?.() || allowedKinds()!.includes(item.value))))
  const kind = shallowRef<ScopedAcademicKind | ''>('')
  const page = shallowRef(1)
  const keyword = shallowRef('')
  const query = shallowRef('')
  const rows = shallowRef<ScopedAcademicRow[]>([])
  const total = shallowRef(0)
  const error = shallowRef('')
  const busy = shallowRef(false)
  const context = () => `${identityContext(session.currentUser)}:${collegeId()}:${capabilities().join(',')}`
  const semesterId = () => ['teaching-classes', 'schedules', 'qualifications'].includes(kind.value) ? session.currentSemesterId || '' : ''
  const epoch = new ContextEpoch(() => `${context()}:${kind.value}:${page.value}:${query.value}:${semesterId()}`)
  let active = true
  onUnmounted(() => { active = false; epoch.invalidate() })
  async function load() {
    const ticket = epoch.begin()
    error.value = ''
    if (!active || !collegeId() || !kind.value || !identityContext(session.currentUser)) {
      rows.value = []
      total.value = 0
      busy.value = false
      return
    }
    busy.value = true
    try {
      const result = semesterId()
        ? await listScopedAcademic(collegeId(), kind.value, page.value, query.value, semesterId())
        : await listScopedAcademic(collegeId(), kind.value, page.value, query.value)
      if (!active || !ticket.isCurrent()) return
      rows.value = result.items; total.value = result.total
    } catch (e) {
      if (active && ticket.isCurrent()) error.value = e instanceof Error ? e.message : '加载失败'
    } finally { if (!active || ticket.isLatest()) busy.value = false }
  }
  watch(context, () => {
    epoch.invalidate(); page.value = 1; total.value = 0; rows.value = []; keyword.value = ''; query.value = ''
    kind.value = options.value[0]?.value || ''
  }, { immediate: true })
  watch(kind, () => { page.value = 1; total.value = 0; rows.value = []; keyword.value = ''; query.value = '' })
  watch(semesterId, () => { page.value = 1; total.value = 0; rows.value = [] })
  watch([context, kind, page, query, semesterId], () => { void load() }, { immediate: true })
  function search() {
    const value = keyword.value.trim()
    if (page.value !== 1 || query.value !== value) { page.value = 1; query.value = value }
    else void load()
  }
  return { options, kind, page, keyword, rows, total, busy, error, load, search }
}
