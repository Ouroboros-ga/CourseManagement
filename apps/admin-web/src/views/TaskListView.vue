<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import TaskStatusTag from '../components/TaskStatusTag.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import AppIcon from '../components/AppIcon.vue'
import { listTasks, updateTask, type InspectionTaskItem } from '../api/tasks'
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

// 编辑任务弹窗（方式 A）
const editDialogVisible = ref(false)
const editingTask = ref<InspectionTaskItem | null>(null)
const editForm = ref({
  classroom: '',
  start_period: 1,
  end_period: 2,
  course_name: '',
  reason: ''
})
const editSubmitting = ref(false)

function openEditTask(task: InspectionTaskItem) {
  editingTask.value = task
  editForm.value = {
    classroom: task.classroom_snapshot || '',
    start_period: task.start_period || 1,
    end_period: task.end_period || 2,
    course_name: task.course_name_snapshot || '',
    reason: ''
  }
  editDialogVisible.value = true
}

async function handleUpdateTask() {
  if (!editingTask.value) return
  editSubmitting.value = true
  try {
    await updateTask(editingTask.value.id, {
      classroom: editForm.value.classroom,
      start_period: editForm.value.start_period,
      end_period: editForm.value.end_period,
      course_name: editForm.value.course_name,
      reason: editForm.value.reason || '管理端直接修改任务信息'
    })
    ElMessage.success('查课任务信息修改成功！')
    editDialogVisible.value = false
    fetchTasks()
  } catch (err: any) {
    ElMessage.error(err.message || '修改任务失败')
  } finally {
    editSubmitting.value = false
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
              
    <!-- 编辑查课任务弹窗（方式 A） -->
    <el-dialog
      v-model="editDialogVisible"
      :title="`编辑查课任务 #${editingTask?.id || ''}`"
      width="480px"
      destroy-on-close
    >
      <div v-loading="editSubmitting" class="edit-dialog-body">
        <p style="font-size: 12px; color: var(--ink-mute); margin-bottom: 16px;">
          直接调整当天的查课任务信息（如任课老师临时调换教室或节次变更）。修改后将实时同步至志愿者的查课小程序端。
        </p>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">教室地点：</label>
          <input
            v-model="editForm.classroom"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：教学楼 3-203"
          />
        </div>

        <div style="display: flex; gap: 12px; margin-bottom: 14px;">
          <div style="flex: 1;">
            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">开始大节：</label>
            <el-input-number v-model="editForm.start_period" :min="1" :max="12" style="width: 100%;" />
          </div>
          <div style="flex: 1;">
            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">结束大节：</label>
            <el-input-number v-model="editForm.end_period" :min="editForm.start_period" :max="12" style="width: 100%;" />
          </div>
        </div>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">课程名称（快照）：</label>
          <input
            v-model="editForm.course_name"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：高等数学A"
          />
        </div>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">修改原因（审计备查）：</label>
          <input
            v-model="editForm.reason"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：任课教师申请临时调换教室"
          />
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button class="btn btn-ghost" @click="editDialogVisible = false">取消</button>
          <button class="btn btn-primary" :disabled="editSubmitting" @click="handleUpdateTask">
            {{ editSubmitting ? '保存中…' : '保存修改' }}
          </button>
        </div>
      </template>
    </el-dialog>

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
              <button v-if="task.status !== '已取消' && task.status !== '已完成'" class="btn btn-ghost btn-sm inline-flex items-center gap-1" @click="openEditTask(task)">
                <AppIcon name="edit" :size="12" />
                <span>编辑</span>
              </button>
              <button class="btn btn-ghost btn-sm" @click="openTaskDetail(task)">详情与名单</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else class="empty-box">
        <div class="empty-icon flex justify-center mb-2">
          <AppIcon name="folder-open" :size="36" class="text-gray-300" />
        </div>
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
