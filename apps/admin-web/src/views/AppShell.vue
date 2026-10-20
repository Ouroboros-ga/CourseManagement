<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { listObjections } from '../api/objections'
import { primaryPages, auxiliaryPages, canAccessPage } from '../navigation/workspaceNavigation'
import { useWorkspaceContext } from '../composables/useWorkspaceContext'
import { useWorkspaceChanges } from '../composables/useWorkspaceChanges'
import WorkspaceContextBar from '../components/workspace/WorkspaceContextBar.vue'
import { ContextEpoch } from '../utils/contextEpoch'
import schoolLogo from '../assets/school-logo.png'

const router = useRouter()
const route = useRoute()
const sessionStore = useSessionStore()
const { key: workspaceKey } = useWorkspaceContext()
const viewKey = computed(() => `${sessionStore.workspaceCollegeId || ''}:${sessionStore.currentSemesterId || ''}:${sessionStore.currentUser?.id || ''}`)
useWorkspaceChanges()
const mobileNavigation = ref(false)
const badgeEpoch = new ContextEpoch(() => workspaceKey.value)

const pendingObjectionsCount = ref<number>(0)

// 真实系统运行状态探测（通过 /health/ready 探针校验服务与数据库就绪度）
interface SystemHealth {
  state: 'healthy' | 'degraded' | 'down' | 'checking'
  text: string
  title: string
}

const systemHealth = ref<SystemHealth>({
  state: 'checking',
  text: '系统检测中…',
  title: '正在检测服务与数据库就绪状态'
})

let healthTimer: number | null = null

