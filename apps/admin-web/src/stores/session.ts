import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe, login as apiLogin, logout as apiLogout, refresh as apiRefresh, type CurrentUser } from '../api/auth'
import { listSemesters, type SemesterItem } from '../api/academic'

export const useSessionStore = defineStore('session', () => {
  const currentUser = ref<CurrentUser | null>(null)
  const isRestoring = ref(false)
  const isRestored = ref(false)

  // Academic context
  const semesters = ref<SemesterItem[]>([])
  const currentSemester = ref<SemesterItem | null>(null)
  const currentWeekNo = ref<number>(1)

  const currentSemesterId = computed(() => currentSemester.value?.id || '')
  const currentSemesterName = computed(() => currentSemester.value?.name || '未选中学期')
  const totalWeeks = computed(() => currentSemester.value?.total_weeks || 20)

  const isAuthenticated = computed(() => !!currentUser.value)
  const userRoles = computed(() => currentUser.value?.roles || [])
  const permissions = computed(() => new Set(currentUser.value?.permissions || []))

  function hasPermission(perm: string): boolean {
    return permissions.value.has(perm)
  }

  function hasAnyRole(...roles: string[]): boolean {
    return roles.some(r => userRoles.value.includes(r))
  }

  /**
   * 计算指定周的周一至周日日期
   */
  const weekDateRange = computed(() => {
    if (!currentSemester.value?.start_date) {
      return { start: '', end: '', text: '' }
    }
    const [year, month, day] = currentSemester.value.start_date.split('-').map(Number)
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
   * 根据当前自然日计算系统应处于的周次
   */
  function calculateCurrentNaturalWeek(startDateStr: string, maxWeeks: number): number {
    try {
      const [year, month, day] = startDateStr.split('-').map(Number)
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
    try {
      // 拉取全部学期（包含 ACTIVE 与 ARCHIVED），确保全局支持切换与查阅
      const res = await listSemesters('')
      semesters.value = res.items || []
      if (semesters.value.length > 0) {
        const storedId = localStorage.getItem('preferred_semester_id') || ''
        const candidateId = preferredId || currentSemester.value?.id || storedId

        // 查找优先级：明确指定的ID -> 当前选中的ID -> LocalStorage记录的ID -> 首个活跃学期 -> 倒序最新学期
        let target = candidateId ? semesters.value.find(s => String(s.id) === String(candidateId)) : null
        if (!target) {
          target = semesters.value.find(s => s.status === 'ACTIVE') || semesters.value[semesters.value.length - 1] || semesters.value[0]
        }

        currentSemester.value = target
        localStorage.setItem('preferred_semester_id', target.id)
        currentWeekNo.value = calculateCurrentNaturalWeek(target.start_date, target.total_weeks)
      }
    } catch (err) {
      console.warn('获取学期日历上下文失败:', err)
    }
  }

  function setSemester(semesterId: string): void {
    const found = semesters.value.find(s => String(s.id) === String(semesterId))
    if (found) {
      currentSemester.value = found
      localStorage.setItem('preferred_semester_id', found.id)
      currentWeekNo.value = calculateCurrentNaturalWeek(found.start_date, found.total_weeks)
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
        return false
      }
      currentUser.value = await getMe()
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
    await fetchAcademicContext()
    isRestored.value = true
    return user
  }

  async function signOut(): Promise<void> {
    try {
      await apiLogout()
    } finally {
      currentUser.value = null
      isRestored.value = true
    }
  }

  return {
    currentUser,
    isRestoring,
    isRestored,
    semesters,
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
