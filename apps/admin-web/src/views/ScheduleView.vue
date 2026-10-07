<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listTasks,
  queryCourseOccurrences,
  generateExactTasks,
  triggerAutoAssign,
  smartSampleOccurrences,
  type CourseOccurrence,
  type InspectionTaskItem,
  type SmartSampleResult
} from '../api/tasks'
import {
  listAdministrativeClasses,
  createSemester,
  getMasterTimetable,
  type AdministrativeClassItem,
  type MasterTimetableItem
} from '../api/academic'
import {
  uploadImportFile,
  confirmImportBatch,
  uploadBulkImport,
  type ImportPreviewResult,
  type BulkImportResult
} from '../api/importer'
import TaskStatusTag from '../components/TaskStatusTag.vue'
import AppIcon from '../components/AppIcon.vue'
import { formatPeriodText } from '../utils/period'

const sessionStore = useSessionStore()

const activeTab = ref<'dispatch' | 'master'>('dispatch')
const loading = ref(false)
const dispatchLoading = ref(false)
const adminClasses = ref<AdministrativeClassItem[]>([])
const selectedAdminClassId = ref<string>('')

// ---- 课次下发Tab状态 ----
const occurrences = ref<CourseOccurrence[]>([])
const weekTasks = ref<InspectionTaskItem[]>([])
const selectedKeys = ref<string[]>([])
const selectionRevision = ref<string>('')
const selectionScope = ref<Record<string, unknown>>({})
const hasData = computed(() => occurrences.value.length > 0 || weekTasks.value.length > 0)

// ---- 全校总课表Tab状态 ----
const masterTimetableList = ref<MasterTimetableItem[]>([])
const masterLoading = ref(false)
const masterWeekday = ref<number | ''>('')
const masterWeekNo = ref<number | ''>('')
const masterAdminClassId = ref<string>('')
const masterKeyword = ref('')

function formatWeekday(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    const names = ['日', '一', '二', '三', '四', '五', '六']
    return names[d.getDay()] || ''
  } catch {
    return ''
  }
}

// ---- 开启新学期弹窗 ----
const showSemesterDialog = ref(false)
const semesterSubmitting = ref(false)
const semesterForm = ref({
  code: '',
  name: '',
  start_date: '',
  end_date: '',
  first_monday: '',
  total_weeks: 20,
  init_default_periods: true,
  reason: '管理端开启新学期'
})

// ---- 导入教务数据弹窗 ----
const showImportDialog = ref(false)
const importMode = ref<'bulk' | 'single'>('bulk')
const importTarget = ref<'admin_roster' | 'grid_timetable' | 'elective_course'>('grid_timetable')
const importFile = ref<File | null>(null)
const importUploading = ref(false)
const importConfirming = ref(false)
const importPreview = ref<ImportPreviewResult | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// ---- 批量/整包 ZIP 导入状态 ----
const bulkFiles = ref<File[]>([])
const bulkFileInputRef = ref<HTMLInputElement | null>(null)
const bulkUploading = ref(false)
const bulkResult = ref<BulkImportResult | null>(null)

function isRosterFile(f: { type: string }) {
  const t = (f.type || '').toUpperCase()
  return t === 'ADMIN_ROSTER' || t === 'ROSTER'
}

function isSuccessFile(f: { status: string }) {
  return (f.status || '').toUpperCase() === 'SUCCESS'
}

function isSkippedFile(f: { status: string }) {
  return (f.status || '').toUpperCase() === 'SKIPPED'
}

const bulkHasErrors = computed(() => {
  return bulkResult.value?.file_results?.some(f => !isSuccessFile(f) && !isSkippedFile(f)) ?? false
})

const bulkAllFailed = computed(() => {
  if (!bulkResult.value?.file_results?.length) return false
  return bulkResult.value.file_results.every(f => !isSuccessFile(f))
})

// ---- 智能抽查推荐状态 ----
const showSmartSampleDialog = ref(false)
const smartSampling = ref(false)
const smartSampleResult = ref<SmartSampleResult | null>(null)
const smartSampleForm = ref({
  morning_only: true,
  max_tasks_per_class: 1,
  sample_ratio: 0.35,
  exclude_already_generated: true
})

async function loadData() {
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  selectedKeys.value = []
  try {
    // 1. 加载行政班列表（全校真实行政班）
    if (adminClasses.value.length === 0) {
      const adminRes = await listAdministrativeClasses({ page_size: 100 })
      adminClasses.value = adminRes.items || []
    }

    // 2. 加载本周已有的查课任务（可按选中的行政班联动过滤）
    const taskRes = await listTasks({
      semester_id: sessionStore.currentSemesterId,
      week_no: sessionStore.currentWeekNo,
      administrative_class_id: selectedAdminClassId.value ? selectedAdminClassId.value : undefined,
      page_size: 100
    })
    weekTasks.value = taskRes.items || []

    // 3. 查询当周排课课次（支持按行政班精准过滤，或查当周全量课次）
    if (sessionStore.weekDateRange.start && sessionStore.weekDateRange.end) {
      try {
        const occRes = await queryCourseOccurrences({
          semester_id: sessionStore.currentSemesterId,
          date_from: sessionStore.weekDateRange.start,
          date_to: sessionStore.weekDateRange.end,
          administrative_class_id: selectedAdminClassId.value ? Number(selectedAdminClassId.value) : undefined,
          page_size: 500
        })
        occurrences.value = occRes.items || []
        selectionRevision.value = occRes.selection_revision
        selectionScope.value = occRes.selection_scope || {}
      } catch (err: unknown) {
        console.error('加载排课课次失败:', err)
        occurrences.value = []
      }
    } else {
      occurrences.value = []
    }
  } catch (err: unknown) {
    console.error('加载排班数据失败:', err)
  } finally {
    loading.value = false
  }
}

async function loadMasterTimetableData() {
  if (!sessionStore.currentSemesterId) return
  masterLoading.value = true
  try {
    const res = await getMasterTimetable({
      semester_id: sessionStore.currentSemesterId,
      weekday: masterWeekday.value ? Number(masterWeekday.value) : undefined,
      week_no: masterWeekNo.value ? Number(masterWeekNo.value) : undefined,
      administrative_class_id: masterAdminClassId.value ? Number(masterAdminClassId.value) : undefined,
      keyword: masterKeyword.value.trim() || undefined
    })
    masterTimetableList.value = res.items || []
  } catch (err: unknown) {
    console.error('加载总课表失败:', err)
    ElMessage.error('加载总课表库失败')
  } finally {
    masterLoading.value = false
  }
}

watch(
  () => [sessionStore.currentSemesterId, sessionStore.currentWeekNo, selectedAdminClassId.value],
  () => {
    if (activeTab.value === 'dispatch') {
      loadData()
    } else {
      loadMasterTimetableData()
    }
  }
)

watch(activeTab, (tab) => {
  if (tab === 'master') {
    masterWeekNo.value = sessionStore.currentWeekNo
    loadMasterTimetableData()
  } else {
    loadData()
  }
})

onMounted(() => {
  loadData()
})

const selectableOccurrences = computed(() => occurrences.value.filter(o => o.selectable))