async function checkSystemHealth() {
  try {
    const res = await fetch('/health/ready', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
    if (res.ok) {
      const data = await res.json().catch(() => null)
      if (data?.status === 'ok' && data?.database === 'up') {
        systemHealth.value = {
          state: 'healthy',
          text: '系统运行正常',
          title: `服务与数据库正常 (环境: ${data.env || 'prod'}) · 点击刷新`
        }
      } else {
        systemHealth.value = {
          state: 'degraded',
          text: '数据库连接异常',
          title: data?.reason ? `数据库异常: ${data.reason} · 点击重试` : '数据库未就绪 · 点击重试'
        }
      }
    } else {
      const data = await res.json().catch(() => null)
      if (res.status === 503 && data?.database === 'down') {
        systemHealth.value = {
          state: 'degraded',
          text: '数据库连接中断',
          title: `数据库未就绪 (HTTP 503): ${data?.reason || '服务暂不可用'} · 点击重试`
        }
      } else {
        systemHealth.value = {
          state: 'down',
          text: `服务异常 (${res.status})`,
          title: `服务返回状态码 HTTP ${res.status} · 点击重试`
        }
      }
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '网络连接失败'
    systemHealth.value = {
      state: 'down',
      text: '服务连接断开',
      title: `无法连接服务器 (${msg}) · 点击重试`
    }
  }
}

async function fetchBadgeCounts() {
  const ticket = badgeEpoch.begin()
  pendingObjectionsCount.value = 0
  if (!sessionStore.currentUser) return

  // 待终审考勤异议
  if (sessionStore.hasPermission('objection.final_review') || sessionStore.hasPermission('objection.read')) {
    try {
      const res = await listObjections({
        semester_id: sessionStore.currentSemesterId || undefined,
        final_status: 'PENDING',
        page_size: 1
      })
      if (ticket.isCurrent()) pendingObjectionsCount.value = res.total || 0
    } catch (e) {
      if (ticket.isCurrent()) console.warn('获取待终审徽标计数失败:', e)
    }
  }
}

onMounted(async () => {
  if (sessionStore.semesters.length === 0) {
    await sessionStore.fetchAcademicContext()
  }
  await checkSystemHealth()
  healthTimer = window.setInterval(checkSystemHealth, 30000)
})

onUnmounted(() => {
  badgeEpoch.invalidate()
  if (healthTimer) {
    clearInterval(healthTimer)
    healthTimer = null
  }
})

// 学院已包含在工作区 key 中，统一监听可合并同一轮上下文变更。
watch([() => route.path, workspaceKey], () => {
  void fetchBadgeCounts()
}, { immediate: true })

const currentUser = computed(() => sessionStore.currentUser)

interface NavItem {
  id: string
  label: string
  path: string
  idx: string
  badge: string | null
  badgeClass: string
}

// 过滤权限后连续编号；考勤页挂待终审徽标
function decoratePages(pages: typeof primaryPages, startIdx: number): NavItem[] {
  return pages
    .filter(item => sessionStore.currentUser ? canAccessPage(item.id, sessionStore) : import.meta.env.DEV)
    .map((item, i) => ({
      id: item.id,
      label: item.label,
      path: item.path,
      idx: String(startIdx + i).padStart(2, '0'),
      badge: item.id === 'attendance' && pendingObjectionsCount.value > 0 ? String(pendingObjectionsCount.value) : null,
      badgeClass: 'badge-red'
    }))
}

const primaryNav = computed(() => decoratePages(primaryPages, 1))
const auxiliaryNav = computed(() => decoratePages(auxiliaryPages, primaryNav.value.length + 1))
watch(workspaceKey, () => {
  const page = String(route.meta.workspacePage || '')
  if (sessionStore.currentUser && page && !canAccessPage(page, sessionStore)) void router.replace('/dashboard/unavailable')
})

const userDisplayName = computed(() => {
  return currentUser.value?.display_name || '未命名账号'
})

// 只列 role 表里真实存在的五个角色；辅导员/班主任是教工职责（StaffDuty），不是登录角色。
const roleNameMap: Record<string, string> = {
  SUPER_ADMIN: '超级管理员',
  TEACHER_ADMIN: '教师管理员',
  STUDENT_AFFAIRS_MANAGER: '学生工作负责人',
  VOLUNTEER: '查课志愿者',
  STUDENT: '学生'
}

const userRoleBadge = computed(() => {
  const roles = currentUser.value?.roles || []
  const primary = roles[0] || ''
  return roleNameMap[primary] || (primary ? primary : '未分配角色')
})

async function handleLogout() {
  await sessionStore.signOut()
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="side-brand">
        <div class="brand-wrap">
          <img :src="schoolLogo" alt="绍兴理工学院校徽" class="brand-logo" />
          <div class="brand-titles">
            <div
              class="college-name font-serif"
              :title="sessionStore.workspace?.name || '学院工作区'"
            >
              {{ sessionStore.workspace?.name || '学院工作区' }}
            </div>
            <div class="system-name font-serif">查课管理后台</div>
          </div>
        </div>
      </div>

      <nav class="side-nav">
        <router-link
          v-for="item in primaryNav"
          :key="item.id"
          :to="item.path"
          class="side-link"
          :class="{ on: route.path.startsWith(item.path) }"
        >
          <span class="idx font-mono">{{ item.idx }}</span>
          <span class="name">{{ item.label }}</span>
          <span v-if="item.badge" class="badge font-mono" :class="item.badgeClass">{{ item.badge }}</span>
        </router-link>
        <div v-if="auxiliaryNav.length" class="nav-sep">
          <span class="nav-group font-mono">系统 SYSTEM</span>
        </div>
        <router-link
          v-for="item in auxiliaryNav"
          :key="item.id"
          :to="item.path"
          class="side-link side-link-aux"
          :class="{ on: route.path.startsWith(item.path) }"
        >
          <span class="idx font-mono">{{ item.idx }}</span>
          <span class="name">{{ item.label }}</span>
          <span v-if="item.badge" class="badge font-mono" :class="item.badgeClass">{{ item.badge }}</span>
        </router-link>
      </nav>

      <div class="side-user">
        <div class="u-info">
          <div class="u-name" :title="userDisplayName">{{ userDisplayName }}</div>
          <div class="u-role">{{ userRoleBadge }}</div>
        </div>
        <button class="u-logout" title="退出登录" @click="handleLogout">登出 →</button>
      </div>

      <div class="side-foot">
        <div
          class="status"
          :class="`status-${systemHealth.state}`"
          :title="systemHealth.title"
          @click="checkSystemHealth"
        >
          <span class="dot" :class="`dot-${systemHealth.state}`"></span>
          <span>{{ systemHealth.text }}</span>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="shell-main">
      <!-- 顶部学期周次栏 -->
      <header class="topbar">
        <button class="mobile-menu" @click="mobileNavigation = !mobileNavigation" :aria-expanded="mobileNavigation" aria-label="展开功能菜单">☰ 菜单</button>
        <WorkspaceContextBar />
      </header>
      <nav v-if="mobileNavigation" class="mobile-nav" aria-label="移动端功能菜单">
        <router-link
          v-for="item in [...primaryNav, ...auxiliaryNav]"
          :key="item.id"
          :to="item.path"
          :class="{ on: route.path.startsWith(item.path) }"
          @click="mobileNavigation = false"
        >{{ item.label }}</router-link>
      </nav>

      <main class="main">
        <el-alert v-if="sessionStore.workspaceError" :title="sessionStore.workspaceError" type="error" :closable="false" />
        <RouterView v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" :key="`${route.path}:${viewKey}`" />
          </transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<style scoped>
.mobile-menu { display: none; }
.mobile-nav { display: flex; flex-wrap: wrap; gap: 12px; padding: 16px; border-bottom: 1px solid var(--line); }
.mobile-nav a { padding: 6px 12px; color: var(--ink); }
.shell {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-height: 100vh;
}

/* ---------- 侧边栏 ---------- */
.sidebar {
  border-right: 1px solid var(--line);
  padding: 32px 0 0;
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  background: var(--paper);
  overflow-x: hidden;
}
.side-brand {
  padding: 0 16px 20px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 24px;
  overflow: hidden;
}
.brand-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  overflow: hidden;
}
.brand-logo {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.brand-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}
.brand-titles .college-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: 0.02em;
  line-height: 1.35;
  word-break: break-all;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
}
.brand-titles .system-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-soft);
  letter-spacing: 0.03em;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.side-nav { flex: 1; overflow-y: auto; }
