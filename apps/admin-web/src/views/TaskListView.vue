<script setup lang="ts">
import { confirmGroupAssignment, confirmGroupPlan } from '../composables/confirmGroupAssignment'
import { automaticAssignmentTargets, isUnassignedTask } from '../utils/automaticAssignmentTargets'
import { formatBeijingTime } from '@/utils/datetime'
import { useRoute } from 'vue-router'
import { assignmentWarnings } from '../utils/assignmentWarnings'
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ContextEpoch } from '../utils/contextEpoch'
import AppPagination from '../components/AppPagination.vue'
import TaskStatusTag from '../components/TaskStatusTag.vue'
import AutoChangePolicyCard from '../components/AutoChangePolicyCard.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import AppIcon from '../components/AppIcon.vue'
import {
  listTasks,
  exportTasks,
  updateTask,
  previewTaskDeletion,
  restoreDeletedTask,
  batchDeleteTasks,
  triggerAutoAssign,
  listSemesterVolunteers,
  listTaskCandidateVolunteers,
  reviewChangeRequest,
  assignTask,
  cancelTask,
  type InspectionTaskItem,
  type SemesterVolunteerItem,
  type TaskCandidateVolunteerItem
} from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatPeriodText, PERIOD_PRESET_OPTIONS } from '../utils/period'

const sessionStore = useSessionStore()
const route = useRoute()
const needsAttention = computed(() => ['unassigned', 'roster'].includes(String(route.query.needs_attention)) ? route.query.needs_attention as 'unassigned' | 'roster' : undefined)
const attentionPage = ref(1), attentionTotal = ref(0)
const summary = ref({ total: 0, assigned: 0, unassigned: 0, reviewed: 0, pending_change: 0, dates: {} as Record<string, number> })
const taskEpoch = new ContextEpoch(() => JSON.stringify([sessionStore.currentUser?.id, sessionStore.workspaceCollegeId,
  sessionStore.currentSemesterId, sessionStore.currentWeekNo, needsAttention.value, attentionPage.value,
  deletedOnly.value, searchQuery.value, selectedStatus.value, selectedDayFilter.value, filterOnlyChangeRequests.value]))
onUnmounted(() => taskEpoch.invalidate())

const loading = ref(false)
const tasks = ref<InspectionTaskItem[]>([])
const deletedOnly = ref(false)
const selectedTaskIds = ref<string[]>([])
const drawerVisible = ref(false)
const activeTask = ref<InspectionTaskItem | null>(null)
const searchQuery = ref('')
const selectedStatus = ref(needsAttention.value === 'unassigned' ? '未分配' : '')
const selectedDayFilter = ref<string>('ALL')
const filterOnlyChangeRequests = ref(false)

const pendingChangeRequestsCount = computed(() => summary.value.pending_change)
const canConfigureAutoChange = computed(() => !!sessionStore.campusRuntime?.scheduling
  && sessionStore.hasPermission('assignment.manage')
  && sessionStore.hasPermission('assignment.change_review')
  && sessionStore.hasPermission('volunteer.group.read'))
const autoChangeContextKey = computed(() => JSON.stringify([
  sessionStore.currentUser?.id, sessionStore.workspaceCollegeId,
  sessionStore.workspace?.authorization_revision, sessionStore.workspace?.configuration_revision,
  sessionStore.workspace?.capabilities, sessionStore.currentSemesterId, canConfigureAutoChange.value
]))

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

    const count = summary.value.dates[isoDate] || 0
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

function taskQuery() {
  const isUnassigned = selectedStatus.value === '未分配'
  const activeNeedsAttention = isUnassigned
    ? 'unassigned'
    : (selectedStatus.value ? undefined : needsAttention.value)
  const activeWeekNo = (needsAttention.value && !selectedStatus.value) ? undefined : sessionStore.currentWeekNo

  return {
    deleted_only: deletedOnly.value,
    semester_id: sessionStore.currentSemesterId,
    week_no: activeWeekNo,
    needs_attention: activeNeedsAttention,
    page: attentionPage.value,
    page_size: 50,
    keyword: searchQuery.value.trim() || undefined,
    status: isUnassigned ? undefined : statusCodes[selectedStatus.value],
    inspection_date: selectedDayFilter.value === 'ALL' ? undefined : weekDayOptions.value.find(d => d.value === selectedDayFilter.value)?.isoDate,
    pending_change: filterOnlyChangeRequests.value || undefined
  }
}

async function fetchTasks() {
  const ticket = taskEpoch.begin()
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  try {
    const res = await listTasks(taskQuery())
    if (!ticket.isCurrent()) return
    tasks.value = res.items || []
    attentionTotal.value = res.total
    summary.value = res.summary || summary.value
    if (attentionPage.value > 1 && !res.items.length) attentionPage.value = Math.max(1, Math.ceil(res.total / 50))
  } catch (err: unknown) {
    if (ticket.isCurrent()) console.error('获取任务列表失败:', err)
  } finally {
    if (ticket.isLatest()) loading.value = false
  }
}

const statusCodes: Record<string, string> = { '待执行': 'NOT_STARTED', '已逾期': 'OVERDUE', '已取消': 'CANCELLED', '已完成': 'REVIEWED' }
const filteredTasks = computed(() => tasks.value)
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch([searchQuery, selectedStatus, selectedDayFilter, filterOnlyChangeRequests, deletedOnly, needsAttention,
  () => sessionStore.currentSemesterId, () => sessionStore.currentWeekNo,
  () => sessionStore.workspaceCollegeId, () => sessionStore.currentUser?.id], () => {
  taskEpoch.invalidate()
  selectedTaskIds.value = []; tasks.value = []; attentionPage.value = 1
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void fetchTasks(), 250)
})
watch(attentionPage, () => { selectedTaskIds.value = []; clearTimeout(searchTimer); searchTimer = setTimeout(() => void fetchTasks(), 0) })
onMounted(() => void fetchTasks())
onUnmounted(() => clearTimeout(searchTimer))

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
const stats = computed(() => ({ ...summary.value,
  assignRate: summary.value.total ? `${((summary.value.assigned / summary.value.total) * 100).toFixed(1)}%` : '0%'
}))

