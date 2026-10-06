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
  listTeachingClasses,
  createSemester,
  getMasterTimetable,
  type TeachingClassItem,
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

const sessionStore = useSessionStore()

const activeTab = ref<'dispatch' | 'master'>('dispatch')
const loading = ref(false)
const dispatchLoading = ref(false)
const teachingClasses = ref<TeachingClassItem[]>([])
const selectedClassId = ref<string>('')

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
    // 1. 加载本周已有的查课任务
    const taskRes = await listTasks({
      semester_id: sessionStore.currentSemesterId,
      week_no: sessionStore.currentWeekNo,
      page_size: 50
    })
    weekTasks.value = taskRes.items || []

    // 2. 加载当前学期的教学班
    if (teachingClasses.value.length === 0) {
      const clsRes = await listTeachingClasses(sessionStore.currentSemesterId)
      teachingClasses.value = clsRes.items || []
    }

    // 3. 查询当周排课课次
    if (sessionStore.weekDateRange.start && sessionStore.weekDateRange.end && teachingClasses.value.length > 0) {
      const classIds = selectedClassId.value 
        ? [Number(selectedClassId.value)] 
        : teachingClasses.value.map(c => Number(c.id)).slice(0, 50)

      try {
        const occRes = await queryCourseOccurrences({
          semester_id: sessionStore.currentSemesterId,
          date_from: sessionStore.weekDateRange.start,
          date_to: sessionStore.weekDateRange.end,
          teaching_class_ids: classIds
        })
        occurrences.value = occRes.items || []
        selectionRevision.value = occRes.selection_revision
        selectionScope.value = occRes.selection_scope || {}
      } catch {
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
  () => [sessionStore.currentSemesterId, sessionStore.currentWeekNo, selectedClassId.value],
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

function toggleSelect(key: string) {
  const index = selectedKeys.value.indexOf(key)
  if (index > -1) {
    selectedKeys.value.splice(index, 1)
  } else {
    selectedKeys.value.push(key)
  }
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
    teachingClasses.value = []
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
    ElMessage.success(`整包导入成功！共处理 ${res.total_files} 个文件，新建班级 ${res.classes_created} 个，录入学生 ${res.students_created} 名`)
    teachingClasses.value = []
    if (activeTab.value === 'master') {
      loadMasterTimetableData()
    } else {
      loadData()
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
          ➕ 开启新学期
        </button>
        <button class="btn btn-outline" @click="openImportDialog">
          📁 批量导入教务数据
        </button>
        <button
          v-if="activeTab === 'dispatch'"
          class="btn btn-outline border-amber-300 text-amber-800 bg-amber-50 hover:bg-amber-100 font-semibold"
          @click="openSmartSampleDialog"
        >
          ⚡ 智能抽查推荐
        </button>
        <button
          v-if="activeTab === 'dispatch'"
          class="btn btn-dark"
          :disabled="dispatchLoading || selectedKeys.length === 0"
          @click="triggerDispatch"
        >
          {{ dispatchLoading ? '正在下发…' : `⚡ 确认下发并排班 (${selectedKeys.length})` }}
        </button>
      </div>
    </header>

    <!-- Tab 切换 -->
    <div class="tab-nav">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'dispatch' }"
        @click="activeTab = 'dispatch'"
      >
        📅 当周课次下发与排班
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'master' }"
        @click="activeTab = 'master'"
      >
        🏫 全校总课表数据库 (Master Timetable)
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
          <label>教学班过滤</label>
          <select v-model="selectedClassId" class="input">
            <option value="">全部教学班（{{ teachingClasses.length }} 个）</option>
            <option v-for="c in teachingClasses" :key="c.id" :value="c.id">
              {{ c.class_name }}
            </option>
          </select>
        </div>
      </div>

      <!-- 课次列表 -->
      <div v-if="occurrences.length > 0">
        <div class="section-title">当周待下发课次（共 {{ occurrences.length }} 节）</div>
        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 44px;">勾选</th>
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
              :class="{ 'row-disabled': !item.selectable }"
            >
              <td>
                <input
                  type="checkbox"
                  :disabled="!item.selectable"
                  :checked="selectedKeys.includes(`${item.course_schedule_id}_${item.inspection_date}`)"
                  @change="toggleSelect(`${item.course_schedule_id}_${item.inspection_date}`)"
                />
              </td>
              <td class="cell-mono">{{ item.inspection_date }}</td>
              <td>
                <div class="font-bold">周{{ formatWeekday(item.inspection_date) }}</div>
                <div class="cell-sub font-mono">第 {{ item.start_period }}-{{ item.end_period }} 大节</div>
              </td>
              <td>
                <div class="cell-main">{{ item.course_name }}</div>
                <div class="cell-sub font-mono">#{{ item.course_schedule_id }}</div>
              </td>
              <td>
                <div class="cell-main flex items-center gap-1.5 flex-wrap">
                  <span>{{ item.teaching_class_name }}</span>
                  <span
                    v-if="item.teaching_class_name && (item.teaching_class_name.includes('合班') || item.teaching_class_name.includes('+'))"
                    class="px-1.5 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700 font-semibold border border-indigo-200"
                    title="相同教室与时段自动合班查课"
                  >
                    合班
                  </span>
                </div>
              </td>
              <td>
                <div class="cell-main">{{ item.classroom_name || '未指定教室' }}</div>
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
              <td class="cell-mono">第 {{ t.start_period }}-{{ t.end_period }} 节</td>
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
        <div class="empty-icon">📂</div>
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
                <div class="cell-sub font-mono">第 {{ item.start_period }}-{{ item.end_period }} 大节</div>
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
                  <span>⚽ 体育课·免查</span>
                </div>
                <div v-else-if="item.enrolled_student_count > 0" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs bg-emerald-50 text-emerald-700 font-medium border border-emerald-200">
                  <span>👥 需查课 · 名单 {{ item.enrolled_student_count }} 人</span>
                </div>
                <div v-else class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs bg-amber-50 text-amber-700 border border-amber-200">
                  <span>⚠️ 暂无学生名单</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!masterLoading && masterTimetableList.length === 0" class="empty-box">
        <div class="empty-icon">📚</div>
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
            <span>自动初始化标准 6 大节次时间定义 (08:00 - 21:50)</span>
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
    <el-dialog v-model="showImportDialog" title="导入教务数据" width="720px">
      <!-- 模式选择切换 -->
      <div class="flex items-center gap-2 p-1 bg-gray-100 rounded-lg mb-4 text-xs font-semibold">
        <button
          type="button"
          class="flex-1 py-2 px-3 rounded-md transition-all text-center"
          :class="importMode === 'bulk' ? 'bg-white shadow text-blue-700 font-bold' : 'text-gray-600 hover:text-gray-900'"
          @click="importMode = 'bulk'"
        >
          📦 批量整包 ZIP / 多文件导入 (推荐 · 支持30+班级考勤与课表)
        </button>
        <button
          type="button"
          class="flex-1 py-2 px-3 rounded-md transition-all text-center"
          :class="importMode === 'single' ? 'bg-white shadow text-blue-700 font-bold' : 'text-gray-600 hover:text-gray-900'"
          @click="importMode = 'single'"
        >
          📄 单文件分步导入与预览
        </button>
      </div>

      <!-- 模式 1: 整包 / 批量 ZIP 导入 -->
      <div v-if="importMode === 'bulk'" class="space-y-4">
        <div class="p-4 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900 leading-relaxed">
          <div class="font-bold mb-1">💡 智能整包解析说明：</div>
          <div>支持直接上传包含多个班级考勤表（如《数据科学2601.xlsx》）和全校班级课表（如《班级课表.zip》）的压缩包或多选文件。</div>
          <div class="mt-1 text-blue-700">
            • <b>自动顺序执行</b>：先解析考勤表完成行政建班与学生建档，再解析网格课表关联学生，无须手动分步上传。<br/>
            • <b>学籍异动识别</b>：自动识别并标记转专业/调班学生，更新至最新班级。<br/>
            • <b>支持格式</b>：.zip 压缩包（内含 xlsx/xls）、或直接多选多个 .xlsx / .xls 文件。
          </div>
        </div>

        <div class="p-4 bg-gray-50 rounded-lg border border-gray-200">
          <label class="block text-xs font-bold text-gray-700 mb-2">选择 ZIP 压缩包或多选 Excel 文件</label>
          <input
            ref="bulkFileInputRef"
            type="file"
            accept=".zip,.xlsx,.xls"
            multiple
            class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            @change="handleBulkFileSelect"
          />
          <div v-if="bulkFiles.length > 0" class="mt-2 text-xs text-gray-600">
            已选择 <span class="font-bold text-blue-700">{{ bulkFiles.length }}</span> 个文件：
            <span class="text-gray-500 font-mono">{{ bulkFiles.map(f => f.name).slice(0, 3).join(', ') }}{{ bulkFiles.length > 3 ? ` 等共 ${bulkFiles.length} 项` : '' }}</span>
          </div>
        </div>

        <div v-if="!bulkResult">
          <button
            class="btn btn-dark w-full py-2.5 text-center font-bold"
            :disabled="bulkUploading || bulkFiles.length === 0"
            @click="submitBulkImport"
          >
            {{ bulkUploading ? '🚀 正在解压并批量原子落库，请稍候…' : '🚀 开始整包自动分析与原子落库' }}
          </button>
        </div>

        <!-- 批量导入结果展示 -->
        <div v-if="bulkResult" class="p-4 bg-emerald-50 border border-emerald-200 rounded-lg space-y-3">
          <div class="flex justify-between items-center">
            <span class="font-bold text-emerald-900 text-sm">🎉 批量整包导入完成</span>
            <span class="text-xs px-2 py-0.5 rounded bg-emerald-200 text-emerald-800 font-mono">
              共处理 {{ bulkResult.total_files }} 个文件
            </span>
          </div>

          <div class="grid grid-cols-4 gap-2 text-xs bg-white p-3 rounded border border-emerald-100">
            <div class="p-2 bg-gray-50 rounded">
              <div class="text-gray-500">考勤花名册</div>
              <div class="text-base font-bold text-gray-800">{{ bulkResult.rosters_count }} 份</div>
            </div>
            <div class="p-2 bg-gray-50 rounded">
              <div class="text-gray-500">班级网格课表</div>
              <div class="text-base font-bold text-gray-800">{{ bulkResult.timetables_count }} 份</div>
            </div>
            <div class="p-2 bg-gray-50 rounded">
              <div class="text-gray-500">新建行政班</div>
              <div class="text-base font-bold text-gray-800">{{ bulkResult.classes_created }} 个</div>
            </div>
            <div class="p-2 bg-gray-50 rounded">
              <div class="text-gray-500">学生建立档案</div>
              <div class="text-base font-bold text-emerald-600">{{ bulkResult.students_created }} 人</div>
            </div>
            <div class="p-2 bg-gray-50 rounded">
              <div class="text-gray-500">转专业/换班识别</div>
              <div class="text-base font-bold text-blue-600">{{ bulkResult.students_transferred }} 人</div>
            </div>
            <div class="p-2 bg-gray-50 rounded">
              <div class="text-gray-500">新建课程库</div>
              <div class="text-base font-bold text-gray-800">{{ bulkResult.courses_created }} 门</div>
            </div>
            <div class="p-2 bg-gray-50 rounded col-span-2">
              <div class="text-gray-500">课表排课节次</div>
              <div class="text-base font-bold text-gray-800">{{ bulkResult.schedules_created }} 节</div>
            </div>
          </div>

          <!-- 文件列表明细摘要 -->
          <div v-if="bulkResult.file_results && bulkResult.file_results.length > 0" class="max-h-48 overflow-y-auto text-xs bg-white p-2 rounded border border-emerald-100 divide-y divide-gray-100">
            <div v-for="(f, idx) in bulkResult.file_results" :key="idx" class="py-1.5 flex justify-between items-center">
              <span class="truncate max-w-xs font-mono text-gray-700" :title="f.filename">{{ f.filename }}</span>
              <div class="flex items-center gap-2">
                <span class="px-1.5 py-0.5 rounded text-[11px]" :class="f.type === 'ADMIN_ROSTER' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'">
                  {{ f.type === 'ADMIN_ROSTER' ? '花名册' : '网格课表' }}
                </span>
                <span class="px-1.5 py-0.5 rounded text-[11px]" :class="f.status === 'SUCCESS' ? 'bg-emerald-100 text-emerald-700 font-bold' : (f.status === 'SKIPPED' ? 'bg-gray-100 text-gray-500' : 'bg-red-100 text-red-600')">
                  {{ f.status === 'SUCCESS' ? '成功' : (f.status === 'SKIPPED' ? '跳过' : '异常') }}
                </span>
              </div>
            </div>
          </div>

          <div class="pt-2 flex justify-end">
            <button class="btn btn-dark" @click="showImportDialog = false">完成并关闭</button>
          </div>
        </div>
      </div>

      <!-- 模式 2: 单文件分步导入 -->
      <div v-if="importMode === 'single'" class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-gray-700 mb-1">导入目标类型 *</label>
          <select v-model="importTarget" class="input w-full font-medium" @change="importPreview = null">
            <option value="admin_roster">1. 行政班花名册 (班级考勤表 .xlsx/.xls) - 自动建班与学生</option>
            <option value="grid_timetable">2. 学校网格课表 (.xls/.xlsx) - 自动提取排课并关联行政班学生名单</option>
            <option value="elective_course">3. 选修课/分班课名单 (.xlsx) - 精确多教学班选课与课表录入</option>
          </select>
        </div>

        <div class="p-4 bg-gray-50 rounded-lg border border-gray-200">
          <label class="block text-xs font-bold text-gray-700 mb-2">选择 Excel 文件 (.xlsx 或 .xls)</label>
          <input
            ref="fileInputRef"
            type="file"
            accept=".xlsx,.xls"
            class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            @change="handleFileSelect"
          />
          <div class="mt-2 text-xs text-gray-500">
            支持学校导出的原始班级考勤表与课程网格表，系统将自动进行中英文归一化解析并原子事务入库。
          </div>
        </div>

        <div v-if="!importPreview" class="pt-2">
          <button
            class="btn btn-dark w-full py-2.5 text-center"
            :disabled="importUploading || !importFile"
            @click="uploadAndPreview"
          >
            {{ importUploading ? '正在解析文件…' : '🔍 上传并预览解析' }}
          </button>
        </div>

        <!-- 预览结果显示 -->
        <div v-if="importPreview" class="p-4 bg-blue-50 border border-blue-200 rounded-lg space-y-3">
          <div class="flex justify-between items-center">
            <span class="font-bold text-blue-900">解析预览结果</span>
            <span class="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-800">批次 #{{ importPreview.id }}</span>
          </div>

          <div class="grid grid-cols-2 gap-2 text-xs text-gray-700 bg-white p-3 rounded border border-blue-100">
            <div v-for="(val, key) in importPreview.summary" :key="key">
              <span class="font-medium text-gray-500">{{ key }}: </span>
              <span class="font-mono font-bold">{{ val }}</span>
            </div>
          </div>

          <div v-if="importPreview.errors && importPreview.errors.length > 0" class="text-xs text-red-600 bg-red-50 p-2 rounded">
            <strong>发现错误 (无法确认):</strong>
            <ul class="list-disc pl-4 mt-1">
              <li v-for="(e, idx) in importPreview.errors.slice(0, 5)" :key="idx">
                第 {{ e.row }} 行: {{ e.message }}
              </li>
            </ul>
          </div>

          <div v-if="importPreview.warnings && importPreview.warnings.length > 0" class="text-xs text-amber-700 bg-amber-50 p-2 rounded">
            <strong>告警提示:</strong> 共 {{ importPreview.warnings.length }} 条提示（如重复项将自动忽略）
          </div>

          <div class="pt-2 flex gap-3">
            <button class="btn btn-outline flex-1" @click="importPreview = null">重新选择</button>
            <button
              class="btn btn-dark flex-1"
              :disabled="importConfirming || !importPreview.can_confirm"
              @click="confirmImport"
            >
              {{ importConfirming ? '正在落库…' : '✅ 确认整批原子落库' }}
            </button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 弹窗 3: 智能抽查推荐 -->
    <el-dialog v-model="showSmartSampleDialog" title="⚡ 智能抽查推荐 (按规则筛选当周需查课)" width="640px">
      <div class="space-y-4">
        <div class="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 leading-relaxed">
          <strong>🎯 算法策略与高校教务规范：</strong><br/>
          • <b>早八重点查</b>：默认优先筛选上午 1-2 大节（考勤旷课高发时段）。<br/>
          • <b>免查规则过滤</b>：自动剔除体育课、实验/实训课、在线通选网课，不占用查课力量。<br/>
          • <b>班级均衡配额</b>：每个教学班每周按指定上限抽查，防止查课过度集中或遗漏。<br/>
          • <b>相同课时合流</b>：同一教室同一时段的多班合堂已自动合并，一趟查完。
        </div>

        <div class="grid grid-cols-2 gap-3 text-xs bg-gray-50 p-3 rounded-lg border border-gray-200">
          <div>
            <label class="block font-bold text-gray-700 mb-1">每班每周抽查上限 (节)</label>
            <input
              v-model.number="smartSampleForm.max_tasks_per_class"
              type="number"
              min="1"
              max="5"
              class="input w-full"
            />
          </div>
          <div>
            <label class="block font-bold text-gray-700 mb-1">抽查比例 (0.1 ~ 1.0)</label>
            <input
              v-model.number="smartSampleForm.sample_ratio"
              type="number"
              min="0.1"
              max="1.0"
              step="0.05"
              class="input w-full"
            />
          </div>
        </div>

        <div class="space-y-2 text-xs">
          <label class="inline-flex items-center gap-2 cursor-pointer font-medium text-gray-700">
            <input v-model="smartSampleForm.morning_only" type="checkbox" class="rounded text-blue-600" />
            <span>仅抽查上午 1-2 节 (早八课堂高优考勤)</span>
          </label>
          <div>
            <label class="inline-flex items-center gap-2 cursor-pointer font-medium text-gray-700">
              <input v-model="smartSampleForm.exclude_already_generated" type="checkbox" class="rounded text-blue-600" />
              <span>排除当周已下发任务的课次 (不重复下发)</span>
            </label>
          </div>
        </div>

        <div>
          <button
            class="btn btn-dark w-full py-2.5 text-center font-bold"
            :disabled="smartSampling"
            @click="runSmartSample"
          >
            {{ smartSampling ? '正在运算推荐课次…' : '🔍 计算智能推荐课次' }}
          </button>
        </div>

        <!-- 计算结果预览 -->
        <div v-if="smartSampleResult" class="p-3 bg-blue-50 border border-blue-200 rounded-lg space-y-2">
          <div class="flex justify-between items-center text-xs">
            <span class="font-bold text-blue-900">
              推荐查课清单：共精选 {{ smartSampleResult.sampled_count }} 门课次
            </span>
            <span class="text-blue-700">
              (候选池共 {{ smartSampleResult.total_candidates }} 门课)
            </span>
          </div>

          <div v-if="smartSampleResult.items && smartSampleResult.items.length > 0" class="max-h-48 overflow-y-auto bg-white p-2 rounded border border-blue-100 text-xs divide-y divide-gray-100">
            <div v-for="item in smartSampleResult.items.slice(0, 15)" :key="item.course_schedule_id" class="py-1.5 flex justify-between items-center">
              <div>
                <span class="font-bold text-gray-800">{{ item.course_name }}</span>
                <span class="text-gray-500 ml-2">{{ item.class_name }}</span>
              </div>
              <div class="text-right text-gray-600 font-mono">
                {{ item.inspection_date }} 第{{ item.start_period }}-{{ item.end_period }}节 {{ item.classroom }}
              </div>
            </div>
            <div v-if="smartSampleResult.items.length > 15" class="py-1 text-center text-gray-400 font-mono text-[11px]">
              ... 以及更多 {{ smartSampleResult.items.length - 15 }} 门课次
            </div>
          </div>

          <div class="pt-2 flex justify-end gap-2">
            <button class="btn btn-outline" @click="showSmartSampleDialog = false">取消</button>
            <button
              class="btn btn-dark"
              :disabled="smartSampleResult.sampled_count === 0"
              @click="applySmartSample"
            >
              ✨ 应用推荐并批量勾选 ({{ smartSampleResult.sampled_count }} 节)
            </button>
          </div>
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
.row-disabled { opacity: 0.45; }

.empty-box {
  padding: 60px 20px;
  text-align: center;
  color: var(--ink-mute);
}
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 14px; font-weight: 600; color: var(--ink-soft); margin-bottom: 4px; }
.empty-sub { font-size: 12px; }
</style>