.side-link {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 11px 24px;
  color: var(--ink-mute);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
  position: relative;
}
.side-link .idx { font-size: 10px; font-weight: 500; opacity: 0.6; transition: color 0.2s; }
.side-link:hover { color: var(--ink); background: var(--paper-deep); }
.side-link.on {
  color: var(--ink);
  font-weight: 600;
  background: var(--paper-deep);
}
.side-link.on .idx { color: var(--accent); opacity: 1; }
.side-link.on::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent);
}
.side-link .badge {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 10px;
  align-self: center;
}
.badge-red { background: var(--accent-soft); color: var(--accent); }

/* 分组：主导航 / 系统辅助导航 */
.nav-sep {
  margin: 16px 24px 4px;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}
.nav-group {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--ink-mute);
}
.side-link-aux { padding-top: 9px; padding-bottom: 9px; font-size: 12.5px; }

.side-user {
  padding: 16px 20px;
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.side-user .u-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}
.side-user .u-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}
.side-user .u-role {
  font-size: 11px;
  color: var(--blue);
  background: var(--blue-soft);
  padding: 1px 6px;
  border-radius: 3px;
  width: fit-content;
  font-weight: 500;
  line-height: 1.35;
}
.side-user .u-logout {
  flex-shrink: 0;
  border: none;
  background: none;
  font-size: 12px;
  font-family: inherit;
  color: var(--ink-mute);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: all 0.2s;
  white-space: nowrap;
}
.side-user .u-logout:hover {
  color: var(--accent);
  background: var(--paper-deep);
}

.side-foot {
  padding: 14px 20px 20px;
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.6;
}
.side-foot .status {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-soft);
  font-weight: 500;
  cursor: pointer;
  user-select: none;
  transition: opacity 0.2s;
}
.side-foot .status:hover {
  opacity: 0.8;
}
.side-foot .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  transition: background-color 0.3s ease;
}
.side-foot .dot-healthy {
  background: var(--green);
}
.side-foot .dot-degraded {
  background: var(--amber);
}
.side-foot .dot-down {
  background: var(--accent);
}
.side-foot .dot-checking {
  background: var(--ink-mute);
  opacity: 0.7;
}

.side-foot .status-healthy {
  color: var(--ink-soft);
}
.side-foot .status-degraded {
  color: var(--amber);
}
.side-foot .status-down {
  color: var(--accent);
}

/* ---------- 顶栏 ---------- */
.shell-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  height: 52px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  flex-shrink: 0;
  background: var(--paper);
}

/* ---------- 内容区 ---------- */
.main {
  flex: 1;
  padding: 18px 32px 36px;
  overflow-y: auto;
}

@media (max-width: 900px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .topbar { padding: 0 16px; height: auto; min-height: 52px; gap: 12px; flex-wrap: wrap; }
  .mobile-menu {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--paper);
    border: 1px solid var(--line-strong);
    padding: 6px 12px;
    border-radius: var(--radius);
    font-size: 12px;
    font-family: inherit;
    font-weight: 600;
    color: var(--ink);
    cursor: pointer;
    transition: border-color 0.15s;
  }
  .mobile-menu:hover { border-color: var(--ink); }
  .mobile-nav a.on { font-weight: 700; color: var(--accent); }
  .main { padding: 16px; }
}
</style>
