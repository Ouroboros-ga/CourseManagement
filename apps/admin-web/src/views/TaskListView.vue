<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import TaskStatusTag from '../components/TaskStatusTag.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import AppIcon from '../components/AppIcon.vue'
import {
  listTasks,
  updateTask,
  deleteTask,
  batchDeleteTasks,
  triggerAutoAssign,
  listSemesterVolunteers,
  assignTask,
  cancelTask,
  type InspectionTaskItem,
  type SemesterVolunteerItem
} from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatPeriodText, PERIOD_PRESET_OPTIONS } from '../utils/period'

const sessionStore = useSessionStore()

const loading = ref(false)
const tasks = ref<InspectionTaskItem[]>([])
const selectedTaskIds = ref<string[]>([])
const drawerVisible = ref(false)
const activeTask = ref<InspectionTaskItem | null>(null)
const searchQuery = ref('')
const selectedStatus = ref('')
const selectedDayFilter = ref<string>('ALL')

function getTodayDateStr(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function getTaskWeekday(dateStr?: string | null): number | null {
  if (!dateStr) return null
  try {
    const parts = dateStr.split('-').map(Number)
    if (parts.length !== 3) return null
    const dt = new Date(parts[0], parts[1] - 1, parts[2])
    const day = dt.getDay()
    return isNaN(day) ? null : day
  } catch {
    return null
  }
}

function formatTaskDateWithWeekday(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const dayNames = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const weekday = getTaskWeekday(dateStr)
  const weekdayText = weekday !== null ? ` ${dayNames[weekday]}` : ''
  return `${dateStr}${weekdayText}`
}

const weekDayOptions = computed(() => {
  const baseDate = sessionStore.currentSemester?.first_monday || sessionStore.currentSemester?.start_date
  if (!baseDate) return []
  const [y, m, d] = baseDate.split('-').map(Number)
  const startDate = new Date(y, m - 1, d)
  const offsetDays = (sessionStore.currentWeekNo - 1) * 7
  const monday = new Date(startDate.getTime() + offsetDays * 86400000)

  const todayStr = getTodayDateStr()
  const dayLabels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
  const weekdayNumbers = [1, 2, 3, 4, 5, 6, 0] // JS getDay() mapping: Mon=1, Sun=0

  return weekdayNumbers.map((num, idx) => {
    const curDate = new Date(monday.getTime() + idx * 86400000)
    const mStr = String(curDate.getMonth() + 1).padStart(2, '0')
    const dStr = String(curDate.getDate()).padStart(2, '0')
    const isoDate = `${curDate.getFullYear()}-${mStr}-${dStr}`
    const isToday = isoDate === todayStr

    const count = tasks.value.filter(t => t.inspection_date === isoDate).length
    const todayMarker = isToday ? ' · 今天' : ''

    return {
      value: String(num),
      weekdayNum: num,
      isoDate,
      weekdayName: dayLabels[idx],
      dateLabel: `${mStr}-${dStr}`,
      isToday,
      count,
      label: `${dayLabels[idx]} (${mStr}-${dStr}${todayMarker}) [${count} 节查课]`
    }
  })
})

const currentDayFilterLabel = computed(() => {
  const found = weekDayOptions.value.find(d => d.value === selectedDayFilter.value)
  return found ? `${found.weekdayName} (${found.dateLabel}) · ${found.count} 节查课` : '指定日期'
})

async function fetchTasks() {
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  try {
    const res = await listTasks({
      semester_id: sessionStore.currentSemesterId,
      week_no: sessionStore.currentWeekNo,
      page_size: 200
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
    selectedTaskIds.value = []
    selectedDayFilter.value = 'ALL'
    fetchTasks()
  }
)

watch(selectedDayFilter, () => {
  selectedTaskIds.value = []
})

onMounted(() => {
  fetchTasks()
})

const statusAliasMap: Record<string, string[]> = {
  '待执行': ['待执行', 'NOT_STARTED'],
  '已逾期': ['已逾期', 'OVERDUE'],
  '待审核': ['待审核', 'SUBMITTED'],
  '已完成': ['已完成', 'REVIEWED', '已审核'],
  '已取消': ['已取消', 'CANCELLED']
}

// 过滤后的任务列表
const filteredTasks = computed(() => {
  return tasks.value.filter(t => {
    // 1. 日期 / 周几筛选
    if (selectedDayFilter.value !== 'ALL') {
      const targetWeekday = Number(selectedDayFilter.value)
      if (getTaskWeekday(t.inspection_date) !== targetWeekday) return false
    }

    // 2. 状态筛选
    if (selectedStatus.value) {
      const allowed = statusAliasMap[selectedStatus.value] || [selectedStatus.value]
      if (!allowed.includes(t.status)) return false
    }

    // 3. 关键字搜索
    if (!searchQuery.value.trim()) return true
    const q = searchQuery.value.trim().toLowerCase()
    return (
      (t.id && String(t.id).toLowerCase().includes(q)) ||
      (t.course_name_snapshot && t.course_name_snapshot.toLowerCase().includes(q)) ||
      (t.class_name_snapshot && t.class_name_snapshot.toLowerCase().includes(q)) ||
      (t.classroom_snapshot && t.classroom_snapshot.toLowerCase().includes(q)) ||
      (t.assigned_volunteer_name && t.assigned_volunteer_name.toLowerCase().includes(q)) ||
      ((t as any).assignment?.volunteer_name && (t as any).assignment.volunteer_name.toLowerCase().includes(q))
    )
  })
})

// 批量全选判定
const isAllSelected = computed(() => {
  if (filteredTasks.value.length === 0) return false
  return filteredTasks.value.every(t => selectedTaskIds.value.includes(t.id))
})

const isIndeterminate = computed(() => {
  const count = filteredTasks.value.filter(t => selectedTaskIds.value.includes(t.id)).length
  return count > 0 && count < filteredTasks.value.length
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    const curIds = new Set(filteredTasks.value.map(t => t.id))
    selectedTaskIds.value = selectedTaskIds.value.filter(id => !curIds.has(id))
  } else {
    const set = new Set(selectedTaskIds.value)
    filteredTasks.value.forEach(t => set.add(t.id))
    selectedTaskIds.value = Array.from(set)
  }
}

function toggleSelectTask(id: string) {
  const idx = selectedTaskIds.value.indexOf(id)
  if (idx >= 0) {
    selectedTaskIds.value.splice(idx, 1)
  } else {
    selectedTaskIds.value.push(id)
  }
}

// 统计数据
const stats = computed(() => {
  const total = tasks.value.length
  const assigned = tasks.value.filter(t => t.assigned_volunteer_id || (t as any).assignment).length
  const unassigned = total - assigned
  const reviewed = tasks.value.filter(t => t.status === 'REVIEWED' || t.status === '已审核' || t.status === '已完成').length
  const assignRate = total > 0 ? ((assigned / total) * 100).toFixed(1) + '%' : '0%'

  return { total, assigned, unassigned, reviewed, assignRate }
})

function openTaskDetail(task: InspectionTaskItem) {
  activeTask.value = task
  drawerVisible.value = true
}

// 单项删除查课任务
async function handleDeleteSingleTask(task: InspectionTaskItem) {
  try {
    await ElMessageBox.confirm(
      `确定要删除查课任务 #${task.id}（${task.course_name_snapshot || '未命名课程'}）吗？\n删除后关联的排班分配与点名名单快照将一并移除，此操作不可撤销。`,
      '删除查课任务',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
    loading.value = true
    await deleteTask(task.id, '管理端单项删除')
    ElMessage.success(`查课任务 #${task.id} 已成功删除！`)
    selectedTaskIds.value = selectedTaskIds.value.filter(id => id !== task.id)
    if (activeTask.value?.id === task.id) {
      drawerVisible.value = false
      activeTask.value = null
    }
    await fetchTasks()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.message || '删除任务失败')
    }
  } finally {
    loading.value = false
  }
}

// 批量删除查课任务
async function handleBatchDelete() {
  if (selectedTaskIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要批量删除选中的 ${selectedTaskIds.value.length} 个查课任务吗？\n删除后关联的排班受派与名单快照将一并清除，此操作不可撤销。`,
      '批量删除查课任务',
      {
        confirmButtonText: `确认删除 (${selectedTaskIds.value.length}项)`,
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
    loading.value = true
    const res = await batchDeleteTasks({
      task_ids: selectedTaskIds.value,
      reason: '管理端批量删除'
    })
    ElMessage.success(`成功批量删除 ${res.deleted_count} 个查课任务！`)
    selectedTaskIds.value = []
    if (activeTask.value && res.deleted_ids.includes(String(activeTask.value.id))) {
      drawerVisible.value = false
      activeTask.value = null
    }
    await fetchTasks()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.message || '批量删除任务失败')
    }
  } finally {
    loading.value = false
  }
}

// ==================== 智能自动排班（求解器防冲突算法） ====================
const autoAssigning = ref(false)

async function handleAutoAssign() {
  if (!sessionStore.currentSemesterId) return
  const isSelectedScope = selectedTaskIds.value.length > 0
  const confirmText = isSelectedScope
    ? `确定对表格中选中的 ${selectedTaskIds.value.length} 个任务执行智能自动排班？\n系统将自动运行防冲突算法，为其中尚未分配的任务匹配在册志愿者。`
    : `确定对当前【${sessionStore.currentSemesterName}】第 ${sessionStore.currentWeekNo} 周所有未分配的查课任务执行智能自动排班？\n系统将自动结合在册有效志愿者进行防冲突排班。`

  try {
    await ElMessageBox.confirm(confirmText, '智能自动排班确认', {
      confirmButtonText: '立即执行排班',
      cancelButtonText: '取消',
      type: 'info'
    })
    autoAssigning.value = true
    const payload = isSelectedScope
      ? {
          semester_id: sessionStore.currentSemesterId,
          task_ids: selectedTaskIds.value
        }
      : {
          semester_id: sessionStore.currentSemesterId,
          date_from: sessionStore.weekDateRange.start || undefined,
          date_to: sessionStore.weekDateRange.end || undefined
        }
    const res = await triggerAutoAssign(payload)
    ElMessage.success(`智能自动排班完成！已成功分配 ${res.assigned_count ?? 0} 个任务，待人工处理 ${res.unassigned_count ?? 0} 个`)
    selectedTaskIds.value = []
    await fetchTasks()
  } catch (err: unknown) {
    if (err !== 'cancel') {
      const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '自动排班执行失败'
      ElMessage.error(msg)
    }
  } finally {
    autoAssigning.value = false
  }
}

// ==================== 导出排班表（CSV / Excel 兼容） ====================
function handleExportTasks() {
  if (filteredTasks.value.length === 0) {
    ElMessage.warning('当前暂无可导出的排班任务')
    return
  }
  const headers = ['任务编号', '查课日期', '周次', '节次', '课程名称', '教学班级', '查课教室', '受派志愿者', '任务状态']
  const rows = filteredTasks.value.map(t => {
    const periodStr = formatPeriodText(t.start_period, t.end_period)
    const volName = t.assigned_volunteer_name || (t as any).assignment?.volunteer_name || '未指派'
    const statusMap: Record<string, string> = {
      NOT_STARTED: '待执行',
      SUBMITTED: '待审核',
      REVIEWED: '已完成',
      CANCELLED: '已取消',
      OVERDUE: '已逾期'
    }
    const statusStr = statusMap[t.status] || t.status || '待执行'
    return [
      t.id,
      t.inspection_date || '',
      `第${sessionStore.currentWeekNo}周`,
      `"${periodStr.replace(/"/g, '""')}"`,
      `"${(t.course_name_snapshot || '').replace(/"/g, '""')}"`,
      `"${(t.class_name_snapshot || '').replace(/"/g, '""')}"`,
      `"${(t.classroom_snapshot || '').replace(/"/g, '""')}"`,
      `"${volName.replace(/"/g, '""')}"`,
      statusStr
    ].join(',')
  })
  const csvContent = '\uFEFF' + [headers.join(','), ...rows].join('\r\n')
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `查课排班表_第${sessionStore.currentWeekNo}周_${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
  ElMessage.success(`成功导出 ${filteredTasks.value.length} 条查课排班记录！`)
}

// ==================== 人工指派志愿者（支持按姓名搜索本学期已有志愿者） ====================
const assignDialogVisible = ref(false)
const assigningTask = ref<InspectionTaskItem | null>(null)
const assignVolunteers = ref<SemesterVolunteerItem[]>([])
const loadingVolunteers = ref(false)
const selectedVolunteerUserId = ref<string>('')
const assignReason = ref('')
const assignSubmitting = ref(false)

const selectedVolunteer = computed(() => {
  return assignVolunteers.value.find(v => v.user_id === selectedVolunteerUserId.value)
})

async function loadSemesterVolunteers() {
  if (!sessionStore.currentSemesterId) return
  loadingVolunteers.value = true
  try {
    const res = await listSemesterVolunteers(sessionStore.currentSemesterId)
    assignVolunteers.value = res || []
  } catch (e) {
    console.error('加载本学期志愿者失败:', e)
  } finally {
    loadingVolunteers.value = false
  }
}

async function handleOpenAssignDialog(task: InspectionTaskItem) {
  assigningTask.value = task
  assignReason.value = ''
  const curUid = (task as any).assignment?.volunteer_user_id || task.assigned_volunteer_id
  selectedVolunteerUserId.value = curUid ? String(curUid) : ''
  assignDialogVisible.value = true
  await loadSemesterVolunteers()
}

async function handleConfirmAssign() {
  if (!assigningTask.value) return
  if (!selectedVolunteerUserId.value) {
    ElMessage.warning('请选择受派志愿者')
    return
  }
  assignSubmitting.value = true
  try {
    await assignTask(assigningTask.value.id, {
      volunteer_user_id: selectedVolunteerUserId.value,
      lock_version: assigningTask.value.lock_version || 0,
      reason: assignReason.value || '管理端人工指派志愿者'
    })
    const vol = selectedVolunteer.value
    ElMessage.success(`成功将任务 #${assigningTask.value.id} 指派给志愿者【${vol?.name || '志愿者'}】！`)
    assignDialogVisible.value = false
    await fetchTasks()
    if (activeTask.value?.id === assigningTask.value.id) {
      activeTask.value = tasks.value.find(t => t.id === assigningTask.value?.id) || null
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '指派志愿者失败')
  } finally {
    assignSubmitting.value = false
  }
}

