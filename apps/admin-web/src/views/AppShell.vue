<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { listManagementSubmissions } from '../api/submissions'
import { listObjections } from '../api/objections'
import schoolLogo from '../assets/school-logo.png'

const router = useRouter()
const route = useRoute()
const sessionStore = useSessionStore()

const pendingReviewsCount = ref<number>(0)
const pendingObjectionsCount = ref<number>(0)

async function fetchBadgeCounts() {
  if (!sessionStore.currentUser) return

  // 1. 待审核查课提交
  if (sessionStore.hasPermission('submission.review')) {
    try {
      const res = await listManagementSubmissions({
        semester_id: sessionStore.currentSemesterId || undefined,
        review_status: 'PENDING',
        page_size: 1
      })
      pendingReviewsCount.value = res.total || 0
    } catch (e) {
      console.warn('获取待审核徽标计数失败:', e)
    }
  }

  // 2. 待终审考勤异议
  if (sessionStore.hasPermission('objection.final_review') || sessionStore.hasPermission('objection.read')) {
    try {
      const res = await listObjections({
        final_status: 'PENDING',
        page_size: 1
      })
      pendingObjectionsCount.value = res.total || 0
    } catch (e) {
      console.warn('获取待终审徽标计数失败:', e)
    }
  }
}

onMounted(async () => {
  if (sessionStore.semesters.length === 0) {
    await sessionStore.fetchAcademicContext()
  }
  await fetchBadgeCounts()
})

watch(() => route.path, () => {
  fetchBadgeCounts()
})

const currentUser = computed(() => sessionStore.currentUser)

// Menu items filtered by user permissions
const menuItems = computed(() => {
  const list = [
    {
      id: 'volunteers',
      idx: '00',
      path: '/dashboard/volunteers',
      name: '人员资质与绑定码',
      badge: null as string | null,
      badgeClass: '',
      permission: 'volunteer.read'
    },
    {
      id: 'schedule',
      idx: '01',
      path: '/dashboard/schedule',
      name: '课次勾选与下发',
      badge: null as string | null,
      badgeClass: '',
      permission: 'inspection.generate'
    },
    {
      id: 'tasks',
      idx: '02',
      path: '/dashboard/tasks',
      name: '查课任务与排班',
      badge: null,
      badgeClass: '',
      permission: 'inspection.read'
    },
    {
      id: 'reviews',
      idx: '03',
      path: '/dashboard/reviews',
      name: '提交管理审核',
      badge: pendingReviewsCount.value > 0 ? String(pendingReviewsCount.value) : null,
      badgeClass: 'badge-amber',
      permission: 'submission.review'
    },
    {
      id: 'objections',
      idx: '04',
      path: '/dashboard/objections',
      name: '考勤异议处理',
      badge: pendingObjectionsCount.value > 0 ? String(pendingObjectionsCount.value) : null,
      badgeClass: 'badge-red',
      permission: 'objection.final_review'
    },
    {
      id: 'reports',
      idx: '05',
      path: '/dashboard/reports',
      name: '学院考勤周报',
      badge: null,
      badgeClass: '',
      permission: 'report.read'
    },
    {
      id: 'users',
      idx: '06',
      path: '/dashboard/users',
      name: '人员与权限管理',
      badge: null,
      badgeClass: '',
      permission: 'academic.read'
    },
    {
      id: 'settings',
      idx: '07',
      path: '/dashboard/settings',
      name: '平台与学期设置',
      badge: null,
      badgeClass: '',
      permission: 'academic.manage'
    }
  ]

  // Filter based on user's actual permissions (or show all if admin/preview mode)
  return list.filter(item => {
    if (!item.permission) return true
    if (!sessionStore.currentUser) return true // preview mode fallback
    return sessionStore.hasPermission(item.permission)
  })
})

const userDisplayName = computed(() => {
  return currentUser.value?.display_name || '教师管理员'
})

const roleNameMap: Record<string, string> = {
  SUPER_ADMIN: '系统管理员',
  TEACHER_ADMIN: '教师管理员',
  COLLEGE_ADMIN: '学院管理员',
  COUNSELOR: '专职辅导员',
  STUDENT_VOLUNTEER: '查课志愿者',
  VOLUNTEER: '查课志愿者',
  STUDENT: '学生',
  TEACHER: '任课教师'
}

