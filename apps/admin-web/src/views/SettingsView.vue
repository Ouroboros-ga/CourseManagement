<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listSemesters,
  createSemester,
  updateSemester,
  resetSemesterData,
  listPeriodDefinitions,
  upsertPeriodDefinition,
  deletePeriodDefinition,
  listCalendarOverrides,
  createCalendarOverride,
  deleteCalendarOverride,
  type SemesterItem,
  type PeriodDefinitionItem,
  type CalendarOverrideItem
} from '../api/academic'
import AppIcon from '../components/AppIcon.vue'

const sessionStore = useSessionStore()

const activeTab = ref<'semester' | 'periods' | 'rules'>('semester')
const loading = ref(false)

// ==================== 1. 学期管理 ====================
const semesters = ref<SemesterItem[]>([])
const selectedSemester = computed(() => {
  return semesters.value.find(s => s.id === sessionStore.currentSemesterId) || null
})

async function fetchSemesters() {
  try {
    const res = await listSemesters('')
    semesters.value = res.items || []
  } catch (err: unknown) {
    console.error('获取学期列表失败:', err)
  }
}

// 开启新学期弹窗
const showCreateSemesterDialog = ref(false)
const createSemesterSubmitting = ref(false)
const semesterCreateForm = ref({
  code: '',
  name: '',
  start_date: '',
  end_date: '',
  first_monday: '',
  total_weeks: 20,
  init_default_periods: true,
  reason: '管理端开启新学期'
})

function openCreateSemesterDialog() {
  const currentYear = new Date().getFullYear()
  semesterCreateForm.value = {
    code: `${currentYear}-${currentYear + 1}-1`,
    name: `${currentYear}-${currentYear + 1}学年第1学期`,
    start_date: `${currentYear}-09-01`,
    end_date: `${currentYear + 1}-01-31`,
    first_monday: `${currentYear}-09-07`,
    total_weeks: 20,
    init_default_periods: true,
    reason: '管理端新建学期'
  }
  showCreateSemesterDialog.value = true
}