// ==================== 编辑任务弹窗（方式 A） ====================
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
const editPeriodPreset = ref<number>(1)

function onPeriodPresetChange(val: number) {
  if (val > 0) {
    editForm.value.start_period = val
    editForm.value.end_period = val
  }
}

function openEditTask(task: InspectionTaskItem) {
  editingTask.value = task
  const sp = task.start_period || 1
  const ep = task.end_period || 1
  editForm.value = {
    classroom: task.classroom_snapshot || '',
    start_period: sp,
    end_period: ep,
    course_name: task.course_name_snapshot || '',
    reason: ''
  }
  if (sp === ep && sp >= 1 && sp <= 6) {
    editPeriodPreset.value = sp
  } else {
    editPeriodPreset.value = 0
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

// ==================== 标记停课免计（教师单独停课/特殊免查） ====================
const cancelDialogVisible = ref(false)
const cancelingTask = ref<InspectionTaskItem | null>(null)
const cancelPresetReason = ref('教师临时请假/停课')
const cancelCustomReason = ref('')
const cancelSubmitting = ref(false)

function openCancelDialog(task: InspectionTaskItem) {
  cancelingTask.value = task
  cancelPresetReason.value = '教师临时请假/停课'
  cancelCustomReason.value = ''
  cancelDialogVisible.value = true
}

function onPresetReasonChange() {
  if (cancelPresetReason.value !== 'CUSTOM') {
    cancelCustomReason.value = ''
  }
}

async function handleConfirmCancel() {
  if (!cancelingTask.value) return
  const finalReason = cancelPresetReason.value === 'CUSTOM'
    ? cancelCustomReason.value.trim()
    : cancelPresetReason.value
  if (!finalReason) {
    ElMessage.warning('请输入具体的停课/免计原因')
    return
  }
  cancelSubmitting.value = true
  try {
    await cancelTask(cancelingTask.value.id, {
      reason: finalReason,
      lock_version: cancelingTask.value.lock_version || 0
    })
    ElMessage.success(`任务 #${cancelingTask.value.id} 已成功标记为「已取消（${finalReason}）」，不计入本周考勤统计！`)
    cancelDialogVisible.value = false
    await fetchTasks()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '标记停课免计失败'
    ElMessage.error(msg)
  } finally {
    cancelSubmitting.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <h1>查课任务与排班</h1>
      <p class="sub">
        当前周次真实数据库查课任务总览。支持查看任务点名名单、指派状态与考核事实，可人工搜索姓名分配/改派志愿者或批量删除任务。
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
        <div class="note">支持手动按姓名指派</div>
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
          <div class="meta">
            按检查日期与节次排序 · 数据库真实数据
            <span v-if="selectedDayFilter !== 'ALL'" class="ml-2 font-medium text-slate-700">
              · [已筛选: {{ currentDayFilterLabel }}]
            </span>
          </div>
        </div>
        <div class="tbl-tools">
          <input
            v-model="searchQuery"
            type="text"
            class="input"
            style="width: 200px"
            placeholder="搜索课程 / 班级 / 教室…"
          />
          <select v-model="selectedDayFilter" class="input" style="min-width: 185px">
            <option value="ALL">本周全部 ({{ tasks.length }} 节查课)</option>
            <option v-for="d in weekDayOptions" :key="d.value" :value="d.value">{{ d.label }}</option>
          </select>
          <select v-model="selectedStatus" class="input">
            <option value="">全部状态</option>
            <option value="待执行">待执行</option>
            <option value="已逾期">已逾期</option>
            <option value="待审核">待审核</option>
            <option value="已完成">已完成</option>
            <option value="已取消">已取消</option>
          </select>
          <button
            class="btn btn-sm btn-primary inline-flex items-center gap-1.5 shadow-sm"
            :disabled="autoAssigning"
            title="调用求解器防冲突算法，为当前未分配任务自动匹配在册志愿者"
            @click="handleAutoAssign"
          >
            <AppIcon name="sparkles" :size="13" class="text-amber-300" />
            <span>{{ autoAssigning ? '排班中…' : (selectedTaskIds.length > 0 ? `智能自动排班 (${selectedTaskIds.length})` : '智能自动排班') }}</span>
          </button>
          <button
            class="btn btn-sm btn-danger inline-flex items-center gap-1"
            :disabled="selectedTaskIds.length === 0"
            @click="handleBatchDelete"
          >
            <AppIcon name="trash" :size="13" />
            <span>批量删除 ({{ selectedTaskIds.length }})</span>
          </button>
          <button
            class="btn btn-sm btn-outline inline-flex items-center gap-1"
            :disabled="filteredTasks.length === 0"
            title="将当前周或筛选出的查课任务与受派人员导出为表格"
            @click="handleExportTasks"
          >
            <AppIcon name="download" :size="13" />
            <span>导出排班 ({{ filteredTasks.length }})</span>
          </button>
          <button class="btn btn-sm" @click="fetchTasks">⟳ 刷新</button>
        </div>
      </div>

      <table v-if="filteredTasks.length > 0" class="tbl">
        <thead>
          <tr>
            <th style="width: 44px; text-align: center">
              <input
                type="checkbox"
                :checked="isAllSelected"
                :indeterminate="isIndeterminate"
                class="chk"
                title="全选 / 取消全选"
                @change="toggleSelectAll"
              />
            </th>
            <th>任务 ID</th>
            <th>时间与地点</th>
            <th>课程与教学班</th>
            <th>受派志愿者</th>
            <th>状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="task in filteredTasks"
            :key="task.id"
            :class="{ 'row-selected': selectedTaskIds.includes(task.id) }"
          >
            <td style="text-align: center">
              <input
                type="checkbox"
                :checked="selectedTaskIds.includes(task.id)"
                class="chk"
                @change="toggleSelectTask(task.id)"
              />
            </td>
            <td class="cell-mono tid">#{{ task.id }}</td>
            <td>
              <div class="cell-main">{{ formatTaskDateWithWeekday(task.inspection_date) }} {{ formatPeriodText(task.start_period, task.end_period) }}</div>
              <div class="cell-sub">{{ task.classroom_snapshot || '未指定教室' }}</div>
            </td>
            <td>
              <div class="cell-main">{{ task.course_name_snapshot || '—' }}</div>
              <div class="cell-sub">{{ task.class_name_snapshot || '—' }}</div>
            </td>
            <td>
              <template v-if="(task as any).assignment?.volunteer_user_id || task.assigned_volunteer_id">
                <div class="cell-main font-bold text-slate-800">
                  {{ (task as any).assignment?.volunteer_name || task.assigned_volunteer_name || '志愿者' }}
                </div>
                <div class="cell-sub cell-mono text-xs text-slate-500">
                  <span v-if="(task as any).assignment?.volunteer_class_name" class="mr-1">
                    {{ (task as any).assignment.volunteer_class_name }} ·
                  </span>
                  UID: {{ (task as any).assignment?.volunteer_user_id || task.assigned_volunteer_id }}
                </div>
              </template>
              <template v-else>
                <div class="unassigned text-slate-400">未分配</div>
                <div class="cell-sub cell-mono text-xs text-slate-400">可人工指定</div>
              </template>
            </td>
            <td>
              <TaskStatusTag :status="task.status" :deadline-assessment="task.deadline_assessment" />
              <div
                v-if="task.cancel_reason"
                class="cell-sub text-xs text-amber-700 mt-1 max-w-[140px] truncate"
                :title="task.cancel_reason"
              >
                停课: {{ task.cancel_reason }}
              </div>
            </td>
            <td style="text-align: right">
              <button
                class="btn btn-sm"
                @click="handleOpenAssignDialog(task)"
              >
                {{ (task as any).assignment || task.assigned_volunteer_id ? '改派' : '人工指派' }}
              </button>
              <button
                v-if="task.status !== '已取消' && task.status !== 'CANCELLED' && task.status !== '已完成' && task.status !== 'REVIEWED'"
                class="btn btn-ghost btn-sm inline-flex items-center gap-1"
                @click="openEditTask(task)"
              >
                <AppIcon name="edit" :size="12" />
                <span>编辑</span>
              </button>
              <button
                v-if="task.status !== '已取消' && task.status !== 'CANCELLED' && task.status !== '已完成' && task.status !== 'REVIEWED'"
                class="btn btn-ghost btn-sm text-amber-700 inline-flex items-center gap-1"
                style="color: #b45309;"
                title="标记为教师临时停课或免计（不计入考勤统计与周报，不影响志愿者）"
                @click="openCancelDialog(task)"
              >
                <AppIcon name="slash" :size="12" />
                <span>停课免计</span>
              </button>
              <button class="btn btn-ghost btn-sm" @click="openTaskDetail(task)">详情与名单</button>
              <button
                class="btn btn-ghost btn-sm text-red-600 inline-flex items-center gap-1"
                style="color: #dc2626;"
                title="删除此查课任务"
                @click="handleDeleteSingleTask(task)"
              >
                <AppIcon name="trash" :size="12" />
                <span>删除</span>
              </button>
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

    <!-- 弹窗 1：人工指派志愿者（支持按姓名搜索本学期已有志愿者） -->
    <el-dialog
      v-model="assignDialogVisible"
      :title="`人工指派志愿者 · 任务 #${assigningTask?.id || ''}`"
      width="580px"
      destroy-on-close
    >
      <div v-loading="assignSubmitting" class="assign-dialog-body">
        <!-- 任务信息概要卡片 -->
        <div v-if="assigningTask" class="task-info-card">
          <div class="task-info-title font-bold">
            {{ assigningTask.course_name_snapshot || '未命名课程' }}
          </div>
          <div class="task-info-meta">
            <span>教学班：{{ assigningTask.class_name_snapshot || '—' }}</span>
            <span>·</span>
            <span>{{ assigningTask.inspection_date }} {{ formatPeriodText(assigningTask.start_period, assigningTask.end_period) }}</span>
            <span>·</span>
            <span>教室：{{ assigningTask.classroom_snapshot || '未指定教室' }}</span>
          </div>
        </div>

        <!-- 志愿者搜索与选择 -->
        <div class="form-group" style="margin-top: 18px;">
          <label class="form-label font-bold" style="display: block; margin-bottom: 8px; font-size: 13px;">
            选择受派志愿者（在【本学期已有志愿者】中搜索）：
          </label>
          <el-select
            v-model="selectedVolunteerUserId"
            filterable
            placeholder="输入志愿者姓名、学号或行政班级快速搜索…"
            style="width: 100%"
            :loading="loadingVolunteers"
            no-data-text="本学期暂无启用的志愿者，可先在「人员资质」中添加"
          >
            <el-option
              v-for="v in assignVolunteers"
              :key="v.user_id"
              :label="`${v.name} (${v.student_no} · ${v.class_name || '未分班'})`"
              :value="v.user_id"
            >
              <div class="vol-option-row">
                <div>
                  <span class="vol-option-name">{{ v.name }}</span>
                  <span class="vol-option-sub font-mono">{{ v.student_no }} · {{ v.class_name || '未分班' }}</span>
                </div>
                <div class="vol-option-tags">
                  <span v-if="v.has_wechat" class="tag tag-green tag-mini">微信已绑定</span>
                  <span v-else class="tag tag-blue tag-mini">账号就绪</span>
                  <span class="vol-option-uid font-mono">UID:{{ v.user_id }}</span>
                </div>
              </div>
            </el-option>
          </el-select>
        </div>

        <!-- 选中志愿者详情名片 -->
        <div v-if="selectedVolunteer" class="selected-vol-card">
          <div class="vol-avatar-badge font-bold">{{ selectedVolunteer.name.slice(0, 1) }}</div>
          <div class="vol-meta-info">
            <div class="vol-name">
              {{ selectedVolunteer.name }}
              <span class="vol-sno font-mono">{{ selectedVolunteer.student_no }}</span>
            </div>
            <div class="vol-class font-mono">
              {{ selectedVolunteer.class_name || '行政班未分配' }} · 系统 UID: {{ selectedVolunteer.user_id }}
            </div>
          </div>
          <div class="vol-status-badge">
            <span v-if="selectedVolunteer.has_wechat" class="tag tag-green">微信已登录绑定</span>
            <span v-else class="tag tag-blue">账号就绪 · 可直接排班</span>
          </div>
        </div>

        <!-- 改派说明 -->
        <div class="form-group" style="margin-top: 14px;">
          <label class="form-label" style="display: block; margin-bottom: 6px; font-size: 12px; color: var(--ink-soft);">
            指派 / 改派说明（审计备查，选填）：
          </label>
          <input
            v-model="assignReason"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：任课老师调整时段改派、原志愿者请假人工调换"
          />
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button class="btn btn-ghost" @click="assignDialogVisible = false">取消</button>
          <button
            class="btn btn-primary"
            :disabled="assignSubmitting || !selectedVolunteerUserId"
            @click="handleConfirmAssign"
          >
            {{ assignSubmitting ? '指派中…' : '确认指派' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2：编辑查课任务弹窗（方式 A） -->
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

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">课程节次时段：</label>
          <el-select v-model="editPeriodPreset" @change="onPeriodPresetChange" style="width: 100%;">
            <el-option
              v-for="opt in PERIOD_PRESET_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
            <el-option :value="0" label="自定义起止节次 (连堂课/跨时段)" />
          </el-select>
        </div>

        <div v-if="editPeriodPreset === 0" style="display: flex; gap: 12px; margin-bottom: 14px;">
          <div style="flex: 1;">
            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">开始大节时段 (1-6)：</label>
            <el-input-number v-model="editForm.start_period" :min="1" :max="6" style="width: 100%;" />
          </div>
          <div style="flex: 1;">
            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">结束大节时段 (1-6)：</label>
            <el-input-number v-model="editForm.end_period" :min="editForm.start_period" :max="6" style="width: 100%;" />
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

    <!-- 弹窗 4：标记停课免计（教师单独停课或特殊免查） -->
    <el-dialog
      v-model="cancelDialogVisible"
      :title="`标记停课免计 · 任务 #${cancelingTask?.id || ''}`"
      width="460px"
    >
      <div v-if="cancelingTask" class="p-2 space-y-3">
        <div class="p-2.5 rounded bg-amber-50 border border-amber-200 text-amber-800 text-xs leading-relaxed">
          <b>⚡ 业务说明：</b>标记后，该查课任务将转为「已取消」，<b>不会计入本周周报与考勤到课率统计</b>。志愿者端将显示已取消，且截止结算时判定为豁免（不会被记为逾期违规）。
        </div>

        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">选择停课 / 免查原因 *</label>
          <select v-model="cancelPresetReason" class="input w-full" @change="onPresetReasonChange">
            <option value="教师临时请假/停课">教师临时请假 / 停课</option>
            <option value="班级外出实训/活动免查">班级外出实训 / 活动免查</option>
            <option value="教室设备故障/停电">教室设备故障 / 停电</option>
            <option value="教务处临时调整免查">教务处临时调整免查</option>
            <option value="CUSTOM">其他原因（自定义输入）</option>
          </select>
        </div>

        <div v-if="cancelPresetReason === 'CUSTOM'">
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">自定义具体原因 *</label>
          <input
            v-model="cancelCustomReason"
            class="input w-full"
            placeholder="例如: 教师因学术会议调课"
          />
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button class="btn btn-ghost" @click="cancelDialogVisible = false">取消</button>
          <button
            class="btn btn-dark"
            style="background: #b45309; border-color: #b45309; color: #fff;"
            :disabled="cancelSubmitting"
            @click="handleConfirmCancel"
          >
            {{ cancelSubmitting ? '正在处理…' : '确认标记并免计' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <TaskDrawer
      v-model:visible="drawerVisible"
      :task="activeTask"
      @reassign="handleOpenAssignDialog"
      @delete="handleDeleteSingleTask"
    />
  </div>
</template>

<style scoped>
.stat-row { margin-bottom: 16px; }
.tid { font-weight: 600; color: var(--blue); }
.unassigned { color: var(--amber); font-weight: 600; }

.chk {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--accent);
}

.row-selected {
  background-color: #f0fdf4 !important;
}

.btn-danger {
  background-color: #dc2626;
  color: #fff;
  border: 1px solid #dc2626;
}
.btn-danger:hover:not(:disabled) {
  background-color: #b91c1c;
}
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-box {
  padding: 60px 20px;
  text-align: center;
  color: var(--ink-mute);
}
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 14px; font-weight: 600; color: var(--ink-soft); margin-bottom: 4px; }
.empty-sub { font-size: 12px; }

/* 任务指派弹窗样式 */
.task-info-card {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 16px;
}
.task-info-title {
  font-size: 14px;
  color: var(--ink);
  margin-bottom: 4px;
}
.task-info-meta {
  font-size: 12px;
  color: var(--ink-mute);
  display: flex;
  gap: 8px;
  align-items: center;
}

.vol-option-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
.vol-option-name {
  font-weight: 600;
  margin-right: 8px;
}
.vol-option-sub {
  color: var(--ink-mute);
  font-size: 12px;
}
.vol-option-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.vol-option-uid {
  color: var(--ink-mute);
  font-size: 11px;
}
.tag-mini {
  padding: 1px 6px;
  font-size: 11px;
}

.selected-vol-card {
  margin-top: 14px;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.vol-avatar-badge {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}
.vol-meta-info {
  flex: 1;
}
.vol-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 8px;
}
.vol-sno {
  font-size: 12px;
  color: var(--ink-mute);
}
.vol-class {
  font-size: 11px;
  color: var(--ink-mute);
  margin-top: 2px;
}
</style>
