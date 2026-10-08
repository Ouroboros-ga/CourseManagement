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
    ElMessage.warning(`输入的学期名称与当前学期名称【${sessionStore.currentSemesterName}】不一致，请仔细核对`)
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

function getPeriodTagClass(pNo: number): string {
  if (pNo <= 4) return 'tag-blue'
  if (pNo <= 8) return 'tag-amber'
  return 'tag-red'
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
    <!-- 纸面秩序标准页面头 -->
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
          <h1 class="font-serif">平台与学期设置</h1>
          <p class="sub">
            统一维护全校学期生命周期、教学日历、节次作息时间表及查课业务全局规则。所有调整将实时作为全校排课与抽查的时间基准。
          </p>
        </div>

        <div class="head-actions">
          <button class="btn btn-outline" @click="openEditSemesterDialog(selectedSemester || undefined)">
            <AppIcon name="edit" :size="14" />
            <span>编辑当前学期</span>
          </button>
          <button class="btn btn-dark" @click="openCreateSemesterDialog">
            <AppIcon name="plus" :size="14" />
            <span>+ 开启新学期</span>
          </button>
        </div>
      </div>
    </header>

    <!-- 关键指标分栏 (纸面秩序标准 stat-row) -->
    <div class="stat-row font-mono mb-6">
      <div class="stat-cell">
        <div class="label">当前工作学期</div>
        <div class="value" style="font-size: 20px;">{{ selectedSemester?.name || sessionStore.currentSemesterName }}</div>
        <div class="note">代码：{{ selectedSemester?.code || '—' }} · {{ selectedSemester?.status === 'ACTIVE' ? '正常激活' : '已归档' }}</div>
      </div>
      <div class="stat-cell">
        <div class="label">教学总周数</div>
        <div class="value">{{ selectedSemester?.total_weeks || 20 }} <span class="text-xs font-normal text-[var(--ink-mute)]">周</span></div>
        <div class="note">{{ selectedSemester?.start_date || '—' }} 至 {{ selectedSemester?.end_date || '—' }}</div>
      </div>
      <div class="stat-cell">
        <div class="label">第一教学周周一</div>
        <div class="value" style="font-size: 20px;">{{ selectedSemester?.first_monday || '—' }}</div>
        <div class="note">全校排课与周次折算基准日</div>
      </div>
      <div class="stat-cell">
        <div class="label">节次作息定义</div>
        <div class="value" style="color: var(--blue)">{{ periods.length }} <span class="text-xs font-normal text-[var(--ink-mute)]">节</span></div>
        <div class="note">覆盖 08:00 至 21:00 高校标准作息</div>
      </div>
    </div>

    <!-- 顶部 Tab 切换 -->
    <div class="tab-nav mb-6">
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
        <span>节次作息时间表 ({{ periods.length }})</span>
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'rules' }"
        @click="activeTab = 'rules'"
      >
        <AppIcon name="shield" :size="14" />
        <span>查课业务规则</span>
      </button>
    </div>

    <!-- ==================== Tab 1: 学期与教学日历 ==================== -->
    <div v-if="activeTab === 'semester'" class="space-y-6">
      <!-- 全校学期总目录 -->
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div>
            <h3>全校学期总目录</h3>
            <div class="meta">支持跨学期浏览、切换当前活跃学期以及学期归档处理。</div>
          </div>
          <div class="tbl-tools">
            <button class="btn btn-sm btn-ghost" @click="fetchSemesters">⟳ 刷新学期列表</button>
          </div>
        </div>

        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 160px;">学期代码</th>
              <th>学期全称</th>
              <th style="width: 200px;">起止日期</th>
              <th style="width: 120px;">总周数</th>
              <th style="width: 100px;">状态</th>
              <th style="width: 220px; text-align: right;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="sem in semesters"
              :key="sem.id"
              :style="sem.id === sessionStore.currentSemesterId ? 'background: var(--paper-deep);' : ''"
            >
              <td class="cell-mono font-bold">{{ sem.code }}</td>
              <td class="cell-main">
                <div class="flex items-center gap-2">
                  <span>{{ sem.name }}</span>
                  <span v-if="sem.id === sessionStore.currentSemesterId" class="tag tag-blue">当前工作</span>
                </div>
              </td>
              <td class="cell-sub font-mono">{{ sem.start_date }} ~ {{ sem.end_date || '未设' }}</td>
              <td class="cell-main">{{ sem.total_weeks }} 周</td>
              <td>
                <span class="tag" :class="sem.status === 'ACTIVE' ? 'tag-green' : 'tag-gray'">
                  {{ sem.status === 'ACTIVE' ? '正常激活' : '已归档' }}
                </span>
              </td>
              <td style="text-align: right;">
                <div class="flex items-center justify-end gap-3">
                  <button
                    v-if="sem.id !== sessionStore.currentSemesterId"
                    class="btn-text text-xs text-blue-700 hover:underline"
                    @click="handleSwitchSemester(sem.id)"
                  >
                    切换为此学期
                  </button>
                  <button
                    class="btn-text text-xs text-[var(--ink-soft)] hover:underline"
                    @click="openEditSemesterDialog(sem)"
                  >
                    编辑
                  </button>
                  <button
                    class="btn-text text-xs hover:underline"
                    :class="sem.status === 'ACTIVE' ? 'text-amber-700' : 'text-green-700'"
                    @click="handleToggleArchive(sem)"
                  >
                    {{ sem.status === 'ACTIVE' ? '归档' : '恢复激活' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 校历停补课调度覆盖 -->
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div>
            <h3>校历节假日停课 / 调休补课调度</h3>
            <div class="meta">
              用于中秋、国庆等节假日调休，或校运会全天停课。停课日排课课次将不计入当日查课抽检。
            </div>
          </div>
          <div class="tbl-tools">
            <button class="btn btn-sm btn-dark" @click="openCreateOverrideDialog">
              <AppIcon name="plus" :size="12" />
              <span>+ 添加停补课规则</span>
            </button>
          </div>
        </div>

        <table class="tbl">
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
              <td class="cell-mono font-bold">{{ item.date }}</td>
              <td>
                <span class="tag" :class="item.override_type === 'STOP' ? 'tag-red' : 'tag-blue'">
                  {{ item.override_type === 'STOP' ? '全天停课' : '调休补课' }}
                </span>
              </td>
              <td class="cell-main text-xs">
                <span v-if="item.override_type === 'MAKEUP'">
                  按第 {{ item.source_teaching_week }} 周 星期{{ item.source_teaching_weekday }} 课表执行
                </span>
                <span v-else class="text-[var(--ink-mute)]">全天停课不调课</span>
              </td>
              <td class="cell-sub">{{ item.reason || '—' }}</td>
              <td style="text-align: right;">
                <button class="btn-text text-xs text-[var(--accent)] hover:underline" @click="handleDeleteOverride(item)">
                  删除
                </button>
              </td>
            </tr>
            <tr v-if="calendarOverrides.length === 0">
              <td colspan="5" class="text-center py-8 text-xs text-[var(--ink-mute)]">
                暂未配置本学期校历停补课覆盖规则
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 高危重置区 (纸面秩序标准 banner-warn) -->
      <div class="banner banner-warn">
        <div class="space-y-1">
          <div class="b-title flex items-center gap-1.5" style="color: var(--accent);">
            <AppIcon name="alert" :size="16" />
            <span>高危操作：清空当前学期排课与任务业务数据</span>
          </div>
          <div class="b-desc">
            此操作将彻底清空当前学期（{{ sessionStore.currentSemesterName }}）所有查课任务、排班分配及课表节次。
            <b>学生底册档案、行政班级及公共课程库完整保留</b>。重置后学期变为空白，可在课表中心重新整包导入。
          </div>
        </div>
        <button
          class="btn btn-danger-line shrink-0"
          @click="openResetSemesterDialog"
        >
          <AppIcon name="trash" :size="14" />
          <span>重置本学期业务数据</span>
        </button>
      </div>
    </div>

    <!-- ==================== Tab 2: 节次作息时间表 ==================== -->
    <div v-if="activeTab === 'periods'" class="space-y-4">
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div>
            <h3>高校节次作息时刻表 (Period Definitions)</h3>
            <div class="meta">
              定义当前学期各小节上下课时刻。排课导入、点名任务生成与下发均以此时刻为时间锚点。
            </div>
          </div>
          <div class="tbl-tools">
            <button class="btn btn-sm btn-ghost" @click="handleInitDefaultPeriods">
              <AppIcon name="refresh" :size="12" />
              <span>一键恢复高校标准作息 (1–11节)</span>
            </button>
            <button class="btn btn-sm btn-dark" @click="openCreatePeriodDialog">
              <AppIcon name="plus" :size="12" />
              <span>+ 新增节次</span>
            </button>
          </div>
        </div>

        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 140px;">节次序号</th>
              <th style="width: 130px;">时段分类</th>
              <th style="width: 180px;">上课开始时刻</th>
              <th style="width: 180px;">下课结束时刻</th>
              <th>单节学时</th>
              <th style="width: 160px; text-align: right;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in periods" :key="p.id">
              <td class="cell-main font-bold">第 {{ p.period_no }} 节</td>
              <td>
                <span class="tag" :class="getPeriodTagClass(p.period_no)">
                  {{ getPeriodSlotName(p.period_no) }}
                </span>
              </td>
              <td class="cell-mono font-bold">{{ p.start_time ? p.start_time.slice(0, 5) : '—' }}</td>
              <td class="cell-mono font-bold">{{ p.end_time ? p.end_time.slice(0, 5) : '—' }}</td>
              <td class="cell-sub">45 分钟标准学时</td>
              <td style="text-align: right;">
                <div class="flex items-center justify-end gap-3">
                  <button class="btn-text text-xs text-blue-700 hover:underline" @click="openEditPeriodDialog(p)">
                    编辑作息
                  </button>
                  <button class="btn-text text-xs text-[var(--accent)] hover:underline" @click="handleDeletePeriod(p)">
                    删除
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="periods.length === 0">
              <td colspan="6" class="text-center py-8 text-xs text-[var(--ink-mute)]">
                当前学期暂无节次作息定义，请点击上方“一键恢复高校标准作息”快速初始化。
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ==================== Tab 3: 查课业务规则 ==================== -->
    <div v-if="activeTab === 'rules'" class="space-y-6">
      <div class="grid grid-cols-2 gap-6">
        <div class="panel">
          <div class="panel-title flex items-center gap-2 mb-3">
            <AppIcon name="clock" :size="16" />
            <span>每日查课提交截止规则 (Daily Submission Deadline)</span>
          </div>
          <p class="text-xs text-[var(--ink-soft)] leading-relaxed mb-5">
            查课志愿者在现场考勤与拍照核验后，必须在每日设定时限前通过小程序提交查课记录。
          </p>
          <div class="banner mb-4" style="border-color: var(--blue); background: var(--blue-soft);">
            <div>
              <div class="b-desc font-medium">全校默认查课提交截止时间</div>
              <div class="font-mono text-2xl font-bold mt-1" style="color: var(--blue);">22:00:00</div>
            </div>
            <span class="tag tag-blue">系统默认全局策略</span>
          </div>
          <div class="text-[11px] text-[var(--ink-mute)]">
            * 超过 22:00 提交的记录将被标记为【迟交】，并在次日早报与统计报表中予以提示。
          </div>
        </div>

        <div class="panel">
          <div class="panel-title flex items-center gap-2 mb-3">
            <AppIcon name="sparkles" :size="16" />
            <span>查课任务智能推荐策略 (Smart Sampling Policy)</span>
          </div>
          <p class="text-xs text-[var(--ink-soft)] leading-relaxed mb-4">
            在排班调度中心使用“智能抽查推荐”时，系统遵循以下业务加权策略：
          </p>
          <ul class="text-xs text-[var(--ink-soft)] space-y-2 list-disc list-inside">
            <li><b>早八优先</b>：默认优先筛选上午第 1–2 节的高出勤关键课次。</li>
            <li><b>行政班均衡</b>：限制单周每个行政班级抽查上限（默认 1 门），规避单一班级疲劳。</li>
            <li><b>抽样覆盖率</b>：推荐比例默认 35%，兼顾监督震慑力与志愿者排班负荷。</li>
            <li><b>规避重复下发</b>：已生成任务的课次自动剔除，保障无缝增量排班。</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- 弹窗 1: 开启新学期 -->
    <el-dialog v-model="showCreateSemesterDialog" title="开启新学期与初始化教学日历" width="540px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期代码 (唯一英数字识别码) *</label>
          <input v-model="semesterCreateForm.code" class="input w-full font-mono" placeholder="例如: 2026-2027-1 或 2026FA" />
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期全称 *</label>
          <input v-model="semesterCreateForm.name" class="input w-full" placeholder="例如: 2026-2027学年第1学期" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期开始日期 *</label>
            <input v-model="semesterCreateForm.start_date" type="date" class="input w-full font-mono" />
          </div>
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期结束日期 *</label>
            <input v-model="semesterCreateForm.end_date" type="date" class="input w-full font-mono" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">第一教学周周一 *</label>
            <input v-model="semesterCreateForm.first_monday" type="date" class="input w-full font-mono" />
          </div>
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">总教学周数 *</label>
            <input v-model.number="semesterCreateForm.total_weeks" type="number" min="1" max="50" class="input w-full font-mono" />
          </div>
        </div>
        <div class="pt-2">
          <label class="inline-flex items-center gap-2 text-sm text-[var(--ink-soft)] font-medium cursor-pointer">
            <input v-model="semesterCreateForm.init_default_periods" type="checkbox" class="chk" />
            <span>自动初始化标准时段定义 (覆盖 1–11 节，08:00 - 21:50)</span>
          </label>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="showCreateSemesterDialog = false">取消</button>
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
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期全称 *</label>
          <input v-model="semesterEditForm.name" class="input w-full" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期开始日期</label>
            <input v-model="semesterEditForm.start_date" type="date" class="input w-full font-mono" />
          </div>
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期结束日期</label>
            <input v-model="semesterEditForm.end_date" type="date" class="input w-full font-mono" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">第一教学周周一</label>
            <input v-model="semesterEditForm.first_monday" type="date" class="input w-full font-mono" />
          </div>
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">总教学周数</label>
            <input v-model.number="semesterEditForm.total_weeks" type="number" min="1" max="50" class="input w-full font-mono" />
          </div>
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">学期生命周期状态</label>
          <select v-model="semesterEditForm.status" class="input w-full">
            <option value="ACTIVE">正常激活 (ACTIVE)</option>
            <option value="ARCHIVED">历史归档 (ARCHIVED)</option>
          </select>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="showEditSemesterDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="editSemesterSubmitting" @click="handleUpdateSemester">
            {{ editSemesterSubmitting ? '正在保存…' : '保存学期信息' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 3: 高危重置确认 -->
    <el-dialog v-model="showResetSemesterDialog" title="高危操作：重置当前学期排课与任务数据" width="560px">
      <div class="space-y-3 text-sm">
        <div class="banner banner-warn" style="border-left: 4px solid var(--accent);">
          <div>
            <div class="b-title" style="color: var(--accent);">警告：此操作不可撤销！</div>
            <p class="b-desc">
              重置操作将彻底物理清空【{{ sessionStore.currentSemesterName }}】的所有排课与查课数据：
            </p>
            <ul class="text-xs list-disc list-inside mt-1 space-y-0.5 text-[var(--ink-soft)]">
              <li>所有查课任务、排班分配及点名名单快照</li>
              <li>所有课表排课节次（含各周上课安排）</li>
              <li>所有教学班及选课名单关系</li>
              <li>所有志愿者本学期资质认定</li>
              <li>所有校历停补课覆盖设置</li>
            </ul>
            <div class="mt-2 text-xs font-semibold text-[var(--ink)]">
              安全保留：学生基础底册档案、行政班级及课程公共库完整保留。
            </div>
          </div>
        </div>

        <div class="space-y-1.5 pt-2">
          <label class="block text-xs font-bold text-[var(--ink)]">
            请输入当前学期完整名称以确认：<span class="text-[var(--accent)] select-all font-mono">{{ sessionStore.currentSemesterName }}</span>
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
            class="btn btn-accent inline-flex items-center gap-1.5"
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
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">执行日期 *</label>
          <input v-model="overrideForm.date" type="date" class="input w-full font-mono" />
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">规则类型 *</label>
          <select v-model="overrideForm.override_type" class="input w-full">
            <option value="STOP">全天停课 (STOP)</option>
            <option value="MAKEUP">调休补课 (MAKEUP)</option>
          </select>
        </div>
        <div v-if="overrideForm.override_type === 'MAKEUP'" class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">补第几教学周课</label>
            <input v-model.number="overrideForm.source_teaching_week" type="number" min="1" max="50" class="input w-full font-mono" />
          </div>
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">补星期几的课</label>
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
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">规则说明 / 节日名称</label>
          <input v-model="overrideForm.reason" class="input w-full" placeholder="例如: 国庆节放假停课 或 补上周二课" />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="showCreateOverrideDialog = false">取消</button>
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
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">上课开始时间 *</label>
            <input v-model="periodForm.start_time" type="time" class="input w-full font-mono" />
          </div>
          <div>
            <label class="block text-xs font-bold text-[var(--ink)] mb-1">下课结束时间 *</label>
            <input v-model="periodForm.end_time" type="time" class="input w-full font-mono" />
          </div>
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">变更备注 (可选)</label>
          <input v-model="periodForm.reason" class="input w-full" placeholder="例如: 夏季作息调整" />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="showPeriodDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="periodSubmitting" @click="handleSavePeriod">
            {{ periodSubmitting ? '正在保存…' : '确认保存' }}
          </button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}
.tab-nav {
  display: flex;
  gap: 8px;
  border-bottom: 2px solid var(--line);
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
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
.tab-btn:hover { color: var(--ink); }
.tab-btn.active { color: var(--ink); border-bottom-color: var(--ink); }

.btn-text {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-weight: 500;
}
</style>