const isAllSelected = computed(() => {
  if (selectableOccurrences.value.length === 0) return false
  return selectableOccurrences.value.every(o => 
    selectedKeys.value.includes(`${o.course_schedule_id}_${o.inspection_date}`)
  )
})

const isIndeterminate = computed(() => {
  if (selectableOccurrences.value.length === 0) return false
  const count = selectableOccurrences.value.filter(o => 
    selectedKeys.value.includes(`${o.course_schedule_id}_${o.inspection_date}`)
  ).length
  return count > 0 && count < selectableOccurrences.value.length
})

function isSelected(item: CourseOccurrence): boolean {
  return selectedKeys.value.includes(`${item.course_schedule_id}_${item.inspection_date}`)
}

function toggleSelect(key: string) {
  const index = selectedKeys.value.indexOf(key)
  if (index > -1) {
    selectedKeys.value.splice(index, 1)
  } else {
    selectedKeys.value.push(key)
  }
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    const keysToRemove = new Set(selectableOccurrences.value.map(o => `${o.course_schedule_id}_${o.inspection_date}`))
    selectedKeys.value = selectedKeys.value.filter(k => !keysToRemove.has(k))
  } else {
    const keysToAdd = selectableOccurrences.value.map(o => `${o.course_schedule_id}_${o.inspection_date}`)
    const set = new Set([...selectedKeys.value, ...keysToAdd])
    selectedKeys.value = Array.from(set)
  }
}

function onRowClick(item: CourseOccurrence) {
  if (!item.selectable) return
  toggleSelect(`${item.course_schedule_id}_${item.inspection_date}`)
}

async function triggerDispatch() {
  if (selectedKeys.value.length === 0) {
    ElMessage.warning('请勾选需要下发的课次')
    return
  }

  dispatchLoading.value = true
  try {
    const selectedItems = occurrences.value.filter(o => 
      selectedKeys.value.includes(`${o.course_schedule_id}_${o.inspection_date}`)
    )

    const genRes = await generateExactTasks({
      semester_id: sessionStore.currentSemesterId,
      inspection_type: 'COURSE',
      selection_revision: selectionRevision.value || 'rev_1',
      selection_scope: selectionScope.value,
      occurrences: selectedItems.map(o => ({
        course_schedule_id: o.course_schedule_id,
        inspection_date: o.inspection_date
      }))
    })

    let assignMsg = ''
    if (genRes.assignable_task_ids && genRes.assignable_task_ids.length > 0) {
      try {
        const assignRes = await triggerAutoAssign({
          task_ids: genRes.assignable_task_ids
        })
        assignMsg = `<br/>3. <b>求解器自动排班</b>：已排定 ${assignRes.assigned_count} 个任务，待人工处理 ${assignRes.unassigned_count} 个。`
      } catch {
        assignMsg = '<br/>3. <b>自动排班</b>：暂无可用志愿者或无需自动分配。'
      }
    }

    ElMessageBox.alert(
      `下发完成！<br/><br/>
      1. <b>任务生成</b>：成功生成 ${genRes.created} 个新查课任务<br/>
      2. <b>已有任务</b>：跳过 ${genRes.existed} 个已存在的重复任务
      ${assignMsg}`,
      '下发与排班完成',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '确定'
      }
    )

    await loadData()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '下发失败'
    ElMessage.error(msg)
  } finally {
    dispatchLoading.value = false
  }
}

// ---- 开启新学期 ----
function openSemesterDialog() {
  const currentYear = new Date().getFullYear()
  semesterForm.value = {
    code: `${currentYear}-${currentYear + 1}-1`,
    name: `${currentYear}-${currentYear + 1}学年第1学期`,
    start_date: `${currentYear}-09-01`,
    end_date: `${currentYear + 1}-01-31`,
    first_monday: `${currentYear}-09-07`,
    total_weeks: 20,
    init_default_periods: true,
    reason: '管理端新建学期'
  }
  showSemesterDialog.value = true
}

async function submitSemester() {
  if (!semesterForm.value.code || !semesterForm.value.name) {
    ElMessage.warning('请填写学期代码与学期名称')
    return
  }
  semesterSubmitting.value = true
  try {
    const newSem = await createSemester(semesterForm.value)
    ElMessage.success(`学期 ${newSem.name} 开启成功！标准节次定义已自动初始化`)
    showSemesterDialog.value = false
    await sessionStore.fetchAcademicContext()
    sessionStore.setSemester(newSem.id)
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '开启学期失败'
    ElMessage.error(msg)
  } finally {
    semesterSubmitting.value = false
  }
}

// ---- 导入数据 ----
function openImportDialog() {
  importFile.value = null
  importPreview.value = null
  bulkFiles.value = []
  bulkResult.value = null
  showImportDialog.value = true
  if (fileInputRef.value) fileInputRef.value.value = ''
  if (bulkFileInputRef.value) bulkFileInputRef.value.value = ''
}

const isDragging = ref(false)

function triggerBulkFileInput() {
  bulkFileInputRef.value?.click()
}

function triggerSingleFileInput() {
  fileInputRef.value?.click()
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    if (importMode.value === 'bulk') {
      bulkFiles.value = Array.from(e.dataTransfer.files)
      bulkResult.value = null
    } else {
      importFile.value = e.dataTransfer.files[0]
      importPreview.value = null
    }
  }
}

function removeBulkFile(index: number) {
  bulkFiles.value.splice(index, 1)
  if (bulkFiles.value.length === 0) {
    bulkResult.value = null
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function getFileTypeBadge(name: string): string {
  const lower = name.toLowerCase()
  if (lower.endsWith('.zip')) return 'ZIP 压缩包'
  if (lower.endsWith('.xlsx') || lower.endsWith('.xls')) return 'Excel 表格'
  return '数据文件'
}

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    importFile.value = target.files[0]
    importPreview.value = null
  }
}

function handleBulkFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    bulkFiles.value = Array.from(target.files)
    bulkResult.value = null
  }
}

