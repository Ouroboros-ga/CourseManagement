import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe, login as apiLogin, logout as apiLogout, refresh as apiRefresh, type CurrentUser } from '../api/auth'
import { listSemesters, type SemesterItem } from '../api/academic'
import { campusActionLabels, listWorkspaces, type College } from '../api/campus'
import { request } from '../api/http'
import { configureWorkspace, type CampusRuntime } from '../api/workspaceHttp'

export const useSessionStore = defineStore('session', () => {
  const currentUser = ref<CurrentUser | null>(null)
  const isRestoring = ref(false)
  const isRestored = ref(false)
  const campusRuntime = ref<CampusRuntime | null>(null)
  const workspaces = ref<College[]>([])
  const workspaceCollegeId = ref('')
  const workspaceError = ref('')
  const workspace = computed(() => workspaces.value.find(row => row.id === workspaceCollegeId.value) || null)
  const workspaceMode = computed(() => !!(campusRuntime.value?.academic_scoped || campusRuntime.value?.business_scoped))
  let workspaceEpoch = 0
  let academicEpoch = 0

  function selectWorkspace(cid: string) {
    if (!workspaces.value.some(row => row.id === cid && row.status === 'ACTIVE')) return
    workspaceCollegeId.value = cid
    configureWorkspace(campusRuntime.value, cid)
  }

  async function refreshWorkspaces() {
    const epoch = ++workspaceEpoch, actorId = currentUser.value?.id
      configureWorkspace(null, '')
    workspaceError.value = ''
    try {
      const mode = await request<CampusRuntime>('/api/v1/me/campus-runtime')
      let rows: College[] = []
      try { rows = await listWorkspaces() }
      catch (error) { if (mode.academic_scoped || mode.business_scoped) throw error }
      if (epoch !== workspaceEpoch || actorId !== currentUser.value?.id) return
      campusRuntime.value = mode
      workspaces.value = rows.filter(row => row.status === 'ACTIVE')
      if (!workspaces.value.some(row => row.id === workspaceCollegeId.value)) workspaceCollegeId.value = workspaces.value[0]?.id || ''
      configureWorkspace(mode, workspaceCollegeId.value)
    } catch (e) {
      if (epoch !== workspaceEpoch) return
      workspaces.value = []; workspaceCollegeId.value = ''; campusRuntime.value = null
      configureWorkspace(null, '')
      workspaceError.value = e instanceof Error ? e.message : '学院权限加载失败'
    }
  }

  // Academic context
  const semesters = ref<SemesterItem[]>([])
  const activeSemesters = computed(() => semesters.value.filter(s => s.status === 'ACTIVE'))
  const currentSemester = ref<SemesterItem | null>(null)
  const currentWeekNo = ref<number>(1)

  const currentSemesterId = computed(() => currentSemester.value?.id || '')
  const currentSemesterName = computed(() => currentSemester.value?.name || '未选中学期')
  const totalWeeks = computed(() => currentSemester.value?.total_weeks || 20)

  const isAuthenticated = computed(() => !!currentUser.value)
  const userRoles = computed(() => currentUser.value?.roles || [])
  const permissions = computed(() => new Set(currentUser.value?.permissions || []))

  function hasPermission(perm: string): boolean {
    if (workspaceMode.value && Object.prototype.hasOwnProperty.call(campusActionLabels, perm)) {
      return !!workspace.value?.capabilities.includes(perm)
    }
    return permissions.value.has(perm)
  }

  function hasAnyRole(...roles: string[]): boolean {
    return roles.some(r => userRoles.value.includes(r))
  }

  /**
   * 计算指定周的周一至周日日期（严格以第一教学周周一 first_monday 为基准）
   */
  const weekDateRange = computed(() => {
    const baseDate = currentSemester.value?.first_monday || currentSemester.value?.start_date
    if (!baseDate) {
      return { start: '', end: '', text: '' }
    }
    const [year, month, day] = baseDate.split('-').map(Number)
    const startDate = new Date(year, month - 1, day)
    
    // 偏移到对应周的周一
    const offsetDays = (currentWeekNo.value - 1) * 7
    const monday = new Date(startDate.getTime() + offsetDays * 86400000)
    const sunday = new Date(monday.getTime() + 6 * 86400000)

    const formatShort = (d: Date) => {
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const date = String(d.getDate()).padStart(2, '0')
      return `${m}月${date}日`
    }
    const formatISO = (d: Date) => {
      const y = d.getFullYear()
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const date = String(d.getDate()).padStart(2, '0')
      return `${y}-${m}-${date}`
    }

    return {
      start: formatISO(monday),
      end: formatISO(sunday),
      text: `${formatShort(monday)} — ${formatShort(sunday)}`
    }
  })

  /**
   * 根据当前自然日计算系统应处于的周次（严格以第一教学周周一为第1周开始基准）
   */
  function calculateCurrentNaturalWeek(baseMondayStr: string, maxWeeks: number): number {
    try {
      const [year, month, day] = baseMondayStr.split('-').map(Number)
      const start = new Date(year, month - 1, day)
      const now = new Date()
      const diffMs = now.getTime() - start.getTime()
      if (diffMs < 0) return 1
      const diffDays = Math.floor(diffMs / 86400000)
      const week = Math.floor(diffDays / 7) + 1
      return Math.min(Math.max(1, week), maxWeeks)
    } catch {
      return 1
    }
  }

  async function fetchAcademicContext(preferredId?: string): Promise<void> {
    const epoch = ++academicEpoch, actorId = currentUser.value?.id
    try {
      // 拉取全部学期（包含 ACTIVE 与 ARCHIVED），确保全局支持切换与查阅
      const res = await listSemesters('')
      if (epoch !== academicEpoch || actorId !== currentUser.value?.id) return
      semesters.value = res.items || []
      if (semesters.value.length > 0) {
        const storedId = localStorage.getItem('preferred_semester_id') || ''
        const candidateId = preferredId || currentSemester.value?.id || storedId

        // 明确选择的历史学期也须保留；只在选择不存在时回退到有效学期。
        const activeList = semesters.value.filter(s => s.status === 'ACTIVE')
        let target = candidateId ? semesters.value.find(s => String(s.id) === String(candidateId)) : null
        if (!target) {
          target = activeList[0] || semesters.value.find(s => s.status === 'ACTIVE') || semesters.value[0]
        }

        currentSemester.value = target
        localStorage.setItem('preferred_semester_id', target.id)
        currentWeekNo.value = calculateCurrentNaturalWeek(target.first_monday || target.start_date, target.total_weeks)
      }
    } catch (err) {
      console.warn('获取学期日历上下文失败:', err)
    }
  }

  function setSemester(semesterId: string): void {
    const found = semesters.value.find(s => String(s.id) === String(semesterId))
    if (found) {
      academicEpoch += 1
      currentSemester.value = found
      localStorage.setItem('preferred_semester_id', found.id)
      currentWeekNo.value = calculateCurrentNaturalWeek(found.first_monday || found.start_date, found.total_weeks)
    }
  }

  function setWeekNo(weekNo: number): void {
    if (weekNo >= 1 && weekNo <= totalWeeks.value) {
      currentWeekNo.value = weekNo
    }
  }

  async function restoreSession(): Promise<boolean> {
    if (isRestored.value) return isAuthenticated.value
    isRestoring.value = true
    try {
      const refreshedToken = await apiRefresh()
      if (!refreshedToken) {
        currentUser.value = null
        workspaces.value = []; workspaceCollegeId.value = ''; campusRuntime.value = null
        configureWorkspace(null, '')
        return false
      }
      currentUser.value = await getMe()
      await refreshWorkspaces()
      await fetchAcademicContext()
      return true
    } catch {
      currentUser.value = null
      return false
    } finally {
      isRestoring.value = false
      isRestored.value = true
    }
  }

  async function signIn(username: string, password: string): Promise<CurrentUser> {
    await apiLogin(username, password)
    const user = await getMe()
    currentUser.value = user
    await refreshWorkspaces()
    await fetchAcademicContext()
    isRestored.value = true
    return user
  }

  async function signOut(): Promise<void> {
    try {
      await apiLogout()
    } finally {
      currentUser.value = null
      workspaceEpoch += 1
      academicEpoch += 1
      semesters.value = []; currentSemester.value = null
      workspaces.value = []; workspaceCollegeId.value = ''; campusRuntime.value = null
      configureWorkspace(null, '')
      isRestored.value = true
    }
  }

  return {
    currentUser,
    campusRuntime, workspaces, workspace, workspaceCollegeId, workspaceMode, workspaceError,
    selectWorkspace, refreshWorkspaces,
    isRestoring,
    isRestored,
    semesters,
    activeSemesters,
    currentSemester,
    currentSemesterId,
    currentSemesterName,
    currentWeekNo,
    totalWeeks,
    weekDateRange,
    isAuthenticated,
    userRoles,
    permissions,
    hasPermission,
    hasAnyRole,
    setSemester,
    setWeekNo,
    fetchAcademicContext,
    restoreSession,
    signIn,
    signOut
  }
})