async function handleCreateSemester() {
  if (!semesterCreateForm.value.code || !semesterCreateForm.value.name) {
    ElMessage.warning('请填写学期代码与学期全称')
    return
  }
  if (!semesterCreateForm.value.start_date || !semesterCreateForm.value.end_date || !semesterCreateForm.value.first_monday) {
    ElMessage.warning('请填写完整的学期起止日期和第一教学周周一')
    return
  }

  createSemesterSubmitting.value = true
  try {
    const newSem = await createSemester(semesterCreateForm.value)
    ElMessage.success(`学期【${newSem.name}】开启成功！标准节次定义已自动初始化`)
    showCreateSemesterDialog.value = false
    await fetchSemesters()
    await sessionStore.fetchAcademicContext()
    sessionStore.setSemester(newSem.id)
    if (activeTab.value === 'periods') {
      await fetchPeriods()
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '开启学期失败'
    ElMessage.error(msg)
  } finally {
    createSemesterSubmitting.value = false
  }
}

// 编辑学期信息弹窗
const showEditSemesterDialog = ref(false)
const editSemesterSubmitting = ref(false)
const semesterEditForm = ref({
  id: '',
  name: '',
  start_date: '',
  end_date: '',
  first_monday: '',
  total_weeks: 20,
  status: 'ACTIVE' as 'ACTIVE' | 'ARCHIVED'
})

function openEditSemesterDialog(sem?: SemesterItem) {
  const target = sem || selectedSemester.value
  if (!target) return
  semesterEditForm.value = {
    id: target.id,
    name: target.name,
    start_date: target.start_date || '',
    end_date: target.end_date || '',
    first_monday: target.first_monday || '',
    total_weeks: target.total_weeks || 20,
    status: target.status
  }
  showEditSemesterDialog.value = true
}

async function handleUpdateSemester() {
  if (!semesterEditForm.value.name.trim()) {
    ElMessage.warning('学期名称不能为空')
    return
  }
  editSemesterSubmitting.value = true
  try {
    await updateSemester(semesterEditForm.value.id, {
      name: semesterEditForm.value.name.trim(),
      start_date: semesterEditForm.value.start_date || undefined,
      end_date: semesterEditForm.value.end_date || undefined,
      first_monday: semesterEditForm.value.first_monday || undefined,
      total_weeks: semesterEditForm.value.total_weeks,
      status: semesterEditForm.value.status,
      reason: '管理端更新学期设置'
    })
    ElMessage.success('学期配置更新成功！')
    showEditSemesterDialog.value = false
    await fetchSemesters()
    await sessionStore.fetchAcademicContext()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '更新学期失败'
    ElMessage.error(msg)
  } finally {
    editSemesterSubmitting.value = false
  }
}

// 快速切换当前工作学期
function handleSwitchSemester(semId: string) {
  sessionStore.setSemester(semId)
  ElMessage.success(`已切换当前工作学期为：${sessionStore.currentSemesterName}`)
  fetchPeriods()
  fetchCalendarOverrides()
}

// 归档/解归档学期
async function handleToggleArchive(sem: SemesterItem) {
  const nextStatus = sem.status === 'ACTIVE' ? 'ARCHIVED' : 'ACTIVE'
  const actionText = nextStatus === 'ARCHIVED' ? '归档' : '恢复激活'
  try {
    await ElMessageBox.confirm(
      `确定将学期【${sem.name}】进行${actionText}操作吗？${nextStatus === 'ARCHIVED' ? '归档后日常查课将不再作为默认活跃学期。' : ''}`,
      `${actionText}学期确认`,
      {
        confirmButtonText: `确认${actionText}`,
        cancelButtonText: '取消',
        type: nextStatus === 'ARCHIVED' ? 'warning' : 'info'
      }
    )
    await updateSemester(sem.id, {
      status: nextStatus,
      reason: `管理员${actionText}学期`
    })
    ElMessage.success(`学期【${sem.name}】已成功${actionText}！`)
    await fetchSemesters()
    await sessionStore.fetchAcademicContext()
  } catch {}
}

// ==================== 高危：重置本学期业务数据 ====================
const showResetSemesterDialog = ref(false)
const resetConfirmName = ref('')
const resetSubmitting = ref(false)

function openResetSemesterDialog() {
  resetConfirmName.value = ''
  showResetSemesterDialog.value = true
}

async function handleResetSemesterData() {
  if (!sessionStore.currentSemesterId) return
  if (resetConfirmName.value.trim() !== (sessionStore.currentSemesterName || '').trim()) {
    ElMessage.warning(`输入的学期名称与当前学期名称【${sessionStore.currentSemesterName}】不一致，请核对`)
    return
  }

  resetSubmitting.value = true
  try {
    const res = await resetSemesterData(sessionStore.currentSemesterId, {
      confirm_name: resetConfirmName.value.trim(),
      reason: '管理员在平台设置模块重置本学期排课与任务业务数据'
    })
    ElMessageBox.alert(
      `学期业务数据重置成功！<br/><br/>
      1. <b>查课任务清理</b>：${res.cleared_tasks_count} 个<br/>
      2. <b>课表排课清理</b>：${res.cleared_schedules_count} 条<br/>
      3. <b>教学班选课清理</b>：${res.cleared_teaching_classes_count} 个<br/>
      4. <b>志愿者资质清理</b>：${res.cleared_volunteer_qualifications_count} 个<br/>
      <br/>当前学期已恢复初始空白状态，您现在可以在课表中心重新上传排课压缩包进行导入。`,
      '学期重置成功',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '确定'
      }
    )
    showResetSemesterDialog.value = false
    await sessionStore.fetchAcademicContext()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '重置学期数据失败'
    ElMessage.error(msg)
  } finally {
    resetSubmitting.value = false
  }
}

// ==================== 2. 校历停补课调度 ====================
const calendarOverrides = ref<CalendarOverrideItem[]>([])
const calendarLoading = ref(false)
const showCreateOverrideDialog = ref(false)
const overrideSubmitting = ref(false)
const overrideForm = ref({
  date: '',
  override_type: 'STOP' as 'STOP' | 'MAKEUP',
  source_teaching_week: 1,
  source_teaching_weekday: 1,
  reason: ''
})

async function fetchCalendarOverrides() {
  if (!sessionStore.currentSemesterId) return
  calendarLoading.value = true
  try {
    const res = await listCalendarOverrides(sessionStore.currentSemesterId)
    calendarOverrides.value = res.items || []
  } catch (err) {
    console.error('获取校历覆盖记录失败:', err)
  } finally {
    calendarLoading.value = false
  }
}

function openCreateOverrideDialog() {
  overrideForm.value = {
    date: '',
    override_type: 'STOP',
    source_teaching_week: 1,
    source_teaching_weekday: 1,
    reason: ''
  }
  showCreateOverrideDialog.value = true
}

async function handleCreateOverride() {
  if (!sessionStore.currentSemesterId) return
  if (!overrideForm.value.date) {
    ElMessage.warning('请选择执行日期')
    return
  }
  overrideSubmitting.value = true
  try {
    await createCalendarOverride(sessionStore.currentSemesterId, {
      date: overrideForm.value.date,
      override_type: overrideForm.value.override_type,
      source_teaching_week: overrideForm.value.override_type === 'MAKEUP' ? overrideForm.value.source_teaching_week : undefined,
      source_teaching_weekday: overrideForm.value.override_type === 'MAKEUP' ? overrideForm.value.source_teaching_weekday : undefined,
      reason: overrideForm.value.reason || undefined
    })
    ElMessage.success('校历停补课规则添加成功！')
    showCreateOverrideDialog.value = false
    await fetchCalendarOverrides()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '添加停补课规则失败'
    ElMessage.error(msg)
  } finally {
    overrideSubmitting.value = false
  }
}