function openTaskDetail(task: InspectionTaskItem) {
  activeTask.value = task
  drawerVisible.value = true
}

// Deletion previews are bound to the current actor, workspace and exact task set.
const deletionContext = () => `${sessionStore.currentUser?.id}:${sessionStore.workspaceCollegeId}:${sessionStore.currentSemesterId}:${sessionStore.currentWeekNo}:${deletedOnly.value}`

async function deleteReviewedTasks(ids: string[]) {
  const context = deletionContext()
  try {
    const plan = await previewTaskDeletion(ids)
    if (context !== deletionContext()) return
    await ElMessageBox.confirm(`本次彻底删除 ${plan.permanent_ids.length} 项未使用任务；另有 ${plan.retained_ids.length} 项仅从日常管理移除，保留考勤、异议、照片及截止事实，考勤统计不变，可恢复。`, '核对删除方式', { type: 'warning', confirmButtonText: '按上述方式删除' })
    if (context !== deletionContext()) return
    loading.value = true
    await batchDeleteTasks({ task_ids: ids, reason: '管理端确认删除', deletion_revision: plan.revision })
    if (context !== deletionContext()) return
    ElMessage.success(`已处理 ${ids.length} 项；历史记录按预览保留`)
    selectedTaskIds.value = []; drawerVisible.value = false; activeTask.value = null
    await fetchTasks()
  } catch (e) { if (e !== 'cancel' && e !== 'close' && context === deletionContext()) ElMessage.error(e instanceof Error ? e.message : '删除失败') }
  finally { if (context === deletionContext()) loading.value = false }
}
async function handleDeleteSingleTask(task: InspectionTaskItem) { await deleteReviewedTasks([task.id]) }
async function handleBatchDelete() { if (selectedTaskIds.value.length) await deleteReviewedTasks([...selectedTaskIds.value]) }
async function handleRestoreDeleted(task: InspectionTaskItem) {
  const context = deletionContext()
  try {
    await ElMessageBox.confirm('恢复到日常任务列表，保留原状态、考勤与受派；不会重新生成任务或自动重新排班。', '恢复任务', { type: 'info' })
    if (context !== deletionContext()) return
    await restoreDeletedTask(task.id, task.lock_version || 0)
    if (context === deletionContext()) { ElMessage.success('已恢复'); await fetchTasks() }
  } catch (e) { if (e !== 'cancel' && e !== 'close' && context === deletionContext()) ElMessage.error(e instanceof Error ? e.message : '恢复失败') }
}

// ==================== 智能自动排班（求解器防冲突算法） ====================
const autoAssigning = ref(false)

let assignmentViewAlive = true
onUnmounted(() => { assignmentViewAlive = false })
async function handleAutoAssign(mode: 'filtered' | 'selected' = 'filtered') {
  if (!sessionStore.currentSemesterId || deletedOnly.value) return
  const semesterId = sessionStore.currentSemesterId
  const query = { ...taskQuery() }
  const selectedIds = [...selectedTaskIds.value]
  const context = () => JSON.stringify([sessionStore.currentUser?.id, sessionStore.workspaceCollegeId,
    sessionStore.workspace?.authorization_revision, sessionStore.currentSemesterId, taskQuery(), selectedTaskIds.value])
  const captured = context()
  const current = () => assignmentViewAlive && captured === context()
  const scopeLabel = mode === 'selected' ? '仅本页明确勾选的未分配任务' : '当前筛选下全部未分配任务（跨全部分页）'
  autoAssigning.value = true
  try {
    let targetRows: InspectionTaskItem[]
    if (mode === 'selected') {
      const selected = tasks.value.filter(task => selectedIds.includes(task.id))
      if (selected.length !== selectedIds.length) throw new Error('勾选任务已变化，请刷新后重新选择')
      targetRows = selected.filter(isUnassignedTask)
    } else {
      targetRows = await automaticAssignmentTargets(query, current)
    }
    if (!current()) return
    if (!targetRows.length) { ElMessage.info('当前范围没有未分配任务；已受派和已取消任务不会重复排班'); return }
    const days = targetRows.map(task => task.inspection_date).sort()
    if (sessionStore.campusRuntime?.scheduling) {
      if (targetRows.some(task => !task.group_id || !task.college_id)) {
        throw new Error('待排任务包含尚未明确执行组的旧任务，请先处理组织归属')
      }
      const groups = new Map<string, InspectionTaskItem[]>()
      for (const task of targetRows) groups.set(task.group_id!, [...(groups.get(task.group_id!) || []), task])
      let count = 0, unassigned = 0, stopped = false
      for (const [groupId, rows] of groups) {
        if (!current()) { stopped = true; break }
        const result = await confirmGroupPlan(rows[0]!.college_id!, groupId, {
          semester_id: semesterId, task_ids: rows.map(task => task.id)
        }, { scopeLabel: `${scopeLabel}；本轮共${targetRows.length}项，分${groups.size}个组确认`,
          tasks: rows, isCurrent: current })
        if (!result) { stopped = true; break }
        count += result.assigned_count
        unassigned += result.unassigned_count
      }
      ElMessage.info(`本次实际派发 ${count} 项，已确认计划中未分配 ${unassigned} 项。${stopped ? '其余计划未确认，未派发。' : '已有受派保持不变。'}`)
    } else {
      await ElMessageBox.confirm(`${scopeLabel}：${targetRows.length}项，日期 ${days[0]} 至 ${days[days.length - 1]}。\n系统遵循资格、课程/任务冲突、本班回避及日周上限；已受派任务保持不变。`, '智能自动排班范围确认', {
        confirmButtonText: '执行此范围排班', cancelButtonText: '返回调整', type: 'info', closeOnClickModal: false
      })
      if (!current()) return
      const result = await triggerAutoAssign({ semester_id: semesterId, task_ids: targetRows.map(task => task.id) })
      ElMessage.info(`实际派发 ${result.assigned_count} 项，未分配 ${result.unassigned_count} 项`)
    }
    if (current()) { selectedTaskIds.value = []; await fetchTasks() }
  } catch (error) {
    if (current() && error !== 'cancel' && error !== 'close') {
      ElMessage.error(error instanceof Error ? error.message : '自动排班失败，请重新预览')
    }
  } finally { autoAssigning.value = false }
}

