import { createRouter, createWebHistory, type RouteRecordRaw, type LocationQueryRaw } from 'vue-router'
import type { Component } from 'vue'
import { useSessionStore } from '../stores/session'
import { primaryPages, auxiliaryPages, canAccessPage, legacyDestination } from '../navigation/workspaceNavigation'
import { confirmWorkspaceChange } from '../composables/useWorkspaceChanges'

const viewLoaders: Record<string, () => Promise<{ default: Component }>> = {
  home: () => import('../views/WorkbenchView.vue'), academic: () => import('../views/AcademicView.vue'),
  students: () => import('../views/StudentsView.vue'), organizations: () => import('../views/OrganizationsView.vue'),
  inspections: () => import('../views/InspectionsView.vue'), attendance: () => import('../views/AttendanceView.vue'),
  reports: () => import('../views/ReportsView.vue'), school: () => import('../views/SchoolView.vue'),
  users: () => import('../views/UsersView.vue'), settings: () => import('../views/SettingsView.vue'),
  staff: () => import('../views/StaffView.vue'),
  help: () => import('../views/HelpView.vue')
}
const pageRoutes: RouteRecordRaw[] = [...primaryPages, ...auxiliaryPages].map(page => ({
  path: page.path.slice('/dashboard/'.length), name: page.id,
  meta: { workspacePage: page.id }, component: viewLoaders[page.id]
}))

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', redirect: '/dashboard/home' },
  {
    path: '/dashboard', component: () => import('../views/AppShell.vue'), children: [
      { path: '', redirect: '/dashboard/home' },
      ...pageRoutes,
      { path: 'campus', name: 'campus', meta: { workspacePage: 'home' }, component: () => import('../views/CampusView.vue') },
      { path: 'unavailable', name: 'unavailable', component: () => import('../views/AccessDeniedView.vue') },
      ...['schedule', 'tasks', 'reviews', 'objections', 'volunteers'].map(id => ({
        path: id, redirect: (to: { query: LocationQueryRaw; hash: string }) => legacyDestination(id, to.query, to.hash) as { path: string; query: LocationQueryRaw; hash: string }
      }))
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard/home' }
]
const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to, from) => {
  const session = useSessionStore()
  if (!session.isRestored) await session.restoreSession()
  if (to.name !== 'login' && !session.isAuthenticated && !import.meta.env.DEV) return '/login'
  if (to.name === 'login' && session.isAuthenticated) return '/dashboard/home'
  if (from.fullPath !== to.fullPath && !confirmWorkspaceChange()) return false
  const collegeId = typeof to.query.workspace_id === 'string' ? to.query.workspace_id : ''
  if (collegeId && collegeId !== session.workspaceCollegeId) {
    if (!session.workspaces.some(row => row.id === collegeId && row.status === 'ACTIVE')) return '/dashboard/unavailable'
    session.selectWorkspace(collegeId)
  }
  const semesterId = typeof to.query.semester_id === 'string' ? to.query.semester_id : ''
  if (semesterId && semesterId !== session.currentSemesterId) {
    if (!session.semesters.some(row => row.id === semesterId)) return '/dashboard/unavailable'
    session.setSemester(semesterId)
  }
  const rawWeek = to.query.week || to.query.week_no
  if (rawWeek) {
    const week = Number(rawWeek)
    if (!Number.isInteger(week) || week < 1 || week > session.totalWeeks) return '/dashboard/unavailable'
    session.setWeekNo(week)
  }
  const page = String(to.meta.workspacePage || '')
  if (session.currentUser && page && !canAccessPage(page, session)) return '/dashboard/unavailable'
})
router.onError((error: Error) => {
  if (/Failed to fetch dynamically imported module|Importing a module script failed/.test(error.message)) window.location.reload()
})
export default router
