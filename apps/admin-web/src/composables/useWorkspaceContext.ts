import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { pageContextMode, workspaceContextKey } from '../navigation/workspaceNavigation'

export function useWorkspaceContext() {
  const session = useSessionStore()
  const route = useRoute()
  const page = computed(() => String(route.meta.workspacePage || route.name || 'home'))
  const mode = computed(() => pageContextMode(page.value, String(route.query.tab || '')))
  const key = computed(() => JSON.stringify([workspaceContextKey({
    userId: session.currentUser?.id || '', collegeId: session.workspaceCollegeId,
    authorizationRevision: String(session.workspace?.authorization_revision || ''), semesterId: session.currentSemesterId
  }, mode.value), mode.value === 'semester' && ['home', 'academic', 'inspections', 'reports'].includes(page.value) ? session.currentWeekNo : '']))
  const semesterId = computed(() => mode.value === 'semester' ? session.currentSemesterId : '')
  return { session, page, mode, key, semesterId }
}