async function uploadAndPreview() {
  if (!importFile.value) {
    ElMessage.warning('请先选择要上传的 Excel 文件')
    return
  }
  importUploading.value = true
  try {
    const res = await uploadImportFile(importTarget.value, importFile.value, {
      semester_id: sessionStore.currentSemesterId
    })
    importPreview.value = res
    if (res.errors && res.errors.length > 0) {
      ElMessage.warning(`解析完成，但存在 ${res.errors.length} 项格式错误，请查看错误详情`)
    } else {
      ElMessage.success('解析校验成功，请核对概要后点击确认入库')
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '上传解析失败'
    ElMessage.error(msg)
  } finally {
    importUploading.value = false
  }
}

async function confirmImport() {
  if (!importPreview.value) return
  importConfirming.value = true
  try {
    const res = await confirmImportBatch(importPreview.value.id)
    ElMessageBox.alert(
      `导入已原子生效！<br/><br/>
      <b>数据概要：</b><br/>
      <pre style="background:#f4f4f5;padding:8px;border-radius:4px;font-size:12px;">${JSON.stringify(res.summary, null, 2)}</pre>`,
      '导入落库成功',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '完成'
      }
    )
    showImportDialog.value = false
    adminClasses.value = []
    if (activeTab.value === 'master') {
      loadMasterTimetableData()
    } else {
      loadData()
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '确认导入失败'
    ElMessage.error(msg)
  } finally {
    importConfirming.value = false
  }
}

async function submitBulkImport() {
  if (!sessionStore.currentSemesterId) {
    ElMessage.warning('请先确认当前选中的学期')
    return
  }
  if (bulkFiles.value.length === 0) {
    ElMessage.warning('请选择需要上传的 Excel 文件或 ZIP 压缩包')
    return
  }
  bulkUploading.value = true
  try {
    const res = await uploadBulkImport(sessionStore.currentSemesterId, bulkFiles.value)
    bulkResult.value = res
    const hasErr = res.file_results?.some(f => !isSuccessFile(f) && !isSkippedFile(f))
    if (hasErr) {
      ElMessage.warning(`整包处理完成，但有部分文件存在异常，请在下方列表核对`)
    } else {
      const stuMsg = res.students_created > 0 
        ? `新建建档学生 ${res.students_created} 名` 
        : `核验在籍学生 ${res.total_students || res.students_updated || 0} 名（档案已存在）`
      ElMessage.success(`整包导入成功！共处理 ${res.total_files} 个文件，新建班级 ${res.classes_created} 个，${stuMsg}`)
    }
    adminClasses.value = []
    await loadData()
    if (activeTab.value === 'master') {
      await loadMasterTimetableData()
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '批量导入失败'
    ElMessage.error(msg)
  } finally {
    bulkUploading.value = false
  }
}

// ---- 智能抽查推荐 ----
function openSmartSampleDialog() {
  smartSampleResult.value = null
  showSmartSampleDialog.value = true
}

async function runSmartSample() {
  if (!sessionStore.currentSemesterId) return
  smartSampling.value = true
  try {
    const res = await smartSampleOccurrences({
      semester_id: Number(sessionStore.currentSemesterId),
      week_no: sessionStore.currentWeekNo,
      morning_only: smartSampleForm.value.morning_only,
      max_tasks_per_class: smartSampleForm.value.max_tasks_per_class,
      sample_ratio: smartSampleForm.value.sample_ratio,
      exclude_already_generated: smartSampleForm.value.exclude_already_generated
    })
    smartSampleResult.value = res
    if (res.sampled_count === 0) {
      ElMessage.info('未筛选出待查课次（可能已全部下发或无符合条件的早八课）')
    } else {
      ElMessage.success(`智能推荐算法已就绪！共精选 ${res.sampled_count} 门重点查课课次`)
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '抽查算法计算失败'
    ElMessage.error(msg)
  } finally {
    smartSampling.value = false
  }
}

function applySmartSample() {
  if (!smartSampleResult.value || smartSampleResult.value.sampled_count === 0) return
  const newKeys = smartSampleResult.value.occurrences.map(o => `${o.course_schedule_id}_${o.inspection_date}`)
  const keySet = new Set([...selectedKeys.value, ...newKeys])
  selectedKeys.value = Array.from(keySet)
  showSmartSampleDialog.value = false
  ElMessage.success(`已为您自动勾选推荐的 ${newKeys.length} 门课次！您可以直接核对并点击【确认下发并排班】`)
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
      <h1>教务课表与查课下发调度</h1>
      <p class="sub">
        统一整合全校教务课表数据库、行政班级花名册、选修课导入以及多教学班人员关联追踪，按教学周精准下发查课任务。
      </p>

      <div class="head-actions flex items-center gap-3">
        <button class="btn btn-outline" @click="openSemesterDialog">
          <AppIcon name="plus" :size="14" />
          <span>开启新学期</span>
        </button>
        <button class="btn btn-outline" @click="openImportDialog">
          <AppIcon name="upload" :size="14" />
          <span>批量导入教务数据</span>
        </button>
        <button
          v-if="activeTab === 'dispatch'"
          class="btn btn-outline border-amber-300 text-amber-900 bg-amber-50 hover:bg-amber-100 font-semibold"
          @click="openSmartSampleDialog"
        >
          <AppIcon name="sparkles" :size="14" class="text-amber-700" />
          <span>智能抽查推荐</span>
        </button>
        <button
          v-if="activeTab === 'dispatch'"
          class="btn btn-dark"
          :disabled="dispatchLoading || selectedKeys.length === 0"
          @click="triggerDispatch"
        >
          <AppIcon name="send" :size="14" />
          <span>{{ dispatchLoading ? '正在下发…' : `确认下发并排班 (${selectedKeys.length})` }}</span>
        </button>
      </div>
    </header>

    <!-- Tab 切换 -->
    <div class="tab-nav">
      <button
        class="tab-btn flex items-center gap-2"
        :class="{ active: activeTab === 'dispatch' }"
        @click="activeTab = 'dispatch'"
      >
        <AppIcon name="calendar" :size="15" />
        <span>当周课次下发与排班</span>
      </button>
      <button
        class="tab-btn flex items-center gap-2"
        :class="{ active: activeTab === 'master' }"
        @click="activeTab = 'master'"
      >
        <AppIcon name="database" :size="15" />
        <span>全校总课表数据库 (Master Timetable)</span>
      </button>
    </div>

    <!-- TAB 1: 课次勾选与下发 -->
    <div v-if="activeTab === 'dispatch'" class="tbl-wrap">
      <!-- 筛选条 -->
      <div class="filter-bar">
        <div class="fgroup">
          <label>当前周次日期范围</label>
          <span class="cell-mono font-bold">{{ sessionStore.weekDateRange.start }} 至 {{ sessionStore.weekDateRange.end }}</span>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>行政班过滤</label>
          <select v-model="selectedAdminClassId" class="input">
            <option value="">全部行政班（{{ adminClasses.length }} 个）</option>
            <option v-for="c in adminClasses" :key="c.id" :value="c.id">
              {{ c.class_name }}
            </option>
          </select>
        </div>
      </div>

      <!-- 课次列表 -->
      <div v-if="occurrences.length > 0">
        <div class="table-header-bar flex items-center justify-between">
          <div class="section-title">
            当周待下发课次（共 {{ occurrences.length }} 节，已勾选 {{ selectedKeys.length }} 节）
          </div>
          <div class="table-actions flex items-center gap-2 pr-6 py-2">
            <button
              v-if="selectableOccurrences.length > 0"
              type="button"
              class="btn btn-outline btn-xs"
              @click="toggleSelectAll"
            >
              {{ isAllSelected ? '取消全选' : '全选所有可下发' }}
            </button>
            <button
              v-if="selectedKeys.length > 0"
              type="button"
              class="btn btn-outline btn-xs text-rose-700 border-rose-200 hover:bg-rose-50"
              @click="selectedKeys = []"
            >
              清空选择
            </button>
          </div>
        </div>
        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 52px;" class="text-center">
                <div class="checkbox-wrapper" title="全选 / 取消全选">
                  <input
                    type="checkbox"
                    class="checkbox-lg"
                    :disabled="selectableOccurrences.length === 0"
                    :checked="isAllSelected"
                    .indeterminate="isIndeterminate"
                    @change="toggleSelectAll"
                  />
                </div>
              </th>
              <th>日期</th>
              <th>星期 / 节次</th>
              <th>课程名称</th>
              <th>教学班</th>
              <th>教室地点</th>
              <th>当前状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in occurrences"
              :key="`${item.course_schedule_id}_${item.inspection_date}`"
              class="selectable-row"
              :class="{
                'row-disabled': !item.selectable,
                'row-selected': isSelected(item)
              }"
              @click="onRowClick(item)"
            >
              <td class="cell-checkbox">
                <div class="checkbox-wrapper">
                  <input
                    type="checkbox"
                    class="checkbox-lg"
                    :disabled="!item.selectable"
                    :checked="isSelected(item)"
                    @click.stop
                    @change="toggleSelect(`${item.course_schedule_id}_${item.inspection_date}`)"
                  />
                </div>
              </td>
              <td class="cell-mono font-medium">{{ item.inspection_date }}</td>
              <td>
                <div class="font-bold">周{{ formatWeekday(item.inspection_date) }}</div>
                <div class="cell-sub font-mono">{{ formatPeriodText(item.start_period, item.end_period) }}</div>
              </td>
              <td>
                <div class="cell-main font-semibold">{{ item.course_name }}</div>
                <div class="cell-sub font-mono text-xs">#{{ item.course_schedule_id }}</div>
              </td>
              <td>
                <div class="cell-main flex items-center gap-1.5 flex-wrap">
                  <span>{{ item.class_name || item.teaching_class_name || '—' }}</span>
                  <span
                    v-if="(item.class_name || item.teaching_class_name || '').includes('合班') || (item.class_name || item.teaching_class_name || '').includes('+')"
                    class="px-1.5 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700 font-semibold border border-indigo-200"
                    title="相同教室与时段自动合班查课"
                  >
                    合班
                  </span>
                </div>
              </td>
              <td>
                <div class="cell-main">{{ item.classroom || item.classroom_name || '未指定教室' }}</div>
              </td>
              <td>
                <span v-if="item.existing_task_id" class="tag tag-green">已下发任务</span>
                <span v-else-if="!item.selectable" class="tag tag-amber" :title="item.disabled_reason || ''">
                  {{ item.disabled_reason || '不可下发' }}
                </span>
                <span v-else class="tag tag-gray">待下发</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 本周已生成的任务清单 -->
      <div v-if="weekTasks.length > 0" style="margin-top: 24px;">
        <div class="section-title">本周数据库中已有查课任务（共 {{ weekTasks.length }} 条）</div>
        <table class="tbl">
          <thead>
            <tr>
              <th>任务编号</th>
              <th>查课日期</th>
              <th>节次</th>
              <th>课程</th>
              <th>教学班</th>
              <th>教室</th>
              <th>任务状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in weekTasks" :key="t.id">
              <td class="cell-mono code">#{{ t.id }}</td>
              <td>{{ t.inspection_date }}</td>
              <td class="cell-mono">{{ formatPeriodText(t.start_period, t.end_period) }}</td>
              <td>{{ t.course_name_snapshot || '—' }}</td>
              <td>{{ t.class_name_snapshot || '—' }}</td>
              <td>{{ t.classroom_snapshot || '—' }}</td>
              <td>
                <TaskStatusTag :status="t.status" :deadline-assessment="t.deadline_assessment" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && !hasData" class="empty-box">
        <div class="empty-icon flex justify-center mb-2">
          <AppIcon name="folder-open" :size="36" class="text-gray-300" />
        </div>
        <div class="empty-text">当前周次（第 {{ sessionStore.currentWeekNo }} 周）暂无可下发课次及已有任务</div>
        <div class="empty-sub">您可以点击右上角“批量导入教务数据”录入班级花名册与课表</div>
      </div>
    </div>

    <!-- TAB 2: 全校教务总课表库 -->
    <div v-if="activeTab === 'master'" v-loading="masterLoading" class="tbl-wrap">
      <!-- 搜索过滤条 -->
      <div class="filter-bar">
        <div class="fgroup">
          <label>教学周</label>
          <select v-model="masterWeekNo" class="input" @change="loadMasterTimetableData">
            <option :value="''">全部周次</option>
            <option v-for="w in sessionStore.totalWeeks" :key="w" :value="w">第 {{ w }} 周</option>
          </select>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>星期</label>
          <select v-model="masterWeekday" class="input" @change="loadMasterTimetableData">
            <option :value="''">星期一至星期日</option>
            <option :value="1">星期一</option>
            <option :value="2">星期二</option>
            <option :value="3">星期三</option>
            <option :value="4">星期四</option>
            <option :value="5">星期五</option>
            <option :value="6">星期六</option>
            <option :value="7">星期日</option>
          </select>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>行政班</label>
          <select v-model="masterAdminClassId" class="input" @change="loadMasterTimetableData">
            <option :value="''">全部行政班</option>
            <option v-for="c in adminClasses" :key="c.id" :value="c.id">
              {{ c.class_name }}
            </option>
          </select>
        </div>
        <div class="fsep"></div>
        <div class="fgroup flex-1">
          <label>课程/班级/地点搜索</label>
          <input
            v-model="masterKeyword"
            type="text"
            class="input flex-1"
            placeholder="输入课程名称、教学班名、教室地点..."
            @keyup.enter="loadMasterTimetableData"
          />
          <button class="btn btn-dark btn-sm" @click="loadMasterTimetableData">查询</button>
        </div>
      </div>

      <!-- 总课表列表 -->
      <div v-if="masterTimetableList.length > 0">
        <div class="section-title flex justify-between items-center">
          <span>全校教务总课表检索结果（共 {{ masterTimetableList.length }} 门排课）</span>
          <span class="text-xs text-gray-500 font-normal">
            其中查课覆盖课次：{{ masterTimetableList.filter(m => m.is_inspectable).length }} 门
          </span>
        </div>
        <table class="tbl">
          <thead>
            <tr>
              <th>时间</th>
              <th>课程信息</th>
              <th>教学班 / 关联行政班</th>
              <th>上课地点</th>
              <th>生效周次</th>
              <th>人员与考勤追踪</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in masterTimetableList" :key="item.id">
              <td>
                <div class="font-bold">周{{ item.weekday }}</div>
                <div class="cell-sub font-mono">{{ formatPeriodText(item.start_period, item.end_period) }}</div>
              </td>
              <td>
                <div class="cell-main font-bold">{{ item.course_name }}</div>
                <div class="cell-sub font-mono text-xs text-gray-400">代码: {{ item.course_code }}</div>
              </td>
              <td>
                <div class="cell-main text-blue-700 font-medium flex items-center gap-1.5 flex-wrap">
                  <span>{{ item.teaching_class_name }}</span>
                  <span
                    v-if="item.teaching_class_name && (item.teaching_class_name.includes('合班') || item.teaching_class_name.includes('+'))"
                    class="px-1.5 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700 font-semibold border border-indigo-200"
                    title="合班课程"
                  >
                    合班
                  </span>
                </div>
                <div v-if="item.administrative_classes && item.administrative_classes.length > 0" class="cell-sub text-xs">
                  行政班: {{ item.administrative_classes.join(', ') }}
                </div>
              </td>
              <td>
                <span class="cell-main">{{ item.classroom || '未排教室' }}</span>
              </td>
              <td class="font-mono text-xs">
                <span class="px-2 py-0.5 bg-gray-100 rounded text-gray-700">
                  {{ item.weeks.length > 8 ? `${item.weeks[0]}-${item.weeks[item.weeks.length - 1]}周 (共${item.weeks.length}周)` : item.weeks.join(',') + '周' }}
                </span>
              </td>
              <td>
                <div v-if="item.is_physical_education" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500">
                  <AppIcon name="ban" :size="12" class="text-gray-400" />
                  <span>体育课 · 免查</span>
                </div>
                <div v-else-if="item.enrolled_student_count > 0" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs bg-emerald-50 text-emerald-700 font-medium border border-emerald-200">
                  <AppIcon name="users" :size="12" class="text-emerald-600" />
                  <span>需查课 · 名单 {{ item.enrolled_student_count }} 人</span>
                </div>
                <div v-else class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs bg-amber-50 text-amber-700 border border-amber-200">
                  <AppIcon name="alert" :size="12" class="text-amber-500" />
                  <span>暂无学生名单</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!masterLoading && masterTimetableList.length === 0" class="empty-box">
        <div class="empty-icon flex justify-center mb-2">
          <AppIcon name="book" :size="36" class="text-gray-300" />
        </div>
        <div class="empty-text">未检索到符合条件的排课记录</div>
        <div class="empty-sub">请检查筛选条件，或使用上方“批量导入教务数据”导入网格课表</div>
      </div>
    </div>

    <!-- 弹窗 1: 开启新学期 -->
    <el-dialog v-model="showSemesterDialog" title="开启新学期与初始化教学日历" width="540px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-gray-700 mb-1">学期代码 (唯一英数字识别码) *</label>
          <input v-model="semesterForm.code" class="input w-full" placeholder="例如: 2026-2027-1 或 2026FA" />
        </div>
        <div>
          <label class="block text-xs font-bold text-gray-700 mb-1">学期全称 *</label>
          <input v-model="semesterForm.name" class="input w-full" placeholder="例如: 2026-2027学年第1学期" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-gray-700 mb-1">学期开始日期 *</label>
            <input v-model="semesterForm.start_date" type="date" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-gray-700 mb-1">学期结束日期 *</label>
            <input v-model="semesterForm.end_date" type="date" class="input w-full" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-bold text-gray-700 mb-1">第一教学周周一 *</label>
            <input v-model="semesterForm.first_monday" type="date" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-gray-700 mb-1">总教学周数 *</label>
            <input v-model.number="semesterForm.total_weeks" type="number" min="1" max="50" class="input w-full" />
          </div>
        </div>
        <div class="pt-2">
          <label class="inline-flex items-center gap-2 text-sm text-gray-700 font-medium">
            <input v-model="semesterForm.init_default_periods" type="checkbox" class="rounded text-blue-600" />
            <span>自动初始化标准时段定义 (覆盖 1–11 节，08:00 - 21:50)</span>
          </label>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-outline" @click="showSemesterDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="semesterSubmitting" @click="submitSemester">
            {{ semesterSubmitting ? '正在创建…' : '确认创建学期' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2: 导入教务数据 -->
    <el-dialog
      v-model="showImportDialog"
      title="导入教务数据"
      width="720px"
      :close-on-click-modal="false"
      class="import-dialog"
    >
      <!-- 模式切换 -->
      <div class="mode-tabs">
        <button
          type="button"
          class="mode-tab"
          :class="{ active: importMode === 'bulk' }"
          @click="importMode = 'bulk'"
        >
          <span class="mode-no font-mono">01</span>
          <span class="mode-name">整包批量导入</span>
          <span class="mode-desc">ZIP 压缩包 / 多文件，自动编排原子入库</span>
        </button>
        <button
          type="button"
          class="mode-tab"
          :class="{ active: importMode === 'single' }"
          @click="importMode = 'single'"
        >
          <span class="mode-no font-mono">02</span>
          <span class="mode-name">单文件分步导入</span>
          <span class="mode-desc">上传 → 解析预览 → 确认入库</span>
        </button>
      </div>

      <!-- 模式 1: 整包批量导入 -->
      <div v-if="importMode === 'bulk'">
        <div class="feat-grid">
          <div class="feat-cell">
            <div class="feat-head">
              <AppIcon name="sparkles" :size="13" />
              <span>自动顺序编排</span>
            </div>
            <p>先建行政班与学生档案，再关联网格课表，无需繁琐分批操作。</p>
          </div>
          <div class="feat-cell">
            <div class="feat-head">
              <AppIcon name="swap" :size="13" />
              <span>学籍异动识别</span>
            </div>
            <p>自动核对学号变化，智能识别并修正转专业 / 调班学生班级。</p>
          </div>
          <div class="feat-cell">
            <div class="feat-head">
              <AppIcon name="archive" :size="13" />
              <span>全格式支持</span>
            </div>
            <p>支持 GBK / UTF-8 编码 ZIP 压缩包，或直接多选多个表格。</p>
          </div>
        </div>

        <!-- 拖拽上传区 -->
        <div
          v-if="!bulkResult"
          class="drop-zone"
          :class="{ dragging: isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="handleDrop"
          @click="triggerBulkFileInput"
        >
          <input
            ref="bulkFileInputRef"
            type="file"
            accept=".zip,.xlsx,.xls"
            multiple
            class="hidden"
            @change="handleBulkFileSelect"
          />
          <div class="dz-icon"><AppIcon name="cloud-upload" :size="22" /></div>
          <div class="dz-title">点击选择文件，或将文件拖拽至此处</div>
          <div class="dz-sub">支持整包 .zip 压缩包（内含花名册及课表），或按住 Ctrl 多选 .xlsx / .xls 表格</div>
        </div>

        <!-- 待处理文件清单 -->
        <div v-if="bulkFiles.length > 0 && !bulkResult" class="file-panel">
          <div class="fp-head">
            <span>待处理清单 · 共 {{ bulkFiles.length }} 个文件</span>
            <button type="button" class="fp-clear" @click.stop="bulkFiles = []">
              <AppIcon name="trash" :size="12" />
              <span>清空重选</span>
            </button>
          </div>
          <div class="fp-list">
            <div v-for="(f, idx) in bulkFiles" :key="idx" class="fp-row">
              <AppIcon :name="f.name.endsWith('.zip') ? 'zip' : 'excel'" :size="15" class="fp-ico" />
              <span class="fp-name font-mono" :title="f.name">{{ f.name }}</span>
              <span class="fp-size font-mono">{{ formatFileSize(f.size) }}</span>
              <span class="tag" :class="f.name.endsWith('.zip') ? 'tag-amber' : 'tag-blue'">{{ getFileTypeBadge(f.name) }}</span>
              <button type="button" class="fp-del" title="移除此项" @click.stop="removeBulkFile(idx)">
                <AppIcon name="close" :size="12" />
              </button>
            </div>
          </div>
        </div>

        <button
          v-if="!bulkResult"
          class="btn btn-dark dlg-primary"
          :disabled="bulkUploading || bulkFiles.length === 0"
          @click="submitBulkImport"
        >
          <AppIcon v-if="!bulkUploading" name="upload" :size="14" />
          <span v-if="bulkUploading" class="spin">⟳</span>
          <span>{{ bulkUploading ? '正在解压并原子入库，请稍候…' : `开始整包自动分析与原子入库（${bulkFiles.length}）` }}</span>
        </button>

        <!-- 批量导入结果展示 -->
        <div v-if="bulkResult" class="result-block">
          <div class="rb-head">
            <div class="rb-title" :class="bulkAllFailed ? 'err' : (bulkHasErrors ? 'warn' : 'ok')">
              <AppIcon :name="bulkAllFailed ? 'close' : (bulkHasErrors ? 'alert' : 'check-circle')" :size="16" />
              <span>{{ bulkAllFailed ? '整包导入失败' : (bulkHasErrors ? '部分文件导入完成（存在异常文件）' : '整包导入完成') }}</span>
            </div>
            <span class="rb-meta font-mono">共处理 {{ bulkResult.total_files }} 个文件</span>
          </div>

          <div class="rb-stats">
            <div class="rb-stat">
              <div class="s-label">考勤花名册</div>
              <div class="s-value font-mono">{{ bulkResult.rosters_count }}<em>份</em></div>
            </div>
            <div class="rb-stat">
              <div class="s-label">网格课表</div>
              <div class="s-value font-mono">{{ bulkResult.timetables_count }}<em>份</em></div>
            </div>
            <div class="rb-stat">
              <div class="s-label">新建行政班</div>
              <div class="s-value font-mono">{{ bulkResult.classes_created }}<em>个</em></div>
            </div>
            <div class="rb-stat">
              <div class="s-label">学生档案</div>
              <div class="s-value font-mono hl-green">
                {{ bulkResult.students_created > 0 ? bulkResult.students_created : (bulkResult.total_students || bulkResult.students_updated || 0) }}
                <em>人{{ bulkResult.students_created === 0 && (bulkResult.total_students || bulkResult.students_updated) ? ' (已有)' : ' (新档)' }}</em>
              </div>
            </div>
            <div class="rb-stat">
              <div class="s-label">异动识别</div>
              <div class="s-value font-mono">{{ bulkResult.students_transferred }}<em>人</em></div>
            </div>
            <div class="rb-stat">
              <div class="s-label">课程库更新</div>
              <div class="s-value font-mono">{{ bulkResult.courses_created }}<em>门</em></div>
            </div>
            <div class="rb-stat span2">
              <div class="s-label">排课节次入库</div>
              <div class="s-value font-mono">{{ bulkResult.schedules_created }}<em>节</em></div>
            </div>
          </div>

          <!-- 文件列表明细 -->
          <div v-if="bulkResult.file_results && bulkResult.file_results.length > 0" class="rb-files">
            <div v-for="(f, idx) in bulkResult.file_results" :key="idx" class="rb-file-row">
              <span class="rf-name font-mono" :title="f.filename">{{ f.filename }}</span>
              <span class="tag" :class="isRosterFile(f) ? 'tag-blue' : 'tag-gray'">
                {{ isRosterFile(f) ? '花名册' : '网格课表' }}
              </span>
              <span
                class="tag"
                :class="isSuccessFile(f) ? 'tag-green' : (isSkippedFile(f) ? 'tag-gray' : 'tag-red')"
                :title="f.error || ''"
              >
                {{ isSuccessFile(f) ? '已入库' : (isSkippedFile(f) ? '已跳过' : '异常') }}
              </span>
              <span v-if="isSuccessFile(f) && f.summary" class="rf-stat font-mono">
                <template v-if="isRosterFile(f)">
                  {{ (f.summary.students_created && f.summary.students_created > 0) ? `+${f.summary.students_created}人` : `${f.summary.total_students || f.summary.students_updated || f.summary.student_count || 0}人(在籍)` }}
                </template>
                <template v-else>
                  +{{ f.summary.schedules_created || 0 }}节课
                </template>
              </span>
              <span v-else-if="f.error" class="rf-error font-mono" :title="f.error">
                {{ f.error }}
              </span>
            </div>
          </div>

          <div class="rb-actions">
            <button class="btn btn-sm" @click="bulkResult = null; bulkFiles = []">继续导入更多</button>
            <button class="btn btn-dark btn-sm" @click="showImportDialog = false">完成并关闭</button>
          </div>
        </div>
      </div>

      <!-- 模式 2: 单文件分步导入 -->
      <div v-if="importMode === 'single'">
        <div class="step-block">
          <div class="step-label font-mono">STEP 1 · 选择导入目标</div>
          <select v-model="importTarget" class="input dlg-select" @change="importPreview = null">
            <option value="admin_roster">行政班花名册（.xlsx / .xls）— 自动建班与学生建档</option>
            <option value="grid_timetable">学校网格课表（.xls / .xlsx）— 提取排课并关联行政班名单</option>
            <option value="elective_course">选修课 / 分班课名单（.xlsx）— 多教学班选课与课表录入</option>
          </select>
        </div>

        <div v-if="!importPreview" class="step-block">
          <div class="step-label font-mono">STEP 2 · 上传文件</div>
          <div
            class="drop-zone slim"
            :class="{ dragging: isDragging }"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleDrop"
            @click="triggerSingleFileInput"
          >
            <input
              ref="fileInputRef"
              type="file"
              accept=".xlsx,.xls"
              class="hidden"
              @change="handleFileSelect"
            />
            <div class="dz-icon"><AppIcon name="file-text" :size="20" /></div>
            <div class="dz-title">{{ importFile ? importFile.name : '点击选择单个 Excel 表格，或拖拽至此' }}</div>
            <div class="dz-sub">支持 .xlsx / .xls 格式单个花名册或课表</div>
          </div>
        </div>

        <button
          v-if="!importPreview"
          class="btn btn-dark dlg-primary"
          :disabled="importUploading || !importFile"
          @click="uploadAndPreview"
        >
          <AppIcon v-if="!importUploading" name="search" :size="14" />
          <span v-if="importUploading" class="spin">⟳</span>
          <span>{{ importUploading ? '正在解析文件…' : '上传并解析预览' }}</span>
        </button>

        <!-- 预览结果 -->
        <div v-if="importPreview" class="step-block">
          <div class="step-label font-mono">STEP 3 · 核对解析结果并入库</div>
          <div class="result-block">
            <div class="rb-head">
              <div class="rb-title">
                <AppIcon name="info" :size="15" />
                <span>解析预览</span>
              </div>
              <span class="rb-meta font-mono">批次 #{{ importPreview.id }}</span>
            </div>

            <div class="rb-summary">
              <div v-for="(val, key) in importPreview.summary" :key="key" class="rb-sum-row">
                <span class="k">{{ key }}</span>
                <span class="v font-mono">{{ val }}</span>
              </div>
            </div>

            <div v-if="importPreview.errors && importPreview.errors.length > 0" class="note-block err">
              <div class="nb-head">
                <AppIcon name="alert" :size="13" />
                <span>发现错误（修正后方可确认入库）</span>
              </div>
              <ul>
                <li v-for="(e, idx) in importPreview.errors.slice(0, 5)" :key="idx">
                  第 {{ e.row }} 行：{{ e.message }}
                </li>
              </ul>
            </div>

            <div v-if="importPreview.warnings && importPreview.warnings.length > 0" class="note-block warn">
              <div class="nb-head">
                <AppIcon name="info" :size="13" />
                <span>共 {{ importPreview.warnings.length }} 条提示（如重复项将自动忽略）</span>
              </div>
            </div>

            <div class="rb-actions split">
              <button class="btn" @click="importPreview = null">重新选择</button>
              <button
                class="btn btn-dark"
                :disabled="importConfirming || !importPreview.can_confirm"
                @click="confirmImport"
              >
                <AppIcon v-if="!importConfirming" name="check" :size="14" />
                <span v-if="importConfirming" class="spin">⟳</span>
                <span>{{ importConfirming ? '正在落库…' : '确认整批原子落库' }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 弹窗 3: 智能抽查推荐 -->
    <el-dialog
      v-model="showSmartSampleDialog"
      title="智能抽查推荐"
      width="640px"
      :close-on-click-modal="false"
      class="sample-dialog"
    >
      <p class="dlg-intro">按教务规范算法从当周候选课次中筛选重点查课对象，确认后一键勾选并下发。</p>

      <!-- 算法策略 -->
      <div class="policy-block">
        <div class="pb-title">
          <AppIcon name="sliders" :size="14" />
          <span>算法策略 · 教务规范</span>
        </div>
        <div class="pb-grid">
          <div class="pb-item">
            <b>早八重点查</b>
            <span>默认优先筛选上午课（第 1–4 节 / 早八与午前课）</span>
          </div>
          <div class="pb-item">
            <b>免查规则过滤</b>
            <span>自动剔除体育、实验、网课</span>
          </div>
          <div class="pb-item">
            <b>班级均衡配额</b>
            <span>每班按每周上限合理抽查</span>
          </div>
          <div class="pb-item">
            <b>相同课时合流</b>
            <span>相同教室时段多班自动合并</span>
          </div>
        </div>
      </div>

      <!-- 抽查参数 -->
      <div class="param-grid">
        <div class="param">
          <label>每班每周抽查上限（节）</label>
          <input
            v-model.number="smartSampleForm.max_tasks_per_class"
            type="number"
            min="1"
            max="5"
            class="input font-mono"
          />
          <div class="hint">范围 1–5，用于均衡各班被查频次</div>
        </div>
        <div class="param">
          <label>抽查比例（0.1 – 1.0）</label>
          <input
            v-model.number="smartSampleForm.sample_ratio"
            type="number"
            min="0.1"
            max="1.0"
            step="0.05"
            class="input font-mono"
          />
          <div class="hint">占候选池比例，如 0.35 约抽查三成半</div>
        </div>
      </div>

      <!-- 筛选开关 -->
      <div class="opt-list">
        <label class="opt-row">
          <input v-model="smartSampleForm.morning_only" type="checkbox" class="chk" />
          <span class="opt-text">仅抽查上午 1–2 节<em>早八课堂高优考勤</em></span>
        </label>
        <label class="opt-row">
          <input v-model="smartSampleForm.exclude_already_generated" type="checkbox" class="chk" />
          <span class="opt-text">排除当周已下发任务的课次<em>避免重复下发</em></span>
        </label>
      </div>

      <button
        class="btn btn-dark dlg-primary"
        :disabled="smartSampling"
        @click="runSmartSample"
      >
        <AppIcon v-if="!smartSampling" name="search" :size="14" />
        <span v-if="smartSampling" class="spin">⟳</span>
        <span>{{ smartSampling ? '正在运算推荐课次…' : '计算智能推荐课次' }}</span>
      </button>

      <!-- 计算结果预览 -->
      <div v-if="smartSampleResult" class="result-block">
        <div class="rb-head">
          <div class="rb-title">
            <AppIcon name="check-circle" :size="15" />
            <span>推荐查课清单</span>
          </div>
          <span class="rb-meta font-mono">精选 {{ smartSampleResult.sampled_count }} / 候选 {{ smartSampleResult.total_candidates }} 门</span>
        </div>

        <div v-if="smartSampleResult.items && smartSampleResult.items.length > 0" class="rb-files tall">
          <div v-for="item in smartSampleResult.items.slice(0, 15)" :key="item.course_schedule_id" class="course-row">
            <div class="cr-left">
              <span class="cr-course">{{ item.course_name }}</span>
              <span class="cr-class">{{ item.class_name }}</span>
            </div>
            <div class="cr-right font-mono">
              {{ item.inspection_date }} · {{ formatPeriodText(item.start_period, item.end_period) }} · {{ item.classroom }}
            </div>
          </div>
          <div v-if="smartSampleResult.items.length > 15" class="more-row font-mono">
            … 另有 {{ smartSampleResult.items.length - 15 }} 门课次未列出
          </div>
        </div>

        <div class="rb-actions">
          <button class="btn btn-sm" @click="showSmartSampleDialog = false">取消</button>
          <button
            class="btn btn-dark btn-sm"
            :disabled="smartSampleResult.sampled_count === 0"
            @click="applySmartSample"
          >
            <AppIcon name="check" :size="14" />
            <span>应用推荐并批量勾选（{{ smartSampleResult.sampled_count }}）</span>
          </button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.sel-info { font-size: 13px; color: var(--ink-mute); }
.sel-info strong { color: var(--ink); font-size: 15px; }

.tab-nav {
  display: flex;
  gap: 8px;
  padding: 0 24px;
  background: var(--paper);
  border-bottom: 2px solid var(--line);
}
.tab-btn {
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-mute);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  transition: all 0.15s;
}
.tab-btn:hover {
  color: var(--ink);
}
.tab-btn.active {
  color: var(--ink);
  border-bottom-color: var(--ink);
}

.section-title {
  padding: 14px 24px 6px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  background: var(--paper);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
  font-size: 12px;
  flex-wrap: wrap;
}
.fgroup { display: flex; align-items: center; gap: 8px; }
.fgroup label { color: var(--ink-mute); font-weight: 500; }
.fsep { width: 1px; height: 16px; background: var(--line-strong); }

.code { color: var(--blue); font-weight: 600; }

.table-header-bar {
  background: var(--paper);
}

.selectable-row {
  cursor: pointer;
  user-select: none;
  transition: background-color 0.12s ease;
}

.selectable-row:hover:not(.row-disabled) {
  background-color: #f8fafc;
}

.selectable-row.row-selected {
  background-color: #eff6ff !important;
}

.selectable-row.row-selected:hover {
  background-color: #dbeafe !important;
}

.row-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.cell-checkbox {
  width: 52px;
  text-align: center;
  vertical-align: middle;
  padding: 0 !important;
}

.checkbox-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 48px;
  cursor: pointer;
}

.checkbox-lg {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  accent-color: #0f172a;
  cursor: pointer;
  transition: transform 0.1s ease;
}

.checkbox-lg:hover:not(:disabled) {
  transform: scale(1.15);
}

.checkbox-lg:disabled {
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

/* ============================================================
   弹窗共用（导入 / 智能抽查）
   ============================================================ */
.dlg-intro {
  font-size: 12px;
  color: var(--ink-mute);
  line-height: 1.7;
  margin-bottom: 18px;
}
.dlg-primary {
  width: 100%;
  justify-content: center;
  padding: 11px 20px;
  font-weight: 700;
  margin-top: 16px;
}
.dlg-select { width: 100%; font-size: 12px; }
.spin { display: inline-block; animation: dlg-rotate 0.9s linear infinite; margin-right: 2px; }
@keyframes dlg-rotate { to { transform: rotate(360deg); } }
.hidden { display: none; }

/* ---------- 模式切换 ---------- */
.mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 20px;
}
.mode-tab {
  background: var(--paper-deep);
  padding: 13px 16px 12px;
  text-align: left;
  border: none;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-family: inherit;
  transition: background 0.15s;
}
.mode-tab:hover { background: var(--paper); }
.mode-tab.active { background: var(--paper); box-shadow: inset 0 2px 0 var(--ink); }
.mode-no {
  font-size: 10px;
  color: var(--ink-mute);
  letter-spacing: 0.1em;
  margin-bottom: 3px;
}
.mode-tab.active .mode-no { color: var(--accent); }
.mode-name { font-size: 13px; font-weight: 700; color: var(--ink); }
.mode-desc { font-size: 11px; color: var(--ink-mute); }

/* ---------- 特性三栏（整包导入） ---------- */
.feat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
  padding: 16px 2px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
}
.feat-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 4px;
}
.feat-head svg { color: var(--ink-soft); flex-shrink: 0; }
.feat-cell p {
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.65;
}

/* ---------- 拖拽上传区 ---------- */
.drop-zone {
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background: var(--paper-deep);
  padding: 30px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  margin-bottom: 14px;
}
.drop-zone.slim { padding: 22px 20px; margin-bottom: 0; }
.drop-zone:hover { border-color: var(--ink); background: var(--paper); }
.drop-zone.dragging { border-color: var(--accent); background: var(--accent-soft); }
.dz-icon {
  width: 40px;
  height: 40px;
  margin: 0 auto 10px;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink);
  background: var(--paper);
}
.dz-title { font-size: 13px; font-weight: 700; color: var(--ink); margin-bottom: 4px; }
.dz-sub { font-size: 11px; color: var(--ink-mute); }

/* ---------- 待处理文件清单 ---------- */
.file-panel {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 14px;
}
.fp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-soft);
  letter-spacing: 0.02em;
}
.fp-clear {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  font-size: 11px;
  color: var(--ink-mute);
  cursor: pointer;
  font-family: inherit;
  transition: color 0.15s;
}
.fp-clear:hover { color: var(--accent); }
.fp-list { max-height: 168px; overflow-y: auto; }
.fp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.fp-row:last-child { border-bottom: none; }
.fp-ico { color: var(--ink-mute); flex-shrink: 0; }
.fp-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--ink);
}
.fp-size { font-size: 11px; color: var(--ink-mute); flex-shrink: 0; }
.fp-del {
  display: inline-flex;
  padding: 3px;
  background: none;
  border: none;
  color: var(--ink-mute);
  cursor: pointer;
  border-radius: 2px;
  transition: color 0.15s, background 0.15s;
  flex-shrink: 0;
}
.fp-del:hover { color: var(--accent); background: var(--accent-soft); }

