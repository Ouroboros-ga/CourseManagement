import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useSessionStore } from '../stores/session'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue')
  },
  {
    path: '/',
    redirect: '/dashboard/schedule'
  },
  {
    path: '/dashboard',
    component: () => import('../views/AppShell.vue'),
    children: [
      {
        path: '',
        redirect: '/dashboard/schedule'
      },
      {
        path: 'schedule',
        name: 'schedule',
        component: () => import('../views/ScheduleView.vue')
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('../views/TaskListView.vue')
      },
      {
        path: 'reviews',
        name: 'reviews',
        component: () => import('../views/ReviewsView.vue')
      },
      {
        path: 'objections',
        name: 'objections',
        component: () => import('../views/ObjectionsView.vue')
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('../views/ReportsView.vue')
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard/schedule'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to, _from, next) => {
  const sessionStore = useSessionStore()

  // Try to restore session once if not yet attempted
  if (!sessionStore.isRestored) {
    await sessionStore.restoreSession()
  }

  // Allow direct view in dev/preview mode, or redirect to login if required
  if (to.name !== 'login' && !sessionStore.isAuthenticated) {
    // In dev prototype mode, allow access for testing UI components directly
    next()
    return
  }

  if (to.name === 'login' && sessionStore.isAuthenticated) {
    next('/dashboard/schedule')
    return
  }

  next()
})

export default router