// ==================== 导出排班表（CSV / Excel 兼容） ====================
async function handleExportTasks() {
  const exportContext = JSON.stringify(taskQuery())
  const owner = deletionContext()
  let exportRows: InspectionTaskItem[]
  try {
    const result = await exportTasks(taskQuery())
    if (exportContext !== JSON.stringify(taskQuery()) || owner !== deletionContext()) return
    exportRows = result.items
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '导出失败'); return }
  if (exportRows.length === 0) {
    ElMessage.warning('当前暂无可导出的排班任务')
    return
  }
  const headers = ['任务编号', '查课日期', '周次', '节次', '课程名称', '教学班级', '查课教室', '受派志愿者', '任务状态']
  const rows = exportRows.map(t => {
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
      `第${t.week_no ?? sessionStore.currentWeekNo}周`,
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
  ElMessage.success(`成功导出 ${exportRows.length} 条查课排班记录！`)
}

// ==================== 人工指派志愿者（支持按姓名搜索本学期已有志愿者） ====================
const assignDialogVisible = ref(false)
const assigningTask = ref<InspectionTaskItem | null>(null)
const assignVolunteers = ref<SemesterVolunteerItem[]>([])
const assignCandidateVolunteers = ref<TaskCandidateVolunteerItem[]>([])
const loadingVolunteers = ref(false)
const loadingCandidates = ref(false)
const selectedVolunteerUserId = ref<string>('')
const assignReason = ref('')
const assignSubmitting = ref(false)
const rejectSubmitting = ref(false)

const selectedVolunteer = computed(() => {
  const fromCand = assignCandidateVolunteers.value.find(v => v.user_id === selectedVolunteerUserId.value)
  if (fromCand) return fromCand
  return assignVolunteers.value.find(v => v.user_id === selectedVolunteerUserId.value)
})

const selectedVolunteerCandidate = computed(() => {
  return assignCandidateVolunteers.value.find(v => v.user_id === selectedVolunteerUserId.value)
})

async function handleOpenAssignDialog(task: InspectionTaskItem) {
  assigningTask.value = task
  assignReason.value = ''
  const curUid = (task as any).assignment?.volunteer_user_id || task.assigned_volunteer_id
  selectedVolunteerUserId.value = curUid ? String(curUid) : ''
  assignCandidateVolunteers.value = []
  assignDialogVisible.value = true

  loadingCandidates.value = true
  try {
    const [cands, allVols] = await Promise.all([
      listTaskCandidateVolunteers(task.id).catch(() => []),
      sessionStore.currentSemesterId ? listSemesterVolunteers(sessionStore.currentSemesterId).catch(() => []) : []
    ])
    assignCandidateVolunteers.value = cands || []
    assignVolunteers.value = allVols || []
  } catch (e) {
    console.error('加载候选人员失败:', e)
  } finally {
    loadingCandidates.value = false
  }
}

function autoPickRecommendedVolunteer() {
  const curUid = (assigningTask.value as any)?.assignment?.volunteer_user_id
  const best = assignCandidateVolunteers.value.find(v => v.eligible && v.user_id !== curUid)
  if (best) {
    selectedVolunteerUserId.value = best.user_id
    ElMessage.success(`已为您推荐选中【${best.name}】（本周已排 ${best.assigned_count_week || 0} 节，无课表/回避冲突）`)
  } else {
    ElMessage.warning('当前暂无完全无冲突的空闲志愿者，请手动挑选或联系协调')
  }
}

async function handleRejectChangeRequest() {
  if (!assigningTask.value) return
  const crId = (assigningTask.value as any).assignment?.change_request_id
  if (!crId) {
    ElMessage.warning('未获取到调班申请记录')
    return
  }
  try {
    const { value: comment } = await ElMessageBox.prompt('请输入驳回原因（选填，将反馈给志愿者）：', '驳回换班申请', {
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：近期人员紧张，请按时出勤或自行协商'
    })
    rejectSubmitting.value = true
    await reviewChangeRequest(crId, { decision: 'REJECTED', comment: comment || '管理员驳回调班申请' })
    ElMessage.success('已驳回该志愿者的调班申请')
    assignDialogVisible.value = false
    await fetchTasks()
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err?.message || '驳回失败')
    }
  } finally {
    rejectSubmitting.value = false
  }
}