/* ---------- 步骤块（单文件导入） ---------- */
.step-block { margin-bottom: 16px; }
.step-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.1em;
  margin-bottom: 8px;
}

/* ---------- 结果块 ---------- */
.result-block {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  padding: 16px;
}
.rb-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.rb-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
}
.rb-title.ok { color: var(--green); }
.rb-title.warn { color: var(--amber); }
.rb-title.err { color: var(--accent); }
.rb-meta { font-size: 11px; color: var(--ink-mute); }

.rb-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 12px;
}
.rb-stat { background: var(--paper); padding: 12px 14px; }
.rb-stat.span2 { grid-column: span 2; }
.rb-stat .s-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}
.rb-stat .s-value { font-size: 20px; font-weight: 600; line-height: 1; color: var(--ink); }
.rb-stat .s-value em {
  font-style: normal;
  font-size: 11px;
  font-weight: 400;
  color: var(--ink-mute);
  margin-left: 3px;
}
.rb-stat .s-value.hl-green { color: var(--green); }

.rb-files {
  max-height: 176px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  margin-bottom: 12px;
}
.rb-files.tall { max-height: 220px; }
.rb-file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.rb-file-row:last-child { border-bottom: none; }
.rf-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--ink-soft);
}
.rf-stat {
  font-size: 11px;
  color: var(--green);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}
