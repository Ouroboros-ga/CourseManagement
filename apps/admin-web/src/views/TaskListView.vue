<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import TaskStatusTag from '../components/TaskStatusTag.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import { listTasks, type InspectionTaskItem } from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { ElMessage, ElMessageBox } from 'element-plus'
import { request } from '../api/http'

const sessionStore = useSessionStore()

const loading = ref(false)
const tasks = ref<InspectionTaskItem[]>([])
const drawerVisible = ref(false)
const activeTask = ref<InspectionTaskItem | null>(null)
const searchQuery = ref('')
const selectedStatus = ref('')

async function fetchTasks() {
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  try {
    const res = await listTasks({
      semester_id: sessionStore.currentSemesterId,
      week_no: sessionStore.currentWeekNo,
      page_size: 100
    })
    tasks.value = res.items || []
  } catch (err: unknown) {
    console.error('获取任务列表失败:', err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [sessionStore.currentSemesterId, sessionStore.currentWeekNo],
  () => {
    fetchTasks()
  }
)

onMounted(() => {
  fetchTasks()
})

// 过滤后的任务列表
const filteredTasks = computed(() => {
  return tasks.value.filter(t => {
    if (selectedStatus.value && t.status !== selectedStatus.value) return false
    if (!searchQuery.value.trim()) return true
    const q = searchQuery.value.trim().toLowerCase()
    return (
      (t.id && t.id.toLowerCase().includes(q)) ||
      (t.course_name_snapshot && t.course_name_snapshot.toLowerCase().includes(q)) ||
      (t.class_name_snapshot && t.class_name_snapshot.toLowerCase().includes(q)) ||
      (t.classroom_snapshot && t.classroom_snapshot.toLowerCase().includes(q)) ||
      (t.assigned_volunteer_name && t.assigned_volunteer_name.toLowerCase().includes(q))
    )
  })
})

// 统计数据
const stats = computed(() => {
  const total = tasks.value.length
  const assigned = tasks.value.filter(t => t.assigned_volunteer_id || (t as any).assignment).length
  const unassigned = total - assigned
  const reviewed = tasks.value.filter(t => t.status === 'REVIEWED' || t.status === '已审核').length
  const assignRate = total > 0 ? ((assigned / total) * 100).toFixed(1) + '%' : '0%'

  return { total, assigned, unassigned, reviewed, assignRate }
})

function openTaskDetail(task: InspectionTaskItem) {
  activeTask.value = task
  drawerVisible.value = true
}

async function handleReassign(task: InspectionTaskItem) {
  try {
    const { value: volunteerId } = await ElMessageBox.prompt(
      `请输入要指派给该任务的志愿者用户 ID (当前任务: #${task.id}):`,
      '人工指派志愿者',
      {
        confirmButtonText: '确认指派',
        cancelButtonText: '取消',
        inputPattern: /^\d+$/,
        inputErrorMessage: '用户 ID 须为纯数字'
      }
    )

    if (volunteerId) {
      await request(`/api/v1/inspection-tasks/${task.id}/assignment`, {
        method: 'PUT',
        body: JSON.stringify({
          volunteer_user_id: volunteerId,
          lock_version: task.lock_version || 0
        })
      })
      ElMessage.success('指派成功')
      fetchTasks()
    }
  } catch {
    // cancelled
  }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>{{ sessionStore.currentSemesterName }}</span>
        <em>●</em>
        <span>第 {{ sessionStore.currentWeekNo }} 周</span>
        <em>●</em>
        <span>{{ sessionStore.weekDateRange.text }}</span>
      </div>
      <h1>查课任务与排班</h1>
      <p class="sub">
        当前周次真实数据库查课任务总览。支持查看任务点名名单、指派状态与考核事实，可人工分配或改派志愿者。
      </p>
    </header>

    <!-- 统计分栏 -->
    <div class="stat-row">
      <div class="stat-cell">
        <div class="label">本周计划总任务</div>
        <div class="value font-mono">{{ stats.total }}</div>
        <div class="note">数据库实时统计</div>
      </div>
      <div class="stat-cell">
        <div class="label">排班已分配</div>
        <div class="value font-mono" style="color: var(--green)">{{ stats.assigned }}</div>
        <div class="note"><span class="trend trend-up">{{ stats.assignRate }}</span> 分配率</div>
      </div>
      <div class="stat-cell">
        <div class="label">待分配志愿者</div>
        <div class="value font-mono" style="color: var(--amber)">{{ stats.unassigned }}</div>
        <div class="note">支持手动改派</div>
      </div>
      <div class="stat-cell">
        <div class="label">已审核完成</div>
        <div class="value font-mono" style="color: var(--blue)">{{ stats.reviewed }}</div>
        <div class="note">考勤结果已固化</div>
      </div>
    </div>

    <!-- 任务表 -->
    <div class="tbl-wrap">
      <div class="tbl-head">
        <div>
          <h3>任务总览（{{ filteredTasks.length }} / {{ tasks.length }}）</h3>
          <div class="meta">按检查日期与节次排序 · 数据库真实数据</div>
        </div>
        <div class="tbl-tools">
          <input
            v-model="searchQuery"
            type="text"
            class="input"
            style="width: 220px"
            placeholder="搜索课程 / 班级 / 教室…"
          />
          <select v-model="selectedStatus" class="input">
            <option value="">全部状态</option>
            <option value="NOT_STARTED">待执行</option>
            <option value="SUBMITTED">待审核</option>
            <option value="REVIEWED">已审核</option>
            <option value="CANCELLED">已取消</option>
          </select>
          <button class="btn btn-sm" @click="fetchTasks">⟳ 刷新</button>
        </div>
      </div>

      <table v-if="filteredTasks.length > 0" class="tbl">
        <thead>
          <tr>
            <th>任务 ID</th>
            <th>时间与地点</th>
            <th>课程与教学班</th>
            <th>受派志愿者</th>
            <th>状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in filteredTasks" :key="task.id">
            <td class="cell-mono tid">#{{ task.id }}</td>
            <td>
              <div class="cell-main">{{ task.inspection_date }} 第 {{ task.start_period }}-{{ task.end_period }} 节</div>
              <div class="cell-sub">{{ task.classroom_snapshot || '未指定教室' }}</div>
            </td>
            <td>
              <div class="cell-main">{{ task.course_name_snapshot || '—' }}</div>
              <div class="cell-sub">{{ task.class_name_snapshot || '—' }}</div>
            </td>
            <td>
              <template v-if="(task as any).assignment">
                <div class="cell-main">{{ (task as any).assignment.volunteer_name || '志愿者' }}</div>
                <div class="cell-sub cell-mono">UID: {{ (task as any).assignment.volunteer_user_id }}</div>
              </template>
              <template v-else-if="task.assigned_volunteer_name">
                <div class="cell-main">{{ task.assigned_volunteer_name }}</div>
                <div class="cell-sub cell-mono">{{ task.assigned_volunteer_id }}</div>
              </template>
              <template v-else>
                <div class="unassigned">未分配</div>
                <div class="cell-sub cell-mono">可人工指定</div>
              </template>
            </td>
            <td>
              <TaskStatusTag :status="task.status" :deadline-assessment="task.deadline_assessment" />
            </td>
            <td style="text-align: right">
              <button
                v-if="!(task as any).assignment && !task.assigned_volunteer_id"
                class="btn btn-sm"
                @click="handleReassign(task)"
              >
                人工指派
              </button>
              <button class="btn btn-ghost btn-sm" @click="openTaskDetail(task)">详情与名单</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else class="empty-box">
        <div class="empty-icon">📂</div>
        <div class="empty-text">当前周次（第 {{ sessionStore.currentWeekNo }} 周）暂无查课任务</div>
        <div class="empty-sub">您可以前往「01 课次勾选与下发」下发任务，或切换学期/周次</div>
      </div>
    </div>

    <TaskDrawer
      v-model:visible="drawerVisible"
      :task="activeTask"
      @reassign="handleReassign"
    />
  </div>
</template>

<style scoped>
.stat-row { margin-bottom: 40px; }
.tid { font-weight: 600; color: var(--blue); }
.unassigned { color: var(--amber); font-weight: 600; }

.empty-box {
  padding: 60px 20px;
  text-align: center;
  color: var(--ink-mute);
}
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 14px; font-weight: 600; color: var(--ink-soft); margin-bottom: 4px; }
.empty-sub { font-size: 12px; }
</style>
