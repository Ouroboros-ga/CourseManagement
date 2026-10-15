import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'
import { getCollegeCapabilities, listCourseTypes, listGroups, type College, type CourseType, type VolunteerGroup } from '../api/campus'

export function useCampusConfiguration() {
  const session = useSessionStore()
  const colleges = ref<College[]>([])
  const collegeId = computed({ get: () => session.workspaceCollegeId, set: value => session.selectWorkspace(value) })
  const college = ref<College | null>(null)
  const types = ref<CourseType[]>([])
  const groups = ref<VolunteerGroup[]>([])
  const error = shallowRef('')
  const busy = shallowRef(false)
  const userId = computed(() => identityContext(session.currentUser))
  const isSuper = computed(() => session.hasAnyRole('SUPER_ADMIN'))
  const epoch = new ContextEpoch(() => `${userId.value}:${collegeId.value}`)
  const workspaceEpoch = new ContextEpoch(() => userId.value)
  const can = (action: string) => !!college.value?.capabilities.includes(action)

  async function loadWorkspaces() {
    const ticket = workspaceEpoch.begin()
    try {
      await session.refreshWorkspaces()
      if (!ticket.isCurrent()) return
      colleges.value = session.workspaces
      if (collegeId.value) await reload()
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '获取学院失败'
    }
  }
  async function reload() {
    const cid = collegeId.value
    const ticket = epoch.begin()
    college.value = null
    types.value = []
    groups.value = []
    error.value = ''
    if (!cid || !userId.value) return
    busy.value = true
    try {
      const capability = await getCollegeCapabilities(cid)
      if (!ticket.isCurrent()) return
      college.value = capability
      const [typeRows, groupRows] = await Promise.all([
        capability.capabilities.includes('academic.course_type.read') ? listCourseTypes(cid) : Promise.resolve([]),
        capability.capabilities.includes('volunteer.group.read') ? listGroups(cid) : Promise.resolve([])
      ])
      if (!ticket.isCurrent()) return
      types.value = typeRows
      groups.value = groupRows
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '获取配置失败'
    } finally { if (ticket.isCurrent()) busy.value = false }
  }
  watch(userId, () => {
    workspaceEpoch.invalidate(); epoch.invalidate()
    colleges.value = []; college.value = null; collegeId.value = session.workspaceCollegeId || ''
    types.value = []; groups.value = []; busy.value = false; error.value = ''
    if (userId.value) {
      colleges.value = session.workspaces
      if (collegeId.value) void reload()
      else void loadWorkspaces()
    }
  }, { immediate: true })
  watch(collegeId, () => {
    busy.value = false; void reload()
  })
  onUnmounted(() => { epoch.invalidate(); workspaceEpoch.invalidate() })
  return { colleges, collegeId, college, types, groups, error, busy, userId, isSuper, can, reload, loadWorkspaces }
}