const userRoleBadge = computed(() => {
  const roles = currentUser.value?.roles || []
  const primary = roles[0] || 'TEACHER_ADMIN'
  return roleNameMap[primary] || primary
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
            <div class="college-name font-serif">人工智能学院</div>
            <div class="system-name font-serif">查课管理后台</div>
          </div>
        </div>
      </div>

      <nav class="side-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.id"
          :to="item.path"
          class="side-link"
          :class="{ on: route.path.startsWith(item.path) }"
        >
          <span class="idx font-mono">{{ item.idx }}</span>
          <span class="name">{{ item.name }}</span>
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
        <div class="status"><span class="dot"></span>系统运行正常</div>
        <div class="foot-sub">考勤数据实时同步 · 运行稳定</div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="shell-main">
      <!-- 顶部学期周次栏 -->
      <header class="topbar">
        <div class="term font-mono">
          <!-- 学期选择器 -->
          <div class="sem-picker">
            <select
              class="t-sem-select font-mono"
              :value="sessionStore.currentSemesterId"
              @change="e => sessionStore.setSemester((e.target as HTMLSelectElement).value)"
            >
              <option v-if="!sessionStore.semesters.length" value="">加载学期中...</option>
              <option
                v-for="s in sessionStore.semesters"
                :key="s.id"
                :value="s.id"
              >
                {{ s.name }}
              </option>
            </select>
          </div>

          <span class="t-sep"></span>

          <!-- 周次选择器 -->
          <div class="week-picker">
            <button
              class="week-nav-btn"
              :disabled="sessionStore.currentWeekNo <= 1"
              title="上一周"
              @click="sessionStore.setWeekNo(sessionStore.currentWeekNo - 1)"
            >
              ‹
            </button>
            <select
              class="t-week-select font-mono"
              :value="sessionStore.currentWeekNo"
              @change="e => sessionStore.setWeekNo(Number((e.target as HTMLSelectElement).value))"
            >
              <option
                v-for="w in sessionStore.totalWeeks"
                :key="w"
                :value="w"
              >
                第 {{ w }} 周
              </option>
            </select>
            <button
              class="week-nav-btn"
              :disabled="sessionStore.currentWeekNo >= sessionStore.totalWeeks"
              title="下一周"
              @click="sessionStore.setWeekNo(sessionStore.currentWeekNo + 1)"
            >
              ›
            </button>
          </div>

          <span class="t-range font-mono">{{ sessionStore.weekDateRange.text || '计算日期中' }}</span>
        </div>
      </header>

      <main class="main">
        <RouterView v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<style scoped>
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
}
.side-brand {
  padding: 0 20px 24px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 24px;
}
.brand-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-logo {
  width: 44px;
  height: 44px;
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
}
.brand-titles .college-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: 0.04em;
  line-height: 1.25;
  white-space: nowrap;
}
.brand-titles .system-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-soft);
  letter-spacing: 0.03em;
  line-height: 1.25;
  white-space: nowrap;
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
.side-link .idx { font-size: 10px; font-weight: 500; opacity: 0.6; }
.side-link:hover { color: var(--ink); background: var(--paper-deep); }
.side-link.on { color: var(--ink); font-weight: 600; }
.side-link.on::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--accent);
}
.side-link .badge {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 20px;
  align-self: center;
}
.badge-red { background: var(--accent-soft); color: var(--accent); }
.badge-amber { background: var(--amber-soft); color: var(--amber); }

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
  margin-bottom: 2px;
  color: var(--ink-soft);
  font-weight: 500;
}
.side-foot .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
}
.side-foot .foot-sub {
  color: var(--ink-mute);
  font-size: 11px;
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
  padding: 0 48px;
  flex-shrink: 0;
  background: var(--paper);
}
.term {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--ink-soft);
}
.sem-picker { display: flex; align-items: center; }
.t-sem-select {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  color: var(--ink);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 2px;
  cursor: pointer;
  outline: none;
}
.t-sem-select:hover { border-color: var(--line-strong); }
.term .t-sep { width: 1px; height: 14px; background: var(--line-strong); }

.week-picker {
  display: flex;
  align-items: center;
  background: var(--ink);
  border-radius: 2px;
  padding: 1px;
}
.week-nav-btn {
  background: none;
  border: none;
  color: var(--paper);
  font-size: 13px;
  font-weight: bold;
  cursor: pointer;
  padding: 2px 6px;
  opacity: 0.8;
  transition: opacity 0.15s;
}
.week-nav-btn:hover:not(:disabled) { opacity: 1; }
.week-nav-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.t-week-select {
  background: transparent;
  border: none;
  color: var(--paper);
  font-size: 11px;
  font-weight: 700;
  padding: 2px 4px;
  cursor: pointer;
  outline: none;
}
.t-week-select option { background: var(--paper); color: var(--ink); }
.term .t-range { color: var(--ink-mute); font-size: 11px; }

/* ---------- 内容区 ---------- */
.main {
  flex: 1;
  padding: 40px 48px 80px;
  overflow-y: auto;
}

@media (max-width: 900px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .topbar { padding: 0 24px; }
  .main { padding: 24px; }
}
</style>
