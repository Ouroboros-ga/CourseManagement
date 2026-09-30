import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe, login as apiLogin, logout as apiLogout, refresh as apiRefresh, type CurrentUser } from '../api/auth'

export const useSessionStore = defineStore('session', () => {
  const currentUser = ref<CurrentUser | null>(null)
  const isRestoring = ref(false)
  const isRestored = ref(false)

  // Current academic term & week for workspace
  const currentSemesterId = ref<string>('1')
  const currentSemesterName = ref<string>('2026-2027学年 秋季学期')
  const currentWeekNo = ref<number>(4)

  const isAuthenticated = computed(() => !!currentUser.value)
  const userRoles = computed(() => currentUser.value?.roles || [])
  const permissions = computed(() => new Set(currentUser.value?.permissions || []))

  function hasPermission(perm: string): boolean {
    return permissions.value.has(perm)
  }

  function hasAnyRole(...roles: string[]): boolean {
    return roles.some(r => userRoles.value.includes(r))
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
    currentSemesterId,
    currentSemesterName,
    currentWeekNo,
    isAuthenticated,
    userRoles,
    permissions,
    hasPermission,
    hasAnyRole,
    restoreSession,
    signIn,
    signOut
  }
})