.rf-error {
  font-size: 11px;
  color: var(--accent);
  white-space: nowrap;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.rb-summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 12px;
}
.rb-sum-row {
  background: var(--paper);
  padding: 8px 14px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
}
.rb-sum-row .k { color: var(--ink-mute); }
.rb-sum-row .v { font-weight: 600; color: var(--ink); }

.rb-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.rb-actions.split { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.rb-actions.split .btn { justify-content: center; }

/* ---------- 提示块（错误 / 警告） ---------- */
.note-block {
  border-left: 2px solid;
  padding: 10px 14px;
  font-size: 12px;
  line-height: 1.7;
  margin-bottom: 12px;
  border-radius: 0 var(--radius) var(--radius) 0;
}
.note-block.err { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-dark); }
.note-block.warn { border-color: var(--amber); background: var(--amber-soft); color: var(--ink-soft); }
.nb-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  margin-bottom: 4px;
}
.note-block ul { padding-left: 18px; }
.note-block li { margin-bottom: 2px; }

/* ---------- 智能抽查：策略区 ---------- */
.policy-block {
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line);
  padding: 14px 2px;
  margin-bottom: 16px;
}
.pb-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 10px;
}
.pb-title svg { color: var(--ink-soft); }
.pb-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 20px;
}
.pb-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}
.pb-item b {
  color: var(--ink);
  font-weight: 700;
  white-space: nowrap;
}
.pb-item b::after { content: '·'; margin-left: 8px; color: var(--line-strong); }
.pb-item span { color: var(--ink-mute); font-size: 11px; }