async function handleConfirmAssign() {
  if (!assigningTask.value) return
  if (!selectedVolunteerUserId.value) {
    ElMessage.warning('请选择受派志愿者')
    return
  }
  const isChangeReq = (assigningTask.value as any).assignment?.change_request_status === 'PENDING'
  assignSubmitting.value = true
  try {
    const assigned = assigningTask.value.group_id ? await confirmGroupAssignment(assigningTask.value, selectedVolunteerUserId.value, assignReason.value) : await assignTask(assigningTask.value.id, {
      volunteer_user_id: selectedVolunteerUserId.value,
      lock_version: assigningTask.value.lock_version || 0,
      reason: assignReason.value || (isChangeReq ? '管理员同意调班并完成改派' : '管理端人工指派志愿者')
    })
    if (!assigned) return
    const vol = selectedVolunteer.value
    if (assigned.operation_warning_codes?.length) ElMessage.warning(assignmentWarnings(assigned.operation_warning_codes))
    if (isChangeReq) {
      ElMessage.success(`调班申请审批通过！任务 #${assigningTask.value.id} 已成功改派给【${vol?.name || '志愿者'}】！`)
    } else {
      ElMessage.success(`成功将任务 #${assigningTask.value.id} 指派给志愿者【${vol?.name || '志愿者'}】！`)
    }
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

// ==================== 编辑任务弹窗（方式 A，整合停课免计） ====================
const editDialogVisible = ref(false)
const periodLimit = computed(() => sessionStore.campusRuntime?.scheduling ? 60 : 6)
const periodOptions = computed(() => sessionStore.campusRuntime?.scheduling
  ? Array.from({ length: 60 }, (_, i) => ({ value: i + 1, label: `第 ${i + 1} 节` }))
  : PERIOD_PRESET_OPTIONS)
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
const showCancelSectionInEdit = ref(false)
const cancelPresetReason = ref('教师临时请假/停课')
const cancelCustomReason = ref('')
const cancelSubmitting = ref(false)

function onPeriodPresetChange(val: number) {
  if (val > 0) {
    editForm.value.start_period = val
    editForm.value.end_period = val
  }
}

function openEditTask(task: InspectionTaskItem) {
  editingTask.value = task
  showCancelSectionInEdit.value = false
  cancelPresetReason.value = '教师临时请假/停课'
  cancelCustomReason.value = ''
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

function onPresetReasonChange() {
  if (cancelPresetReason.value !== 'CUSTOM') {
    cancelCustomReason.value = ''
  }
}

async function handleConfirmCancelFromEdit() {
  if (!editingTask.value) return
  const finalReason = cancelPresetReason.value === 'CUSTOM'
    ? cancelCustomReason.value.trim()
    : cancelPresetReason.value
  if (!finalReason) {
    ElMessage.warning('请输入具体的停课/免计原因')
    return
  }
  cancelSubmitting.value = true
  try {
    await cancelTask(editingTask.value.id, {
      reason: finalReason,
      lock_version: editingTask.value.lock_version || 0
    })
    ElMessage.success(`任务 #${editingTask.value.id} 已成功标记为「已取消（${finalReason}）」，不计入本周考勤统计！`)
    editDialogVisible.value = false
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

    <el-alert v-if="needsAttention" :title="`正在查看本学期${needsAttention === 'unassigned' ? '未排班' : '待核对名单'}任务，共 ${attentionTotal} 条；本视图不受顶部周次限制。`" type="info" :closable="false" />


    <!-- 统计分栏 -->
    <div class="stat-row">
      <div class="stat-cell">
        <div class="label">{{ needsAttention ? '全部待办任务' : '本周计划总任务' }}</div>
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
        <div class="label">已完成查课</div>
        <div class="value font-mono" style="color: var(--blue)">{{ stats.reviewed }}</div>
        <div class="note">考勤结果已生效</div>
      </div>
    </div>

    <AutoChangePolicyCard
      v-if="canConfigureAutoChange && sessionStore.currentSemester?.status === 'ACTIVE'"
      :college-id="sessionStore.workspaceCollegeId"
      :college-name="sessionStore.workspace?.name || '当前学院'"
      :semester-id="sessionStore.currentSemesterId"
      :semester-name="sessionStore.currentSemesterName"
      :context-key="autoChangeContextKey"
      :available="canConfigureAutoChange"
    />

    <!-- 换班申请待处理提醒条 -->
    <div v-if="pendingChangeRequestsCount > 0" class="cr-alert-bar">
      <div class="cr-alert-left">
        <span class="cr-badge font-mono">{{ pendingChangeRequestsCount }}</span>
        <span>本周有 <strong>{{ pendingChangeRequestsCount }}</strong> 堂查课任务收到志愿者【换班申请】，请及时审批或改派顶班人员。</span>
      </div>
      <button
        class="btn btn-sm"
        :class="filterOnlyChangeRequests ? 'btn-primary' : 'btn-ghost'"
        @click="filterOnlyChangeRequests = !filterOnlyChangeRequests"
      >
        {{ filterOnlyChangeRequests ? '查看全部任务' : '仅看调班申请' }}
      </button>
    </div>

    <el-checkbox v-model="deletedOnly">查看已删除任务（历史保留）</el-checkbox>
    <!-- 任务表 -->
    <div class="tbl-wrap">
      <div class="tbl-head">
        <div class="tbl-head-title">
          <h3>任务总览（共 {{ attentionTotal }} 条）</h3>
          <div class="meta">按检查日期与节次排序 · 数据库真实数据</div>
        </div>
        <div class="tbl-tools">
          <input
            v-model="searchQuery"
            type="text"
            class="input search-input"
            placeholder="搜索课程 / 班级 / 教室…"
          />
          <select v-model="selectedDayFilter" class="input day-filter-select">
            <option value="ALL">本周全部 ({{ summary.total }} 节查课)</option>
            <option v-for="d in weekDayOptions" :key="d.value" :value="d.value">{{ d.label }}</option>
          </select>
          <select v-model="selectedStatus" class="input status-select">
            <option value="">全部状态</option>
            <option value="待执行">待执行</option>
            <option value="未分配">未分配</option>
            <option value="已逾期">已逾期</option>
            <option value="已取消">已取消</option>
            <option value="已完成">已完成</option>
          </select>
          <button
            class="btn btn-sm btn-primary inline-flex items-center gap-1 shadow-sm flex-shrink-0"
              :disabled="autoAssigning || deletedOnly"
            title="对当前筛选下全部分页的未分配任务生成计划，不局限本页50条"
            @click="handleAutoAssign('filtered')"
          >
            <AppIcon name="sparkles" :size="13" class="t-amber" />
            <span>{{ autoAssigning ? '排班中…' : '智能排班（筛选全部）' }}</span>
          </button>
          <button v-if="selectedTaskIds.length" class="btn btn-sm btn-ghost" :disabled="autoAssigning || deletedOnly"
            title="仅处理本页已勾选且尚未分配的任务" @click="handleAutoAssign('selected')">排班已选（{{ selectedTaskIds.length }}）</button>
          <button
            class="btn btn-sm btn-danger inline-flex items-center gap-1 flex-shrink-0"
              :disabled="selectedTaskIds.length === 0 || deletedOnly"
            @click="handleBatchDelete"
          >
            <AppIcon name="trash" :size="13" />
            <span>批量删除{{ selectedTaskIds.length > 0 ? ` (${selectedTaskIds.length})` : '' }}</span>
          </button>
          <button
            class="btn btn-sm btn-outline inline-flex items-center gap-1 flex-shrink-0"
            :disabled="filteredTasks.length === 0"
            title="将当前周或筛选出的查课任务与受派人员导出为表格"
            @click="handleExportTasks"
          >
            <AppIcon name="download" :size="13" />
            <span>导出筛选结果</span>
          </button>
          <button class="btn btn-sm flex-shrink-0" @click="fetchTasks">⟳ 刷新</button>
        </div>
      </div>

      <div v-if="filteredTasks.length > 0" class="tbl-scroll overflow-x-auto w-full">
        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 38px; text-align: center">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  :indeterminate="isIndeterminate"
                  class="chk"
                  title="全选 / 取消全选"
                  @change="toggleSelectAll"
                />
              </th>
              <th style="width: 210px">时间与地点</th>
              <th style="width: 260px">课程与教学班</th>
              <th style="width: 130px">班主任</th>
              <th style="width: 150px">受派志愿者</th>
              <th style="width: 95px">状态</th>
              <th style="width: 310px; text-align: right">操作</th>
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
              <td>
                <div
                  class="cell-main font-medium"
                  :title="`${formatTaskDateWithWeekday(task.inspection_date)} ${formatPeriodText(task.start_period, task.end_period)}`"
                >
                  {{ formatTaskDateWithWeekday(task.inspection_date) }} {{ formatPeriodText(task.start_period, task.end_period) }}
                </div>
                <div class="cell-sub" :title="task.classroom_snapshot || ''">
                  {{ task.classroom_snapshot || '未指定教室' }}
                </div>
              </td>
              <td>
                <div class="cell-main" :title="task.course_name_snapshot || ''">{{ task.course_name_snapshot || '—' }}</div>
                <div class="cell-sub flex items-center gap-1.5 flex-wrap">
                  <span>{{ task.class_name_snapshot || '—' }}</span>
                  <span
                    v-if="task.effective_teacher || task.teacher_name_snapshot"
                    class="chip-blue font-normal"
                    :title="task.head_teacher && (task.effective_teacher === task.head_teacher) ? '优先采用班主任兜底呈现' : '任课教师'"
                  >
                    {{ task.effective_teacher || task.teacher_name_snapshot }}
                  </span>
                </div>
              </td>
              <td>
                <div class="cell-main font-medium t-ink">
                  {{ task.head_teacher || '—' }}
                </div>
                <div
                  v-if="task.counselor"
                  class="cell-sub text-xs t-blue mt-0.5 truncate max-w-[130px]"
                  :title="`责任区辅导员: ${task.counselor}`"
                >
                  辅导员: {{ task.counselor }}
                </div>
              </td>
              <td>
                <template v-if="(task as any).assignment?.volunteer_user_id || task.assigned_volunteer_id">
                  <div class="cell-main font-bold t-ink">
                    {{ (task as any).assignment?.volunteer_name || task.assigned_volunteer_name || '志愿者' }}
                  </div>
                  <div
                    v-if="(task as any).assignment?.volunteer_class_name"
                    class="cell-sub text-xs t-mute truncate"
                    :title="(task as any).assignment?.volunteer_class_name"
                  >
                    {{ (task as any).assignment.volunteer_class_name }}
                  </div>
                  <div v-else class="cell-sub text-xs t-mute">
                    已指派
                  </div>
                  <!-- 换班申请待处理高亮标签 -->
                  <div
                    v-if="(task as any).assignment?.change_request_status === 'PENDING'"
                    class="mt-1"
                  >
                    <span
                      class="tag tag-amber cursor-pointer"
                      :title="`志愿者申请调班：${(task as any).assignment?.change_request_reason || '未填写理由'}`"
                      @click="handleOpenAssignDialog(task)"
                    >
                      ⚠️ 申请调班
                    </span>
                    <div
                      v-if="(task as any).assignment?.change_request_reason"
                      class="text-xs t-amber truncate max-w-[135px] mt-0.5"
                      :title="(task as any).assignment?.change_request_reason"
                    >
                      {{ (task as any).assignment.change_request_reason }}
                    </div>
                  </div>
                </template>
                <template v-else>
                  <div class="unassigned t-mute">未分配</div>
                  <div class="cell-sub cell-mono text-xs t-mute">可人工指定</div>
                </template>
              </td>
              <td>
                <TaskStatusTag :status="task.status" :deadline-assessment="task.deadline_assessment" />
                <el-tag v-if="task.roster_review_required || task.expected_count_review_required" type="warning">学籍异动待复核</el-tag>
                <div
                  v-if="task.cancel_reason"
                  class="cell-sub text-xs t-amber mt-1 max-w-[140px] truncate"
                  :title="task.cancel_reason"
                >
                  停课: {{ task.cancel_reason }}
                </div>
              </td>
              <td style="text-align: right; white-space: nowrap">
                <div class="inline-flex items-center justify-end gap-1 flex-nowrap">
                  <el-button v-if="task.deleted_at" link @click="handleRestoreDeleted(task)">恢复到日常列表</el-button>
                  <template v-else>
                  <button
                    class="btn btn-action"
                    :style="(task as any).assignment?.change_request_status === 'PENDING' ? 'background: var(--amber); color: var(--paper); border-color: var(--amber); font-weight: 600;' : ''"
                    @click="handleOpenAssignDialog(task)"
                  >
                    {{ (task as any).assignment?.change_request_status === 'PENDING' ? '处理调班' : ((task as any).assignment || task.assigned_volunteer_id ? '改派' : '人工指派') }}
                  </button>
                  <button
                    v-if="task.status !== '已取消' && task.status !== 'CANCELLED' && task.status !== '已完成' && task.status !== 'REVIEWED'"
                    class="btn btn-ghost btn-action inline-flex items-center gap-1"
                    @click="openEditTask(task)"
                  >
                    <AppIcon name="edit" :size="12" />
                    <span>编辑</span>
                  </button>
                  <button
                    class="btn btn-ghost btn-action t-blue inline-flex items-center gap-1"
                    title="展开查课任务详情与点名册卡片"
                    @click="openTaskDetail(task)"
                  >
                    <AppIcon name="file-text" :size="12" />
                    <span>详情与点名册</span>
                  </button>
                  <button
                    class="btn btn-ghost btn-action t-accent inline-flex items-center gap-1"
                    title="删除此查课任务"
                    @click="handleDeleteSingleTask(task)"
                  >
                    <AppIcon name="trash" :size="12" />
                    <span>删除</span>
                  </button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:current-page="attentionPage" :total="attentionTotal" />
      </div>

      <div v-else class="empty-box empty-state">
        <AppIcon name="folder-open" :size="32" class="e-icon" />
        <div class="e-main">当前周次（第 {{ sessionStore.currentWeekNo }} 周）暂无查课任务</div>
        <div class="e-sub">您可以前往「01 课次勾选与下发」下发任务，或切换学期/周次</div>
      </div>
    </div>

    <!-- 弹窗 1：人工指派 / 处理调班志愿者 -->
    <el-dialog
      v-model="assignDialogVisible"
      :title="((assigningTask as any)?.assignment?.change_request_status === 'PENDING' ? '处理调班申请 · 任务 #' : '人工指派志愿者 · 任务 #') + (assigningTask?.id || '')"
      width="640px"
      :lock-scroll="false"
      destroy-on-close
    >
      <div v-loading="assignSubmitting || rejectSubmitting" class="assign-dialog-body">
        <!-- 换班申请详情卡片 -->
        <div
          v-if="(assigningTask as any)?.assignment?.change_request_status === 'PENDING'"
          class="change-req-card"
        >
          <div class="cr-head">
            <span class="tag font-bold" style="background: var(--amber-soft); color: var(--amber); border: 1px solid var(--amber);">
              ⚠️ 志愿者发起换班申请
            </span>
            <span class="font-mono text-xs t-mute">
              {{ (assigningTask as any)?.assignment?.change_request_at ? formatBeijingTime((assigningTask as any)?.assignment?.change_request_at, 'minute') : '' }}
            </span>
          </div>
          <div class="cr-body">
            <div class="cr-row">
              <span class="cr-label">原受派人：</span>
              <span class="font-bold t-ink">{{ (assigningTask as any)?.assignment?.volunteer_name || '原志愿者' }}</span>
              <span class="text-xs t-mute font-mono">
                ({{ (assigningTask as any)?.assignment?.volunteer_student_no || '—' }} · {{ (assigningTask as any)?.assignment?.volunteer_class_name || '未分班' }})
              </span>
            </div>
            <div class="cr-row" style="margin-top: 6px;">
              <span class="cr-label">申请理由：</span>
              <span class="cr-reason-text">
                {{ (assigningTask as any)?.assignment?.change_request_reason || '（志愿者未填写具体说明）' }}
              </span>
            </div>
          </div>
        </div>

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
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <label class="form-label font-bold" style="font-size: var(--text-sm); margin: 0;">
              {{ (assigningTask as any)?.assignment?.change_request_status === 'PENDING' ? '选择顶班 / 新受派志愿者：' : '选择受派志愿者：' }}
            </label>
            <button
              type="button"
              class="btn btn-ghost btn-sm inline-flex items-center gap-1 font-bold"
              style="color: var(--blue);"
              title="自动为您挑选无课表冲突、符合本班回避、且本周任务最少的空闲志愿者"
              @click="autoPickRecommendedVolunteer"
            >
              <span>⚡ 智能推荐可用志愿者</span>
            </button>
          </div>
          <el-select
            v-model="selectedVolunteerUserId"
            filterable
            placeholder="输入志愿者姓名、学号或行政班级快速搜索…"
            style="width: 100%"
            :loading="loadingCandidates || loadingVolunteers"
            no-data-text="本学期暂无启用的志愿者，可先在「人员资质」中添加"
          >
            <el-option
              v-for="v in (assignCandidateVolunteers.length > 0 ? assignCandidateVolunteers : assignVolunteers)"
              :key="v.user_id"
              :label="`${v.name} (${v.student_no} · ${v.class_name || '未分班'})`"
              :value="v.user_id"
              :disabled="'eligible' in v && !(v as any).eligible && v.user_id !== selectedVolunteerUserId"
            >
              <div class="vol-option-row">
                <div>
                  <span class="vol-option-name" :class="{ 't-mute': 'eligible' in v && !(v as any).eligible }">{{ v.name }}</span>
                  <span class="vol-option-sub font-mono">{{ v.student_no }} · {{ v.class_name || '未分班' }}</span>
                </div>
                <div class="vol-option-tags">
                  <template v-if="'eligible' in v">
                    <span v-if="(v as any).eligible" class="tag tag-green tag-mini">✅ 可派 (本周{{ (v as any).assigned_count_week || 0 }}节)</span>
                    <span v-else class="tag tag-red tag-mini" :title="(v as any).conflict_message || ''">❌ {{ (v as any).conflict_message || '不可选' }}</span>
                    <span v-if="v.warning_codes?.length" class="tag tag-mini">{{ assignmentWarnings(v.warning_codes) }}</span>
                  </template>
                  <template v-else>
                    <span v-if="v.has_wechat" class="tag tag-green tag-mini">微信已绑定</span>
                    <span v-else class="tag tag-blue tag-mini">账号就绪</span>
                  </template>
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
              {{ selectedVolunteer.class_name || '行政班未分配' }}
            </div>
          </div>
          <div class="vol-status-badge">
            <span v-if="selectedVolunteerCandidate && selectedVolunteerCandidate.eligible" class="tag tag-green">
              ✅ 无冲突可派 · 本周已排 {{ selectedVolunteerCandidate.assigned_count_week || 0 }} 节
            </span>
            <span v-else-if="selectedVolunteer.has_wechat" class="tag tag-green">微信已登录绑定</span>
            <span v-else class="tag tag-blue">账号就绪 · 可直接排班</span>
          </div>
        </div>

        <!-- 改派说明 -->
        <div class="form-group" style="margin-top: 14px;">
          <label class="form-label" style="display: block; margin-bottom: 6px; font-size: var(--text-xs); color: var(--ink-soft);">
            审批 / 改派说明（审计备查，选填）：
          </label>
          <input
            v-model="assignReason"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            :placeholder="(assigningTask as any)?.assignment?.change_request_status === 'PENDING' ? '例如：同意调班申请，改派空闲志愿者顶替' : '例如：任课老师调整时段改派、原志愿者请假人工调换'"
          />
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
          <div>
            <button
              v-if="(assigningTask as any)?.assignment?.change_request_status === 'PENDING'"
              class="btn btn-ghost"
              style="color: var(--accent); border-color: var(--accent-soft);"
              :disabled="rejectSubmitting || assignSubmitting"
              @click="handleRejectChangeRequest"
            >
              {{ rejectSubmitting ? '正在处理…' : '驳回申请 (维持原状)' }}
            </button>
          </div>
          <div style="display: flex; gap: 10px;">
            <button class="btn btn-ghost" @click="assignDialogVisible = false">取消</button>
            <button
              class="btn btn-primary"
              :disabled="assignSubmitting || !selectedVolunteerUserId || ((assigningTask as any)?.assignment?.change_request_status === 'PENDING' && selectedVolunteerUserId === (assigningTask as any)?.assignment?.volunteer_user_id)"
              @click="handleConfirmAssign"
            >
              {{ assignSubmitting ? '处理中…' : ((assigningTask as any)?.assignment?.change_request_status === 'PENDING' ? '同意调班并改派' : '确认指派') }}
            </button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2：编辑查课任务弹窗（方式 A） -->
    <el-dialog
      v-model="editDialogVisible"
      :title="`编辑查课任务 #${editingTask?.id || ''}`"
      width="480px"
      :lock-scroll="false"
      destroy-on-close
    >
      <div v-loading="editSubmitting" class="edit-dialog-body">
        <p style="font-size: var(--text-xs); color: var(--ink-mute); margin-bottom: 16px;">
          直接调整当天的查课任务信息（如任课老师临时调换教室或节次变更）。修改后将实时同步至志愿者的查课小程序端。
        </p>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: var(--text-xs); font-weight: 600; margin-bottom: 6px;">教室地点：</label>
          <input
            v-model="editForm.classroom"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：教学楼 3-203"
          />
        </div>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: var(--text-xs); font-weight: 600; margin-bottom: 6px;">课程节次时段：</label>
          <el-select v-model="editPeriodPreset" @change="onPeriodPresetChange" style="width: 100%;">
            <el-option
              v-for="opt in periodOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
            <el-option :value="0" label="自定义起止节次 (连堂课/跨时段)" />
          </el-select>
        </div>

        <div v-if="editPeriodPreset === 0" style="display: flex; gap: 12px; margin-bottom: 14px;">
          <div style="flex: 1;">
            <label style="display: block; font-size: var(--text-xs); font-weight: 600; margin-bottom: 6px;">开始节次（1–{{ periodLimit }}）：</label>
            <el-input-number v-model="editForm.start_period" :min="1" :max="periodLimit" style="width: 100%;" />
          </div>
          <div style="flex: 1;">
            <label style="display: block; font-size: var(--text-xs); font-weight: 600; margin-bottom: 6px;">结束节次（1–{{ periodLimit }}）：</label>
            <el-input-number v-model="editForm.end_period" :min="editForm.start_period" :max="periodLimit" style="width: 100%;" />
          </div>
        </div>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: var(--text-xs); font-weight: 600; margin-bottom: 6px;">课程名称（快照）：</label>
          <input
            v-model="editForm.course_name"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：高等数学A"
          />
        </div>

        <div style="margin-bottom: 14px;">
          <label style="display: block; font-size: var(--text-xs); font-weight: 600; margin-bottom: 6px;">修改原因（审计备查）：</label>
          <input
            v-model="editForm.reason"
            type="text"
            class="input"
            style="width: 100%; box-sizing: border-box;"
            placeholder="例如：任课教师申请临时调换教室"
          />
        </div>

        <!-- 停课免计整合操作区 -->
        <div class="mt-4 pt-3 border-t border-[var(--line)]">
          <div v-if="editingTask?.status === '已取消' || editingTask?.status === 'CANCELLED'" class="note-box flex items-center gap-2">
            <AppIcon name="info" :size="14" class="t-amber shrink-0" />
            <span>当前任务已标记为停课免计（原因：{{ editingTask?.cancel_reason || '未备注' }}）</span>
          </div>
          <div v-else>
            <div class="flex items-center justify-between">
              <div>
                <span class="text-xs font-bold t-amber flex items-center gap-1">
                  <AppIcon name="slash" :size="13" class="t-amber" />
                  停课 / 特殊免计
                </span>
                <p class="meta mt-0.5">
                  若本节课教师临时请假或班级外出，可直接标记为停课免计（不计入到课率与考勤统计）。
                </p>
              </div>
              <button
                v-if="!showCancelSectionInEdit"
                type="button"
                class="btn btn-outline btn-xs t-amber"
                @click="showCancelSectionInEdit = true"
              >
                办理停课免计
              </button>
            </div>

            <div v-if="showCancelSectionInEdit" class="warn-box space-y-2.5 mt-2.5">
              <div>
                <label class="form-label">选择停课 / 免查原因 *</label>
                <select v-model="cancelPresetReason" class="input w-full text-xs" @change="onPresetReasonChange">
                  <option value="教师临时请假/停课">教师临时请假 / 停课</option>
                  <option value="班级外出实训/活动免查">班级外出实训 / 活动免查</option>
                  <option value="教室设备故障/停电">教室设备故障 / 停电</option>
                  <option value="教务处临时调整免查">教务处临时调整免查</option>
                  <option value="CUSTOM">其他原因（自定义输入）</option>
                </select>
              </div>
              <div v-if="cancelPresetReason === 'CUSTOM'">
                <label class="form-label">自定义原因说明 *</label>
                <input
                  v-model="cancelCustomReason"
                  type="text"
                  class="input w-full text-xs"
                  placeholder="请输入具体停课免计原因"
                />
              </div>
              <div class="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  class="btn btn-ghost btn-xs t-mute"
                  @click="showCancelSectionInEdit = false"
                >
                  收起
                </button>
                <button
                  type="button"
                  class="btn btn-sm btn-accent"
                  :disabled="cancelSubmitting"
                  @click="handleConfirmCancelFromEdit"
                >
                  {{ cancelSubmitting ? '正在标记…' : '确认标记停课免计' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button class="btn btn-ghost" @click="editDialogVisible = false">取消</button>
          <button class="btn btn-primary" :disabled="editSubmitting || cancelSubmitting" @click="handleUpdateTask">
            {{ editSubmitting ? '保存中…' : '保存修改' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <TaskDrawer
      v-model:visible="drawerVisible"
      :task="activeTask"
      @reassign="handleOpenAssignDialog"
      @delete="handleDeleteSingleTask"
      @corrected="fetchTasks"
    />
  </div>
</template>

<style scoped>
.stat-row { margin-bottom: 16px; }
.tid { font-weight: 600; color: var(--blue); }
.unassigned { color: var(--amber); font-weight: 600; }

.tbl-head {
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
}
.tbl-head-title {
  flex-shrink: 0;
  min-width: 160px;
}
.tbl-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  flex-shrink: 0;
}
.search-input {
  width: 155px;
  min-width: 155px;
  max-width: 155px;
  box-sizing: border-box;
  flex-shrink: 0;
}
.day-filter-select {
  width: 195px;
  min-width: 195px;
  max-width: 195px;
  box-sizing: border-box;
  flex-shrink: 0;
  transition: border-color var(--dur-f) var(--ease);
}
.status-select {
  width: 95px;
  min-width: 95px;
  max-width: 95px;
  box-sizing: border-box;
  flex-shrink: 0;
}
.tbl {
  table-layout: fixed;
  width: 100%;
  min-width: 1180px;
}
.tbl thead th {
  padding: 10px 10px;
}
.tbl tbody td {
  padding: 12px 10px;
}
.btn-action {
  padding: 4px 8px !important;
  font-size: 12px !important;
  height: 28px;
  line-height: 1.4;
  box-sizing: border-box;
}
.cell-main, .cell-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chk {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--accent);
}

.row-selected {
  background-color: var(--green-soft) !important;
}

.btn-danger {
  background-color: var(--red);
  color: var(--paper);
  border: 1px solid var(--red);
}
.btn-danger:hover:not(:disabled) {
  background-color: var(--accent-dark);
}
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-box {
  padding: 60px 20px;
}

/* 任务指派弹窗样式 */
.task-info-card {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
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
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  gap: 12px;
}
.vol-avatar-badge {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--paper);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-lg);
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

/* 换班申请提示横幅与弹窗卡片 */
.cr-alert-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: var(--amber-soft);
  border: 1px solid var(--amber);
  border-left: 4px solid var(--amber);
  border-radius: var(--radius);
  margin-bottom: 14px;
}
.cr-alert-left {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--amber);
}
.cr-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: var(--amber);
  color: var(--paper);
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
}
.change-req-card {
  background: var(--amber-soft);
  border: 1px solid var(--amber);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  margin-bottom: 14px;
}
.cr-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.cr-body {
  font-size: 12px;
}
.cr-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.cr-label {
  color: var(--amber);
  flex-shrink: 0;
  font-weight: 600;
}
.cr-reason-text {
  background: var(--paper);
  border: 1px solid var(--line);
  padding: 4px 10px;
  border-radius: var(--radius-md);
  color: var(--amber);
  font-weight: 500;
  flex: 1;
}
</style>