async function handleDeleteOverride(item: CalendarOverrideItem) {
  if (!sessionStore.currentSemesterId) return
  try {
    await ElMessageBox.confirm(
      `确定删除【${item.date}】的校历${item.override_type === 'STOP' ? '停课' : '补课'}规则吗？`,
      '删除校历覆盖规则',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deleteCalendarOverride(sessionStore.currentSemesterId, item.id)
    ElMessage.success('已成功删除该校历规则')
    await fetchCalendarOverrides()
  } catch {}
}

// ==================== 3. 节次作息时间表 ====================
const periods = ref<PeriodDefinitionItem[]>([])
const periodsLoading = ref(false)
const showPeriodDialog = ref(false)
const periodSubmitting = ref(false)
const periodForm = ref({
  period_no: 1,
  start_time: '08:00',
  end_time: '08:45',
  reason: ''
})

async function fetchPeriods() {
  if (!sessionStore.currentSemesterId) return
  periodsLoading.value = true
  try {
    const res = await listPeriodDefinitions(sessionStore.currentSemesterId)
    // 按照 period_no 升序排列
    periods.value = (res.items || []).sort((a, b) => a.period_no - b.period_no)
  } catch (err) {
    console.error('获取节次定义失败:', err)
  } finally {
    periodsLoading.value = false
  }
}

function getPeriodSlotName(pNo: number): string {
  if (pNo <= 4) return '上午'
  if (pNo <= 8) return '下午'
  return '晚间'
}

function openEditPeriodDialog(p: PeriodDefinitionItem) {
  periodForm.value = {
    period_no: p.period_no,
    start_time: p.start_time ? p.start_time.slice(0, 5) : '08:00',
    end_time: p.end_time ? p.end_time.slice(0, 5) : '08:45',
    reason: ''
  }
  showPeriodDialog.value = true
}

function openCreatePeriodDialog() {
  const nextNo = periods.value.length > 0 ? Math.max(...periods.value.map(p => p.period_no)) + 1 : 1
  periodForm.value = {
    period_no: nextNo,
    start_time: '08:00',
    end_time: '08:45',
    reason: ''
  }
  showPeriodDialog.value = true
}

async function handleSavePeriod() {
  if (!sessionStore.currentSemesterId) return
  if (!periodForm.value.start_time || !periodForm.value.end_time) {
    ElMessage.warning('请选择起止时间')
    return
  }
  periodSubmitting.value = true
  try {
    const formatTime = (t: string) => t.length === 5 ? `${t}:00` : t
    await upsertPeriodDefinition(sessionStore.currentSemesterId, periodForm.value.period_no, {
      start_time: formatTime(periodForm.value.start_time),
      end_time: formatTime(periodForm.value.end_time),
      reason: periodForm.value.reason || '管理员设置节次作息'
    })
    ElMessage.success(`第 ${periodForm.value.period_no} 节作息时间已成功保存！`)
    showPeriodDialog.value = false
    await fetchPeriods()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '保存节次时间失败'
    ElMessage.error(msg)
  } finally {
    periodSubmitting.value = false
  }
}

async function handleDeletePeriod(p: PeriodDefinitionItem) {
  if (!sessionStore.currentSemesterId) return
  try {
    await ElMessageBox.confirm(
      `确定删除【第 ${p.period_no} 节】的作息定义吗？`,
      '删除节次定义',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deletePeriodDefinition(sessionStore.currentSemesterId, p.id)
    ElMessage.success(`第 ${p.period_no} 节作息定义已删除`)
    await fetchPeriods()
  } catch {}
}

// 一键初始化/重置标准 1-11 节作息
async function handleInitDefaultPeriods() {
  if (!sessionStore.currentSemesterId) return
  try {
    await ElMessageBox.confirm(
      '一键重置将根据高校标准作息表覆盖本学期第 1 至 11 节的上下课时间。确定继续吗？',
      '标准作息重置确认',
      { confirmButtonText: '确认重置', cancelButtonText: '取消', type: 'info' }
    )
    periodsLoading.value = true
    const standardPeriods = [
      { no: 1, start: '08:00:00', end: '08:45:00' },
      { no: 2, start: '08:50:00', end: '09:35:00' },
      { no: 3, start: '09:55:00', end: '10:40:00' },
      { no: 4, start: '10:45:00', end: '11:30:00' },
      { no: 5, start: '13:30:00', end: '14:15:00' },
      { no: 6, start: '14:20:00', end: '15:05:00' },
      { no: 7, start: '15:25:00', end: '16:10:00' },
      { no: 8, start: '16:15:00', end: '17:00:00' },
      { no: 9, start: '18:30:00', end: '19:15:00' },
      { no: 10, start: '19:20:00', end: '20:05:00' },
      { no: 11, start: '20:15:00', end: '21:00:00' }
    ]

    for (const sp of standardPeriods) {
      await upsertPeriodDefinition(sessionStore.currentSemesterId, sp.no, {
        start_time: sp.start,
        end_time: sp.end,
        reason: '一键写入高校标准作息定义'
      })
    }
    ElMessage.success('已成功写入高校标准 1–11 节作息时间表！')
    await fetchPeriods()
  } catch {} finally {
    periodsLoading.value = false
  }
}

watch(
  () => sessionStore.currentSemesterId,
  () => {
    fetchPeriods()
    fetchCalendarOverrides()
  }
)

onMounted(async () => {
  loading.value = true
  await fetchSemesters()
  await fetchPeriods()
  await fetchCalendarOverrides()
  loading.value = false
})
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>PLATFORM & SETTINGS</span>
        <em>●</em>
        <span>平台与学期设置</span>
        <em>●</em>
        <span>当前学期：{{ sessionStore.currentSemesterName || '未选中' }}</span>
      </div>
      <div class="head-row">
        <div>
          <h1>平台与学期设置</h1>
          <p class="sub">
            统一维护全校学期生命周期、教学日历、停补课调度、节次作息时刻表及查课业务全局规则。教师与管理员均可协同维护。
          </p>
        </div>

        <div class="head-tools">
          <button class="btn btn-dark" @click="openCreateSemesterDialog">
            <AppIcon name="plus" :size="14" />
            <span>开启新学期</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Tab 导航 -->
    <nav class="tab-nav">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'semester' }"
        @click="activeTab = 'semester'"
      >
        <AppIcon name="calendar" :size="14" />
        <span>学期与教学日历</span>
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'periods' }"
        @click="activeTab = 'periods'"
      >
        <AppIcon name="clock" :size="14" />
        <span>节次作息时间表</span>
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'rules' }"
        @click="activeTab = 'rules'"
      >
        <AppIcon name="shield" :size="14" />
        <span>查课业务规则</span>
      </button>
    </nav>

    <!-- Tab 1: 学期与教学日历 -->
    <main v-if="activeTab === 'semester'" class="tab-body space-y-6">
      <!-- 当前学期概览卡片 -->
      <div class="card p-5">
        <div class="flex items-start justify-between">
          <div>
            <div class="flex items-center gap-3">
              <h2 class="text-lg font-bold text-slate-800">{{ selectedSemester?.name || sessionStore.currentSemesterName }}</h2>
              <span
                class="tag"
                :class="selectedSemester?.status === 'ACTIVE' ? 'tag-green' : 'tag-muted'"
              >
                {{ selectedSemester?.status === 'ACTIVE' ? '当前激活运行中' : '已归档' }}
              </span>
            </div>
            <p class="text-xs text-slate-500 mt-1 font-mono">
              学期代码：{{ selectedSemester?.code || '—' }} |
              起止日期：{{ selectedSemester?.start_date || '—' }} ~ {{ selectedSemester?.end_date || '—' }} |
              第一教学周周一：{{ selectedSemester?.first_monday || '—' }} |
              总周数：{{ selectedSemester?.total_weeks || 20 }} 周
            </p>
          </div>

          <div class="flex items-center gap-2">
            <button class="btn btn-outline text-xs" @click="openEditSemesterDialog(selectedSemester || undefined)">
              <AppIcon name="edit" :size="12" />
              <span>编辑学期信息</span>
            </button>
          </div>
        </div>

        <div class="grid grid-cols-4 gap-4 mt-5 pt-4 border-t border-slate-100 text-center">
          <div class="bg-slate-50 rounded p-3">
            <div class="text-xs text-slate-500 mb-1">学期代码</div>
            <div class="text-sm font-mono font-bold text-slate-800">{{ selectedSemester?.code }}</div>
          </div>
          <div class="bg-slate-50 rounded p-3">
            <div class="text-xs text-slate-500 mb-1">总教学周</div>
            <div class="text-sm font-bold text-slate-800">{{ selectedSemester?.total_weeks }} 周</div>
          </div>
          <div class="bg-slate-50 rounded p-3">
            <div class="text-xs text-slate-500 mb-1">第一教学周周一</div>
            <div class="text-sm font-mono text-slate-800">{{ selectedSemester?.first_monday }}</div>
          </div>
          <div class="bg-slate-50 rounded p-3">
            <div class="text-xs text-slate-500 mb-1">生命周期状态</div>
            <div class="text-sm font-bold" :class="selectedSemester?.status === 'ACTIVE' ? 'text-emerald-700' : 'text-slate-500'">
              {{ selectedSemester?.status === 'ACTIVE' ? '运行中' : '已归档' }}
            </div>
          </div>
        </div>
      </div>

      <!-- 全校所有学期列表 -->
      <div class="card">
        <div class="card-header flex items-center justify-between p-4 border-b border-slate-100">
          <div>
            <h3 class="font-bold text-slate-800">全校学期总目录</h3>
            <p class="text-xs text-slate-500 mt-0.5">支持跨学期浏览、切换当前活跃学期以及学期归档处理。</p>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 160px;">学期代码</th>
                <th>学期全称</th>
                <th style="width: 140px;">起止日期</th>
                <th style="width: 100px;">总周数</th>
                <th style="width: 100px;">状态</th>
                <th style="width: 180px; text-align: right;">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="sem in semesters"
                :key="sem.id"
                :class="{ 'bg-blue-50/40': sem.id === sessionStore.currentSemesterId }"
              >
                <td class="font-mono font-semibold text-slate-700">{{ sem.code }}</td>
                <td class="font-medium text-slate-900">
                  <div class="flex items-center gap-2">
                    <span>{{ sem.name }}</span>
                    <span v-if="sem.id === sessionStore.currentSemesterId" class="tag tag-blue text-[11px] py-0 px-1.5">当前工作</span>
                  </div>
                </td>
                <td class="text-xs font-mono text-slate-600">{{ sem.start_date }} ~ {{ sem.end_date || '未设' }}</td>
                <td class="text-xs text-slate-700">{{ sem.total_weeks }} 周</td>
                <td>
                  <span class="tag" :class="sem.status === 'ACTIVE' ? 'tag-green' : 'tag-muted'">
                    {{ sem.status === 'ACTIVE' ? '正常' : '已归档' }}
                  </span>
                </td>
                <td style="text-align: right;">
                  <div class="action-links flex items-center justify-end gap-3">
                    <button
                      v-if="sem.id !== sessionStore.currentSemesterId"
                      class="btn-text text-blue-600 hover:text-blue-800 text-xs"
                      @click="handleSwitchSemester(sem.id)"
                    >
                      切换为此学期
                    </button>
                    <button
                      class="btn-text text-slate-600 hover:text-slate-800 text-xs"
                      @click="openEditSemesterDialog(sem)"
                    >
                      编辑
                    </button>
                    <button
                      class="btn-text text-xs"
                      :class="sem.status === 'ACTIVE' ? 'text-amber-600 hover:text-amber-800' : 'text-emerald-600 hover:text-emerald-800'"
                      @click="handleToggleArchive(sem)"
                    >
                      {{ sem.status === 'ACTIVE' ? '归档' : '解归档' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 校历停补课调度覆盖 -->
      <div class="card">
        <div class="card-header flex items-center justify-between p-4 border-b border-slate-100">
          <div>
            <h3 class="font-bold text-slate-800">校历节假日停课 / 调休补课调度</h3>
            <p class="text-xs text-slate-500 mt-0.5">
              用于中秋、国庆等节假日调休，或校运会全天停课。停课日排课课次将不计入当日查课抽检。
            </p>
          </div>
          <button class="btn btn-outline text-xs" @click="openCreateOverrideDialog">
            <AppIcon name="plus" :size="12" />
            <span>添加停补课规则</span>
          </button>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 140px;">执行日期</th>
                <th style="width: 120px;">规则类型</th>
                <th>调休上课规则</th>
                <th>说明备注</th>
                <th style="width: 100px; text-align: right;">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in calendarOverrides" :key="item.id">
                <td class="font-mono font-semibold text-slate-800">{{ item.date }}</td>
                <td>
                  <span class="tag" :class="item.override_type === 'STOP' ? 'tag-rose' : 'tag-blue'">
                    {{ item.override_type === 'STOP' ? '全天停课' : '调休补课' }}
                  </span>
                </td>
                <td class="text-xs text-slate-700">
                  <span v-if="item.override_type === 'MAKEUP'">
                    按第 {{ item.source_teaching_week }} 周 星期{{ item.source_teaching_weekday }} 课表执行
                  </span>
                  <span v-else class="text-slate-400">停课不调课</span>
                </td>
                <td class="text-xs text-slate-600">{{ item.reason || '—' }}</td>
                <td style="text-align: right;">
                  <button class="btn-text text-rose-600 hover:text-rose-800 text-xs" @click="handleDeleteOverride(item)">
                    删除
                  </button>
                </td>
              </tr>
              <tr v-if="calendarOverrides.length === 0">
                <td colspan="5" class="text-center py-6 text-slate-400 text-xs">
                  暂未配置本学期校历停补课覆盖规则
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 高危重置区 -->
      <div class="card border border-rose-200 bg-rose-50/20 p-5 rounded-lg">
        <div class="flex items-start justify-between">
          <div class="space-y-1">
            <div class="flex items-center gap-2 text-rose-700 font-bold text-base">
              <AppIcon name="alert" :size="18" />
              <span>学期业务数据清空与高危重置</span>
            </div>
            <p class="text-xs text-rose-600 leading-relaxed max-w-2xl">
              清空当前学期（{{ sessionStore.currentSemesterName }}）所有查课任务、课表排课节次、教学班及选课名单。
              底册学生名单、行政班级及公共课程库将<b>完整保留</b>。重置后学期变为空白，可在课表中心重新批量导入。
            </p>
          </div>
          <button
            class="btn bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs shrink-0"
            @click="openResetSemesterDialog"
          >
            <AppIcon name="trash" :size="13" />
            <span>重置本学期业务数据</span>
          </button>
        </div>
      </div>
    </main>

    <!-- Tab 2: 节次作息时间表 -->
    <main v-if="activeTab === 'periods'" class="tab-body space-y-4">
      <div class="card p-4">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h3 class="font-bold text-slate-800">节次作息时间表 (Period Definitions)</h3>
            <p class="text-xs text-slate-500 mt-0.5">
              定义当前学期各节次的上课与下课时刻。课表导入、点名任务生成与下发均以此时刻为时间锚点。
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button class="btn btn-outline text-xs" @click="handleInitDefaultPeriods">
              <AppIcon name="refresh" :size="12" />
              <span>一键恢复高校标准作息 (1–11节)</span>
            </button>
            <button class="btn btn-dark text-xs" @click="openCreatePeriodDialog">
              <AppIcon name="plus" :size="12" />
              <span>新增节次</span>
            </button>
          </div>
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 120px;">节次序号</th>
                <th style="width: 120px;">时段分类</th>
                <th style="width: 180px;">上课开始时刻</th>
                <th style="width: 180px;">下课结束时刻</th>
                <th>持续时长</th>
                <th style="width: 140px; text-align: right;">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in periods" :key="p.id">
                <td class="font-bold text-slate-800">第 {{ p.period_no }} 节</td>
                <td>
                  <span
                    class="tag"
                    :class="p.period_no <= 4 ? 'tag-blue' : (p.period_no <= 8 ? 'tag-amber' : 'tag-purple')"
                  >
                    {{ getPeriodSlotName(p.period_no) }}
                  </span>
                </td>
                <td class="font-mono text-sm font-semibold text-slate-700">
                  {{ p.start_time ? p.start_time.slice(0, 5) : '—' }}
                </td>
                <td class="font-mono text-sm font-semibold text-slate-700">
                  {{ p.end_time ? p.end_time.slice(0, 5) : '—' }}
                </td>
                <td class="text-xs text-slate-500 font-mono">
                  45 分钟标准学时
                </td>
                <td style="text-align: right;">
                  <div class="action-links flex items-center justify-end gap-3">
                    <button class="btn-text text-blue-600 hover:text-blue-800 text-xs" @click="openEditPeriodDialog(p)">
                      编辑作息
                    </button>
                    <button class="btn-text text-rose-600 hover:text-rose-800 text-xs" @click="handleDeletePeriod(p)">
                      删除
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="periods.length === 0">
                <td colspan="6" class="text-center py-8 text-slate-400 text-xs">
                  当前学期暂无节次作息定义，请点击上方“一键恢复高校标准作息”快速初始化。
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </main>

    <!-- Tab 3: 查课业务规则 -->
    <main v-if="activeTab === 'rules'" class="tab-body space-y-4">
      <div class="grid grid-cols-2 gap-4">
        <div class="card p-5">
          <div class="flex items-center gap-2.5 text-blue-800 font-bold mb-2">
            <AppIcon name="clock" :size="18" />
            <h3 class="text-base">每日查课提交截止规则 (Daily Submission Deadline)</h3>
          </div>
          <p class="text-xs text-slate-600 leading-relaxed mb-4">
            查课志愿者在现场考勤与拍照核验后，必须在每日设定时限前通过小程序提交查课记录。
          </p>
          <div class="bg-blue-50/60 rounded p-4 border border-blue-100 flex items-center justify-between">
            <div>
              <div class="text-xs text-slate-500 font-medium">全校默认查课提交截止时间</div>
              <div class="text-2xl font-mono font-bold text-blue-900 mt-1">22:00:00</div>
            </div>
            <span class="tag tag-blue">系统默认全局策略</span>
          </div>
          <div class="mt-3 text-[11px] text-slate-400">
            * 超过 22:00 提交的记录将被标记为【迟交】，并在次日早报与统计报表中予以提示。
          </div>
        </div>

        <div class="card p-5">
          <div class="flex items-center gap-2.5 text-amber-800 font-bold mb-2">
            <AppIcon name="sparkles" :size="18" />
            <h3 class="text-base">查课任务智能推荐策略 (Smart Sampling Policy)</h3>
          </div>
          <p class="text-xs text-slate-600 leading-relaxed mb-4">
            在排班调度中心使用“智能抽查推荐”时，系统遵循以下业务加权策略：
          </p>
          <ul class="text-xs text-slate-700 space-y-2 list-disc list-inside">
            <li><b>早八优先</b>：默认优先筛选上午第 1–2 节的高出勤关键课次。</li>
            <li><b>行政班均衡</b>：限制单周每个行政班级抽查上限（默认 1 门），规避单一班级疲劳。</li>
            <li><b>抽样覆盖率</b>：推荐比例默认 35%，兼顾监督震慑力与志愿者排班负荷。</li>
            <li><b>规避重复下发</b>：已生成任务的课次自动剔除，保障无缝增量排班。</li>
          </ul>
        </div>
      </div>
    </main>

    <!-- 弹窗 1: 开启新学期 -->
    <el-dialog v-model="showCreateSemesterDialog" title="开启新学期与初始化教学日历" width="540px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">学期代码 (唯一英数字识别码) *</label>
          <input v-model="semesterCreateForm.code" class="input w-full" placeholder="例如: 2026-2027-1 或 2026FA" />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">学期全称 *</label>
          <input v-model="semesterCreateForm.name" class="input w-full" placeholder="例如: 2026-2027学年第1学期" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">学期开始日期 *</label>
            <input v-model="semesterCreateForm.start_date" type="date" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">学期结束日期 *</label>
            <input v-model="semesterCreateForm.end_date" type="date" class="input w-full" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">第一教学周周一 *</label>
            <input v-model="semesterCreateForm.first_monday" type="date" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">总教学周数 *</label>
            <input v-model.number="semesterCreateForm.total_weeks" type="number" min="1" max="50" class="input w-full" />
          </div>
        </div>
        <div class="pt-2">
          <label class="inline-flex items-center gap-2 text-sm text-slate-700 font-medium">
            <input v-model="semesterCreateForm.init_default_periods" type="checkbox" class="rounded text-blue-600" />
            <span>自动初始化标准时段定义 (覆盖 1–11 节，08:00 - 21:50)</span>
          </label>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-outline" @click="showCreateSemesterDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="createSemesterSubmitting" @click="handleCreateSemester">
            {{ createSemesterSubmitting ? '正在创建…' : '确认创建学期' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2: 编辑学期信息 -->
    <el-dialog v-model="showEditSemesterDialog" title="编辑学期信息" width="520px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">学期全称 *</label>
          <input v-model="semesterEditForm.name" class="input w-full" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">学期开始日期</label>
            <input v-model="semesterEditForm.start_date" type="date" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">学期结束日期</label>
            <input v-model="semesterEditForm.end_date" type="date" class="input w-full" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">第一教学周周一</label>
            <input v-model="semesterEditForm.first_monday" type="date" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">总教学周数</label>
            <input v-model.number="semesterEditForm.total_weeks" type="number" min="1" max="50" class="input w-full" />
          </div>
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">学期生命周期状态</label>
          <select v-model="semesterEditForm.status" class="input w-full">
            <option value="ACTIVE">正常激活 (ACTIVE)</option>
            <option value="ARCHIVED">历史归档 (ARCHIVED)</option>
          </select>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-outline" @click="showEditSemesterDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="editSemesterSubmitting" @click="handleUpdateSemester">
            {{ editSemesterSubmitting ? '正在保存…' : '保存学期信息' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 3: 高危重置确认 -->
    <el-dialog v-model="showResetSemesterDialog" title="高危操作：重置当前学期排课与任务数据" width="560px">
      <div class="space-y-3 text-sm">
        <div class="bg-rose-50 border border-rose-200 text-rose-800 p-3.5 rounded">
          <div class="font-bold mb-1 flex items-center gap-1.5">
            <AppIcon name="alert" :size="16" />
            <span>警告：此操作不可撤销！</span>
          </div>
          <p class="text-xs text-rose-700 leading-relaxed">
            重置操作将彻底物理清空【{{ sessionStore.currentSemesterName }}】的所有排课与查课数据：
          </p>
          <ul class="text-xs text-rose-700 list-disc list-inside mt-1 space-y-0.5">
            <li>所有查课任务、排班分配及点名名单快照</li>
            <li>所有课表排课节次（含各周上课安排）</li>
            <li>所有教学班及选课名单关系</li>
            <li>所有志愿者本学期资质认定</li>
            <li>所有校历停补课覆盖设置</li>
          </ul>
          <div class="mt-2 text-slate-700 text-xs">
            <b>安全保留</b>：学生基础底册档案、行政班级及课程公共库<b>完整保留</b>。重置后学期变为空白，您可直接重新上传排课压缩包导入。
          </div>
        </div>

        <div class="space-y-1.5 pt-2">
          <label class="block text-xs font-bold text-slate-700">
            请输入当前学期完整名称以确认：<span class="text-rose-600 select-all font-mono">{{ sessionStore.currentSemesterName }}</span>
          </label>
          <input
            v-model="resetConfirmName"
            type="text"
            class="input w-full font-mono text-sm"
            :placeholder="sessionStore.currentSemesterName || '请输入学期名称'"
          />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="showResetSemesterDialog = false">取消</button>
          <button
            class="btn bg-rose-600 hover:bg-rose-700 text-white font-bold inline-flex items-center gap-1.5"
            :disabled="resetSubmitting || resetConfirmName.trim() !== (sessionStore.currentSemesterName || '').trim()"
            @click="handleResetSemesterData"
          >
            <AppIcon name="trash" :size="14" />
            <span>{{ resetSubmitting ? '正在重置…' : '确认彻底重置本学期' }}</span>
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 4: 添加校历停补课规则 -->
    <el-dialog v-model="showCreateOverrideDialog" title="添加校历停补课规则" width="480px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">执行日期 *</label>
          <input v-model="overrideForm.date" type="date" class="input w-full" />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">规则类型 *</label>
          <select v-model="overrideForm.override_type" class="input w-full">
            <option value="STOP">全天停课 (STOP)</option>
            <option value="MAKEUP">调休补课 (MAKEUP)</option>
          </select>
        </div>
        <div v-if="overrideForm.override_type === 'MAKEUP'" class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">补第几教学周课</label>
            <input v-model.number="overrideForm.source_teaching_week" type="number" min="1" max="50" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">补星期几的课</label>
            <select v-model.number="overrideForm.source_teaching_weekday" class="input w-full">
              <option :value="1">星期一</option>
              <option :value="2">星期二</option>
              <option :value="3">星期三</option>
              <option :value="4">星期四</option>
              <option :value="5">星期五</option>
              <option :value="6">星期六</option>
              <option :value="7">星期日</option>
            </select>
          </div>
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">规则说明 / 节日名称</label>
          <input v-model="overrideForm.reason" class="input w-full" placeholder="例如: 国庆节放假停课 或 补上周二课" />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-outline" @click="showCreateOverrideDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="overrideSubmitting" @click="handleCreateOverride">
            {{ overrideSubmitting ? '正在添加…' : '确认添加' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 5: 节次作息设置 -->
    <el-dialog v-model="showPeriodDialog" :title="`设置第 ${periodForm.period_no} 节作息时间`" width="420px">
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">上课开始时间 *</label>
            <input v-model="periodForm.start_time" type="time" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">下课结束时间 *</label>
            <input v-model="periodForm.end_time" type="time" class="input w-full" />
          </div>
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">变更备注 (可选)</label>
          <input v-model="periodForm.reason" class="input w-full" placeholder="例如: 夏季作息调整" />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-outline" @click="showPeriodDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="periodSubmitting" @click="handleSavePeriod">
            {{ periodSubmitting ? '正在保存…' : '确认保存' }}
          </button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  padding: 24px 32px 16px;
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
}
.crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-mute);
  margin-bottom: 6px;
  text-transform: uppercase;
}
.crumb em {
  font-style: normal;
  font-size: 8px;
  color: var(--line-strong);
}
.page-head h1 {
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.01em;
}
.page-head .sub {
  font-size: 13px;
  color: var(--ink-mute);
  margin-top: 4px;
}
.head-tools {
  display: flex;
  gap: 10px;
}

.tab-nav {
  display: flex;
  gap: 8px;
  padding: 0 32px;
  background: var(--paper);
  border-bottom: 2px solid var(--line);
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 12px 20px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-mute);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.tab-btn:hover {
  color: var(--ink);
}
.tab-btn.active {
  color: var(--ink);
  border-bottom-color: var(--ink);
}

.tab-body {
  padding: 24px 32px;
}

.card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}

.table-wrap {
  overflow-x: auto;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.data-table th {
  padding: 10px 16px;
  background: var(--paper-warm);
  color: var(--ink-mute);
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.data-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--ink);
}
.data-table tr:hover td {
  background: rgba(0, 0, 0, 0.015);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}
.btn-dark {
  background: var(--ink);
  color: var(--paper);
}
.btn-dark:hover {
  opacity: 0.9;
}
.btn-outline {
  background: transparent;
  border-color: var(--line-strong);
  color: var(--ink);
}
.btn-outline:hover {
  background: var(--paper-warm);
}
.btn-ghost {
  background: transparent;
  color: var(--ink-mute);
}
.btn-ghost:hover {
  color: var(--ink);
}
.btn-text {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-weight: 500;
}

.input {
  padding: 7px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  font-size: 13px;
  color: var(--ink);
  background: var(--paper);
  outline: none;
}
.input:focus {
  border-color: var(--ink);
}

.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}
.tag-green { background: #e8f5e9; color: #1b5e20; }
.tag-blue { background: #e3f2fd; color: #0d47a1; }
.tag-amber { background: #fff8e1; color: #b78103; }
.tag-purple { background: #f3e5f5; color: #4a148c; }
.tag-rose { background: #ffebee; color: #c62828; }
.tag-muted { background: #f5f5f5; color: #757575; }
</style>