/* ---------- 智能抽查：参数区 ---------- */
.param-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
.param label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-soft);
  margin-bottom: 6px;
  letter-spacing: 0.02em;
}
.param .input { width: 100%; }
.param .hint {
  font-size: 10px;
  color: var(--ink-mute);
  margin-top: 5px;
  line-height: 1.5;
}

/* ---------- 智能抽查：开关项 ---------- */
.opt-list {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}
.opt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--line);
  transition: background 0.15s;
}
.opt-row:last-child { border-bottom: none; }
.opt-row:hover { background: var(--paper-deep); }
.opt-text { font-size: 12px; font-weight: 600; color: var(--ink); }
.opt-text em {
  font-style: normal;
  font-weight: 400;
  font-size: 11px;
  color: var(--ink-mute);
  margin-left: 8px;
}

/* ---------- 智能抽查：课程行 ---------- */
.course-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
}
.course-row:last-child { border-bottom: none; }
.cr-left { min-width: 0; display: flex; align-items: baseline; gap: 8px; }
.cr-course { font-size: 12px; font-weight: 700; color: var(--ink); white-space: nowrap; }
.cr-class {
  font-size: 11px;
  color: var(--ink-mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cr-right { font-size: 11px; color: var(--ink-soft); white-space: nowrap; flex-shrink: 0; }
.more-row {
  padding: 8px 12px;
  text-align: center;
  font-size: 11px;
  color: var(--ink-mute);
}
</style>
