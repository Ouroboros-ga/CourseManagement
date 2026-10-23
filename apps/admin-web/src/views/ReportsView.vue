<script setup lang="ts">
import { collectPages } from '../utils/collectPages'
import { useDisplayPage } from '../composables/useDisplayPage'
import AppPagination from '../components/AppPagination.vue'
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../stores/session'
import AppIcon from '../components/AppIcon.vue'
import CampusDimensions from '../components/campus/CampusDimensions.vue'
import { detailBelongsToClass, taskBelongsToClass } from '../utils/reportClassIdentity'
import {
  listStudents,
  type StudentItem
} from '../api/academic'
import {
  getAttendanceStats,
  exportAttendanceAnalytics,
  exportAttendanceDetailWord,
  exportStudyAttendanceExcel,
  type AttendanceStatsResponse,
  type ClassStatsItem,
  type TaskStatsItem,
  type AbnormalDetailItem
} from '../api/reports'

const route = useRoute()
const sessionStore = useSessionStore()

const loading = ref(false)
const downloadLoading = ref(false)
const exportLoading = ref(false)

const activeTab = ref<'class' | 'task' | 'detail'>('class')
const selectedWeek = ref<number>(1)
const attendanceStats = ref<AttendanceStatsResponse | null>(null)

// 行政班看板筛选与排序状态
const classSearch = ref('')
const selectedGrade = ref('ALL')
const selectedTier = ref('ALL')
const classSort = ref<'rate_desc' | 'rate_asc' | 'exp_desc'>('rate_asc')

// 教学班/课堂看板筛选状态
const taskSearch = ref('')
const taskOnlyAbnormal = ref(false)
const taskSort = ref<'time_asc' | 'rate_asc' | 'rate_desc'>('time_asc')

// 初始化周次
onMounted(() => {
  if (route.query.week) {
    selectedWeek.value = Number(route.query.week)
  } else if (sessionStore.currentWeekNo) {
    selectedWeek.value = sessionStore.currentWeekNo
  }
  if (route.query.tab) {
    const t = String(route.query.tab)
    if (t === 'class' || t === 'task') activeTab.value = t
    else if (t === 'detail' || t === 'report') activeTab.value = 'detail'
  }
  if (sessionStore.currentSemesterId) {
    fetchReportData()
  }
})

watch(
  () => sessionStore.currentWeekNo,
  (wn) => {
    if (wn && !route.query.week) {
      selectedWeek.value = wn
    }
  }
)

// 学期或周次切换时刷新
watch(
  () => [sessionStore.currentSemesterId, selectedWeek.value],
  ([semId]) => {
    if (semId) {
      fetchReportData()
    }
  }
)

async function fetchReportData() {
  if (!sessionStore.currentSemesterId || !sessionStore.hasPermission('statistics.read')) return
  loading.value = true
  try {
    const semId = Number(sessionStore.currentSemesterId)
    const week = selectedWeek.value

    // 获取当周出勤统计（含行政班、教学班与详细考勤明细）
    try {
      const statsRes = await getAttendanceStats({ semester_id: semId, week_no: week, include_tasks: true })
      attendanceStats.value = statsRes
    } catch (e) {
      console.warn('获取考勤统计失败:', e)
      attendanceStats.value = null
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取数据失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

// ---------------- 计算属性：全院看板宏观洞察 ----------------
const overallRate = computed<number | null>(() => {
  if (!attendanceStats.value || !attendanceStats.value.overall) return null
  const o = attendanceStats.value.overall
  if (o.attendance_rate !== undefined && o.attendance_rate !== null) return o.attendance_rate
  return o.expected_count > 0 ? o.normal_count / o.expected_count : null
})

// 提取行政班级中出现的年级列表
const gradeOptions = computed<string[]>(() => {
  if (!attendanceStats.value?.classes) return []
  const set = new Set<string>()
  for (const c of attendanceStats.value.classes) {
    const m = c.class_name.match(/(20\d{2}|\d{2})/)
    if (m) {
      const g = m[1].length === 2 ? `20${m[1]}级` : `${m[1]}级`
      set.add(g)
    }
  }
  return Array.from(set).sort().reverse()
})

// 辅助方法：解析班级出勤率与梯队
function getClassRate(c: ClassStatsItem): number | null {
  if (c.attendance_rate !== undefined && c.attendance_rate !== null) return c.attendance_rate
  return c.expected_count > 0 ? c.normal_count / c.expected_count : null
}

function getClassTier(rate: number | null): 'EXCELLENT' | 'GOOD' | 'ATTENTION' | 'WARNING' | 'NONE' {
  if (rate === null) return 'NONE'
  if (rate >= 0.98) return 'EXCELLENT'
  if (rate >= 0.95) return 'GOOD'
  if (rate >= 0.90) return 'ATTENTION'
  return 'WARNING'
}

function getTierMeta(tier: string): { label: string; cls: string } {
  switch (tier) {
    case 'EXCELLENT': return { label: '优秀', cls: 'tag-green' }
    case 'GOOD': return { label: '正常', cls: 'tag-blue' }
    case 'ATTENTION': return { label: '关注', cls: 'tag-amber' }
    case 'WARNING': return { label: '预警', cls: 'tag-red' }
    default: return { label: '无数据', cls: 'tag-gray' }
  }
}

// 宏观梯队统计
const tierDistribution = computed(() => {
  const classes = attendanceStats.value?.classes || []
  let excellent = 0
  let good = 0
  let attention = 0
  let warning = 0

  for (const c of classes) {
    const t = getClassTier(getClassRate(c))
    if (t === 'EXCELLENT') excellent++
    else if (t === 'GOOD') good++
    else if (t === 'ATTENTION') attention++
    else if (t === 'WARNING') warning++
  }

  return { total: classes.length, excellent, good, attention, warning }
})

// 最高与最低到课率行政班（有效班级）
const classHighlights = computed(() => {
  const classes = (attendanceStats.value?.classes || []).filter(c => c.expected_count > 0)
  if (classes.length === 0) return { highest: null, lowest: null }
  const sorted = [...classes].sort((a, b) => (getClassRate(b) ?? 0) - (getClassRate(a) ?? 0))
  return {
    highest: sorted[0],
    lowest: sorted[sorted.length - 1]
  }
})

// 过滤与排序后的行政班列表
const filteredClasses = computed(() => {
  let list = [...(attendanceStats.value?.classes || [])]

  if (classSearch.value.trim()) {
    const kw = classSearch.value.trim().toLowerCase()
    list = list.filter(c =>
      c.class_name.toLowerCase().includes(kw) ||
      (c.head_teacher && c.head_teacher.toLowerCase().includes(kw)) ||
      (c.counselor && c.counselor.toLowerCase().includes(kw))
    )
  }

  if (selectedGrade.value !== 'ALL') {
    const target = selectedGrade.value.replace('级', '')
    list = list.filter(c => c.class_name.includes(target) || c.class_name.includes(target.slice(2)))
  }

  if (selectedTier.value !== 'ALL') {
    list = list.filter(c => getClassTier(getClassRate(c)) === selectedTier.value)
  }

  if (classSort.value === 'rate_desc') {
    list.sort((a, b) => (getClassRate(b) ?? -1) - (getClassRate(a) ?? -1))
  } else if (classSort.value === 'rate_asc') {
    list.sort((a, b) => (getClassRate(a) ?? 999) - (getClassRate(b) ?? 999))
  } else if (classSort.value === 'exp_desc') {
    list.sort((a, b) => b.expected_count - a.expected_count)
  }

  return list
})

// 教学班 / 课堂出勤率与过滤
function getTaskRate(t: TaskStatsItem): number | null {
  if (t.attendance_rate !== undefined && t.attendance_rate !== null) return t.attendance_rate
  return t.expected_count > 0 ? t.normal_count / t.expected_count : null
}

const filteredTasks = computed(() => {
  let list = [...(attendanceStats.value?.tasks || [])]

  if (taskSearch.value.trim()) {
    const kw = taskSearch.value.trim().toLowerCase()
    list = list.filter(t =>
      (t.course_name_snapshot || '').toLowerCase().includes(kw) ||
      (t.class_name_snapshot || '').toLowerCase().includes(kw) ||
      (t.classroom_snapshot || '').toLowerCase().includes(kw) ||
      (t.teacher_name_snapshot || '').toLowerCase().includes(kw)
    )
  }

  if (taskOnlyAbnormal.value) {
    list = list.filter(t => (t.abnormal_count || 0) > 0)
  }

  if (taskSort.value === 'time_asc') {
    list.sort((a, b) => {
      const dc = a.inspection_date.localeCompare(b.inspection_date)
      if (dc !== 0) return dc
      return (a.start_period || 0) - (b.start_period || 0)
    })
  } else if (taskSort.value === 'rate_asc') {
    list.sort((a, b) => (getTaskRate(a) ?? 999) - (getTaskRate(b) ?? 999))
  } else if (taskSort.value === 'rate_desc') {
    list.sort((a, b) => (getTaskRate(b) ?? -1) - (getTaskRate(a) ?? -1))
  }

  return list
})

// ---------------- 详细考勤表筛选与数据处理 ----------------
const detailSearch = ref('')
const detailTypeFilter = ref<string>('ALL')
const detailSort = ref<'date_desc' | 'date_asc' | 'type'>('date_desc')

const allAbnormalDetails = computed<AbnormalDetailItem[]>(() => {
  return attendanceStats.value?.details || []
})

const totalAbnormalCount = computed(() => {
  return allAbnormalDetails.value.length || attendanceStats.value?.overall.abnormal_count || 0
})

const filteredDetails = computed<AbnormalDetailItem[]>(() => {
  let list = [...allAbnormalDetails.value]

  if (detailTypeFilter.value !== 'ALL') {
    list = list.filter(d => d.attendance_type === detailTypeFilter.value)
  }

  if (detailSearch.value.trim()) {
    const kw = detailSearch.value.trim().toLowerCase()
    list = list.filter(d =>
      (d.name && d.name.toLowerCase().includes(kw)) ||
      (d.student_no && d.student_no.toLowerCase().includes(kw)) ||
      (d.class_name_snapshot && d.class_name_snapshot.toLowerCase().includes(kw)) ||
      (d.course_name && d.course_name.toLowerCase().includes(kw)) ||
      (d.teacher_name && d.teacher_name.toLowerCase().includes(kw)) ||
      (d.classroom && d.classroom.toLowerCase().includes(kw))
    )
  }

  if (detailSort.value === 'date_desc') {
    list.sort((a, b) => {
      const da = (a.inspection_date || '') + String(a.start_period || 0).padStart(2, '0')
      const db = (b.inspection_date || '') + String(b.start_period || 0).padStart(2, '0')
      return db.localeCompare(da)
    })
  } else if (detailSort.value === 'date_asc') {
    list.sort((a, b) => {
      const da = (a.inspection_date || '') + String(a.start_period || 0).padStart(2, '0')
      const db = (b.inspection_date || '') + String(b.start_period || 0).padStart(2, '0')
      return da.localeCompare(db)
    })
  } else if (detailSort.value === 'type') {
    const order: Record<string, number> = { ABSENT: 1, LATE: 2, LEAVE: 3 }
    list.sort((a, b) => (order[a.attendance_type] || 9) - (order[b.attendance_type] || 9))
  }

  return list
})

function formatDetailTypeBadge(type: string) {
  switch (type) {
    case 'ABSENT': return { label: '旷', cls: 'tag-red' }
    case 'LATE': return { label: '迟到', cls: 'tag-amber' }
    case 'LEAVE': return { label: '请假', cls: 'tag-blue' }
    default: return { label: type, cls: 'tag-gray' }
  }
}

// ---------------- 操作：多维分析 Excel 导出 ----------------
async function handleExportAnalytics() {
  if (!sessionStore.currentSemesterId) return
  exportLoading.value = true
  try {
    const { blob, filename } = await exportAttendanceAnalytics({
      semester_id: Number(sessionStore.currentSemesterId),
      week_no: selectedWeek.value
    })
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    ElMessage.success(`多维考勤分析报表【${filename}】已开始下载`)
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '导出失败'
    ElMessage.error(msg)
  } finally {
    exportLoading.value = false
  }
}

// ---------------- 操作：直接导出课堂考勤详表 (Word) ----------------
async function handleExportDetailWord() {
  if (!sessionStore.currentSemesterId) return
  downloadLoading.value = true
  try {
    const { blob, filename } = await exportAttendanceDetailWord({
      semester_id: Number(sessionStore.currentSemesterId),
      week_no: selectedWeek.value
    })
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    ElMessage.success(`独立课堂考勤详表【${filename}】已开始下载`)
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '导出详表失败'
    ElMessage.error(msg)
  } finally {
    downloadLoading.value = false
  }
}

// ---------------- 操作：直接导出自习与日常考勤表 (Excel) ----------------
async function handleExportStudyExcel() {
  if (!sessionStore.currentSemesterId) return
  downloadLoading.value = true
  try {
    const { blob, filename } = await exportStudyAttendanceExcel({
      semester_id: Number(sessionStore.currentSemesterId),
      week_no: selectedWeek.value
    })
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    ElMessage.success(`自习与日常考勤表【${filename}】已开始下载`)
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '导出自习考勤表失败'
    ElMessage.error(msg)
  } finally {
    downloadLoading.value = false
  }
}

// ---------------- 班级明细抽屉状态与数据处理 ----------------
const showClassDetailDrawer = ref(false)
const selectedClass = ref<ClassStatsItem | null>(null)
const classStudentsLoading = ref(false)
const classStudents = ref<StudentItem[]>([])
const classStudentKeyword = ref('')
const classStudentStatusFilter = ref<'ALL' | 'ABNORMAL' | 'NORMAL'>('ALL')
const detailTab = ref<'students' | 'tasks'>('students')
let classLoadRevision = 0
watch(() => JSON.stringify([sessionStore.currentUser?.id, sessionStore.workspaceCollegeId,
  sessionStore.currentSemesterId, selectedWeek.value, sessionStore.workspace?.authorization_revision]), () => {
  classLoadRevision++; selectedClass.value = null; showClassDetailDrawer.value = false
  classStudents.value = []; classStudentsLoading.value = false
}, { flush: 'sync' })

async function openClassDetail(c: ClassStatsItem) {
  const revision = ++classLoadRevision
  selectedClass.value = c
  showClassDetailDrawer.value = true
  classStudentKeyword.value = ''
  classStudentStatusFilter.value = 'ALL'
  detailTab.value = 'students'
  classStudents.value = []

  // 异步获取该行政班在学籍库中的全量底册名单
  classStudentsLoading.value = true
  try {
    const classId = c.class_id
    if (classId) {
      const items = await collectPages((page, page_size) => listStudents({ administrative_class_id: classId, page, page_size }), () => revision === classLoadRevision)
      if (revision === classLoadRevision) {
        classStudents.value = items
      }
    }
  } catch (err) {
    console.warn('获取班级学生底册失败:', err)
  } finally {
    if (revision === classLoadRevision) classStudentsLoading.value = false
  }
}

export interface StudentAttendanceRow {
  student_no: string
  name: string
  is_abnormal: boolean
  absent_count: number
  late_count: number
  leave_count: number
  total_abnormal: number
  records: AbnormalDetailItem[]
}

// 当周该行政班在所有巡查课堂中产生的非 NORMAL 违纪考勤记录
const classAbnormalDetails = computed<AbnormalDetailItem[]>(() => {
  if (!selectedClass.value || !attendanceStats.value?.details) return []
  return attendanceStats.value.details.filter(d => detailBelongsToClass(selectedClass.value!, d))
})

// 班级完整考勤名单：融合学籍底册与当周违纪记录，【置顶有情况的同学】
const classStudentRoster = computed<StudentAttendanceRow[]>(() => {
  if (!selectedClass.value) return []

  // 1. 归并当周此班级所有有情况（旷课/迟到/请假）的同学
  const abnormalMap = new Map<string, {
    student_no: string
    name: string
    absent_count: number
    late_count: number
    leave_count: number
    records: AbnormalDetailItem[]
  }>()

  for (const d of classAbnormalDetails.value) {
    const key = d.student_id ? `id:${d.student_id}` : `no:${d.student_no}`
    let item = abnormalMap.get(key)
    if (!item) {
      item = {
        student_no: d.student_no,
        name: d.name,
        absent_count: 0,
        late_count: 0,
        leave_count: 0,
        records: []
      }
      abnormalMap.set(key, item)
    }
    if (d.attendance_type === 'ABSENT') item.absent_count++
    else if (d.attendance_type === 'LATE') item.late_count++
    else if (d.attendance_type === 'LEAVE') item.leave_count++
    item.records.push(d)
  }

  // 2. 结合行政班全量底册学生
  const rows: StudentAttendanceRow[] = []
  const processedKeys = new Set<string>()

  for (const stu of classStudents.value) {
    const key = `id:${stu.id}`
    processedKeys.add(key)
    processedKeys.add(`no:${stu.student_no}`)
    const ab = abnormalMap.get(key) || abnormalMap.get(`no:${stu.student_no}`)
    if (ab) {
      rows.push({
        student_no: stu.student_no,
        name: stu.name || ab.name,
        is_abnormal: true,
        absent_count: ab.absent_count,
        late_count: ab.late_count,
        leave_count: ab.leave_count,
        total_abnormal: ab.absent_count + ab.late_count + ab.leave_count,
        records: ab.records
      })
    } else {
      rows.push({
        student_no: stu.student_no,
        name: stu.name,
        is_abnormal: false,
        absent_count: 0,
        late_count: 0,
        leave_count: 0,
        total_abnormal: 0,
        records: []
      })
    }
  }

  // 补充存在违纪但在底册中未匹配到的学生（确保有情况的同学绝不遗漏）
  for (const [key, ab] of abnormalMap.entries()) {
    if (!processedKeys.has(key)) {
      rows.push({
        student_no: ab.student_no,
        name: ab.name,
        is_abnormal: true,
        absent_count: ab.absent_count,
        late_count: ab.late_count,
        leave_count: ab.leave_count,
        total_abnormal: ab.absent_count + ab.late_count + ab.leave_count,
        records: ab.records
      })
    }
  }

  // 3. 【核心置顶排序算法】
  // 有情况（旷课/迟到/请假）的同学在名单最上方自动置顶！
  // 其次按违纪严重程度（旷课数降序 -> 迟到数降序 -> 请假数降序），全勤同学排在下方。
  rows.sort((a, b) => {
    // 违纪置顶
    if (a.is_abnormal !== b.is_abnormal) {
      return a.is_abnormal ? -1 : 1
    }
    // 旷课严重程度优先
    if (a.absent_count !== b.absent_count) {
      return b.absent_count - a.absent_count
    }
    // 迟到次数优先
    if (a.late_count !== b.late_count) {
      return b.late_count - a.late_count
    }
    // 请假次数优先
    if (a.leave_count !== b.leave_count) {
      return b.leave_count - a.leave_count
    }
    // 学号排序
    return (a.student_no || '').localeCompare(b.student_no || '')
  })

  return rows
})

const abnormalStudentCount = computed(() => classStudentRoster.value.filter(s => s.is_abnormal).length)
const normalStudentCount = computed(() => classStudentRoster.value.filter(s => !s.is_abnormal).length)

const filteredClassStudents = computed(() => {
  let list = classStudentRoster.value

  if (classStudentStatusFilter.value === 'ABNORMAL') {
    list = list.filter(s => s.is_abnormal)
  } else if (classStudentStatusFilter.value === 'NORMAL') {
    list = list.filter(s => !s.is_abnormal)
  }

  if (classStudentKeyword.value.trim()) {
    const kw = classStudentKeyword.value.trim().toLowerCase()
    list = list.filter(s =>
      s.name.toLowerCase().includes(kw) ||
      s.student_no.toLowerCase().includes(kw)
    )
  }

  return list
})

// 该班级当周关联的巡查课堂
const selectedClassTasks = computed(() => {
  if (!selectedClass.value || !attendanceStats.value?.tasks) return []
  const abnormalTaskIds = new Set(classAbnormalDetails.value.map(d => String(d.task_id)))
  return attendanceStats.value.tasks.filter(t =>
    taskBelongsToClass(selectedClass.value!, t) ||
    abnormalTaskIds.has(String(t.task_id))
  )
})

function formatViolationType(type: string): string {
  switch (type) {
    case 'ABSENT': return '旷课'
    case 'LATE': return '迟到'
    case 'LEAVE': return '请假'
    case 'NORMAL': return '正常'
    default: return type
  }
}

const { page: display0Page, rows: display0Rows, total: display0Total } = useDisplayPage(() => filteredClasses.value)
const { page: display1Page, rows: display1Rows, total: display1Total } = useDisplayPage(() => filteredTasks.value)
const { page: display2Page, rows: display2Rows, total: display2Total } = useDisplayPage(() => filteredDetails.value)
const { page: display3Page, rows: display3Rows, total: display3Total } = useDisplayPage(() => filteredClassStudents.value)
const { page: display4Page, rows: display4Rows, total: display4Total } = useDisplayPage(() => selectedClassTasks.value)
</script>

<template>
  <div class="report-page" v-loading="loading">
    <CampusDimensions />
    <!-- 页头 -->
    <header class="page-head">
      <div class="crumb font-mono">
        <span>{{ sessionStore.currentSemesterName || '当前学期' }}</span>
        <em>●</em>
        <span>第 {{ selectedWeek }} 周</span>
        <em>●</em>
        <span>ATTENDANCE & ROSTER</span>
      </div>
      <h1>考勤统计与详细考勤看板</h1>
      <p class="sub">
        覆盖行政班到课率、教学班与课堂出勤明细的全院宏观分析，支持多维数据穿透、标准详细考勤表（Word / Excel）快速导出。
      </p>

      <div class="head-actions">
        <div class="week-picker">
          <span class="wp-label font-mono">WEEK</span>
          <select v-model="selectedWeek" class="wp-select font-mono">
            <option v-for="w in sessionStore.totalWeeks" :key="w" :value="w">
              第 {{ w }} 周
            </option>
          </select>
        </div>
        <button
          class="btn btn-dark btn-sm"
          :disabled="downloadLoading || !attendanceStats"
          title="导出100%对齐模板格式的独立【课堂考勤详表】Word文档（居中标题+5列考勤明细）"
          @click="handleExportDetailWord"
        >
          <AppIcon v-if="!downloadLoading" name="download" :size="13" />
          <span>{{ downloadLoading ? '正在导出…' : '导出详细考勤表 (Word)' }}</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :disabled="downloadLoading || !attendanceStats"
          title="导出100%对齐模板格式的【自习与日常考勤表】Excel文档（4列规范）"
          @click="handleExportStudyExcel"
        >
          <AppIcon v-if="!downloadLoading" name="download" :size="13" />
          <span>导出自习考勤表 (Excel)</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :disabled="exportLoading || !attendanceStats"
          title="导出包含全院看板、行政班与教学班明细的多 Sheet 分析 Excel"
          @click="handleExportAnalytics"
        >
          <AppIcon v-if="!exportLoading" name="download" :size="13" />
          <span>{{ exportLoading ? '正在导出…' : '导出到课率分析 (Excel)' }}</span>
        </button>
        <button class="btn btn-ghost btn-sm" @click="fetchReportData">刷新数据</button>
      </div>
    </header>

    <!-- 宏观统计分栏（无边框 · 细线分隔） -->
    <el-alert v-if="attendanceStats?.exception_count" :title="`查课异常 ${attendanceStats.exception_count} 次，已从有效应查和漏查统计中排除；可在查课安排筛选异常查看。`" type="warning" :closable="false" />
    <section v-if="attendanceStats" class="stat-row kpi-row">
      <div class="stat-cell">
        <div class="label">全院综合到课率</div>
        <div class="value" :class="overallRate !== null && overallRate < 0.95 ? 'c-accent' : ''">
          {{ overallRate !== null ? (overallRate * 100).toFixed(1) + '%' : '—' }}
        </div>
        <div class="prog kpi-prog">
          <i
            :style="{
              width: `${Math.min(100, (overallRate || 0) * 100)}%`,
              background: overallRate !== null && overallRate < 0.95 ? 'var(--accent)' : 'var(--green)'
            }"
          ></i>
        </div>
        <div class="note">
          应到 <b class="font-mono">{{ attendanceStats.overall.expected_count }}</b> · 实到
          <b class="font-mono">{{ attendanceStats.overall.normal_count }}</b> 人次
        </div>
      </div>

      <div class="stat-cell">
        <div class="label">考勤异常人次</div>
        <div class="value" :class="attendanceStats.overall.abnormal_count > 0 ? 'c-amber' : 'c-green'">
          {{ attendanceStats.overall.abnormal_count }}
        </div>
        <div class="note font-mono">
          旷课 <b class="c-accent">{{ attendanceStats.overall.absent_count }}</b> · 迟到
          <b class="c-amber">{{ attendanceStats.overall.late_count }}</b> · 请假
          <b class="c-blue">{{ attendanceStats.overall.leave_count }}</b>
        </div>
        <div class="note">
          异常率
          <b class="font-mono">{{
            attendanceStats.overall.abnormal_rate !== null && attendanceStats.overall.abnormal_rate !== undefined
              ? (attendanceStats.overall.abnormal_rate * 100).toFixed(1) + '%'
              : '0.0%'
          }}</b>
        </div>
      </div>

      <div class="stat-cell">
        <div class="label">行政班表现梯队</div>
        <div class="value">{{ tierDistribution.total }}<em class="unit">个班级</em></div>
        <div class="tier-strip">
          <i class="ts ts-green" :style="{ flex: tierDistribution.excellent || 0.01 }" title="优秀 ≥98%"></i>
          <i class="ts ts-blue" :style="{ flex: tierDistribution.good || 0.01 }" title="正常 95–98%"></i>
          <i class="ts ts-amber" :style="{ flex: tierDistribution.attention || 0.01 }" title="关注 90–95%"></i>
          <i class="ts ts-red" :style="{ flex: tierDistribution.warning || 0.01 }" title="预警 <90%"></i>
        </div>
        <div class="note font-mono">
          优 {{ tierDistribution.excellent }} · 良 {{ tierDistribution.good }} · 关
          {{ tierDistribution.attention }} · 警 {{ tierDistribution.warning }}
        </div>
      </div>

      <div class="stat-cell">
        <div class="label">有效查课课堂</div>
        <div class="value">{{ attendanceStats.eligible_task_count }}<em class="unit">堂</em></div>
        <div class="note">
          平均每堂应到
          <b class="font-mono">{{
            attendanceStats.eligible_task_count > 0
              ? (attendanceStats.overall.expected_count / attendanceStats.eligible_task_count).toFixed(0)
              : '—'
          }}</b>
          人
        </div>
        <div class="note">已形成正式考勤 · 纳入统计分母</div>
      </div>

      <div class="stat-cell">
        <div class="label">详细考勤记录</div>
        <div class="value font-mono" :class="totalAbnormalCount > 0 ? 'c-amber' : 'c-green'">
          {{ totalAbnormalCount }}<em class="unit">条明细</em>
        </div>
        <div class="note">
          <span v-if="totalAbnormalCount === 0" class="tag tag-green">全院全勤</span>
          <span v-else class="tag tag-amber">{{ totalAbnormalCount }} 人次违纪</span>
        </div>
        <div class="note">标准 5 列格式 · 随时一键导出</div>
      </div>
    </section>

    <!-- 编号 Tab 导航 -->
    <nav class="tab-nav">
      <button class="tab-btn" :class="{ active: activeTab === 'class' }" @click="activeTab = 'class'">
        <span class="tab-no font-mono">01</span>
        <span>行政班到课率</span>
        <span class="tab-count font-mono">{{ attendanceStats?.classes.length || 0 }}</span>
      </button>
      <button class="tab-btn" :class="{ active: activeTab === 'task' }" @click="activeTab = 'task'">
        <span class="tab-no font-mono">02</span>
        <span>教学班与课堂</span>
        <span class="tab-count font-mono">{{ attendanceStats?.tasks?.length || attendanceStats?.eligible_task_count || 0 }}</span>
      </button>
      <button class="tab-btn" :class="{ active: activeTab === 'detail' }" @click="activeTab = 'detail'">
        <span class="tab-no font-mono">03</span>
        <span>详细考勤表</span>
        <span class="tab-count font-mono">{{ totalAbnormalCount }}</span>
      </button>
    </nav>

    <!-- ============ TAB 01 · 行政班到课率 ============ -->
    <div v-show="activeTab === 'class'">
      <!-- 洞察提要 -->
      <div v-if="classHighlights.highest || classHighlights.lowest" class="insight-strip">
        <div class="is-item">
          <span class="tag tag-green">榜首</span>
          <span class="is-name">{{ classHighlights.highest?.class_name }}</span>
          <span class="is-val font-mono c-green">
            {{ ((getClassRate(classHighlights.highest!) ?? 0) * 100).toFixed(1) }}%
          </span>
          <span class="is-sub">
            应到 {{ classHighlights.highest?.expected_count }} · 实到 {{ classHighlights.highest?.normal_count }}
          </span>
        </div>
        <template v-if="classHighlights.lowest && getClassRate(classHighlights.lowest!) !== null && getClassRate(classHighlights.lowest!)! < 0.95">
          <div class="is-sep"></div>
          <div class="is-item">
            <span class="tag tag-red">需帮扶</span>
            <span class="is-name">{{ classHighlights.lowest?.class_name }}</span>
            <span class="is-val font-mono c-accent">
              {{ ((getClassRate(classHighlights.lowest!) ?? 0) * 100).toFixed(1) }}%
            </span>
            <span class="is-sub">
              旷课 {{ classHighlights.lowest?.absent_count }} · 迟到 {{ classHighlights.lowest?.late_count }}
            </span>
          </div>
        </template>
      </div>

      <!-- 筛选条 -->
      <div class="filter-bar">
        <div class="fgroup fgroup-grow">
          <AppIcon name="search" :size="13" />
          <input v-model="classSearch" type="text" class="f-input" placeholder="搜索班级 / 班主任 / 辅导员…" />
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>年级</label>
          <select v-model="selectedGrade" class="input">
            <option value="ALL">全部年级</option>
            <option v-for="g in gradeOptions" :key="g" :value="g">{{ g }}</option>
          </select>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>梯队</label>
          <select v-model="selectedTier" class="input">
            <option value="ALL">全部状态</option>
            <option value="EXCELLENT">优秀 ≥98%</option>
            <option value="GOOD">正常 95–98%</option>
            <option value="ATTENTION">关注 90–95%</option>
            <option value="WARNING">预警 &lt;90%</option>
          </select>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>排序</label>
          <select v-model="classSort" class="input">
            <option value="rate_desc">到课率 高 → 低</option>
            <option value="rate_asc">到课率 低 → 高</option>
            <option value="exp_desc">应到规模 大 → 小</option>
          </select>
        </div>
        <div class="f-count font-mono">展示 {{ filteredClasses.length }} / {{ attendanceStats?.classes.length || 0 }} 班</div>
      </div>

      <!-- 行政班表格 -->
      <div class="tbl-wrap">
        <div v-if="filteredClasses.length === 0" class="empty-text">无匹配的行政班级考勤数据。</div>
        <table v-else class="tbl">
          <thead>
            <tr>
              <th style="width: 52px;">排名</th>
              <th>行政班级</th>
              <th>梯队状态</th>
              <th class="ta-r">应到</th>
              <th class="ta-r">实到</th>
              <th class="ta-r">迟到</th>
              <th class="ta-r">旷课</th>
              <th class="ta-r">请假</th>
              <th style="width: 180px;">到课率</th>
              <th class="ta-r">缺勤率</th>
              <th class="ta-c">数据有效性</th>
              <th class="ta-c" style="width: 72px;">明细</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(c, idx) in display0Rows"
              :key="`${c.college_id || ''}:${c.class_id || c.class_name}`"
              class="clickable-row"
              @click="openClassDetail(c)"
            >
              <td class="cell-mono rank">{{ String(idx + 1).padStart(2, '0') }}</td>
              <td>
                <div class="cell-main-row">
                  <span class="cell-main fw-600">{{ c.class_name }}</span>
                  <span class="class-click-hint font-mono">详情 &rarr;</span>
                </div>
                <div v-if="c.head_teacher || c.counselor" class="cell-sub">
                  <template v-if="c.head_teacher">班主任 {{ c.head_teacher }}</template>
                  <template v-if="c.head_teacher && c.counselor"> · </template>
                  <template v-if="c.counselor">辅导员 {{ c.counselor }}</template>
                </div>
              </td>
              <td>
                <span class="tag" :class="getTierMeta(getClassTier(getClassRate(c))).cls">
                  {{ getTierMeta(getClassTier(getClassRate(c))).label }}
                </span>
              </td>
              <td class="cell-mono ta-r">{{ c.expected_count }}</td>
              <td class="cell-mono ta-r c-green fw-600">{{ c.normal_count }}</td>
              <td class="cell-mono ta-r" :class="c.late_count > 0 ? 'c-amber fw-600' : 'cell-sub'">{{ c.late_count }}</td>
              <td class="cell-mono ta-r" :class="c.absent_count > 0 ? 'c-accent fw-600' : 'cell-sub'">{{ c.absent_count }}</td>
              <td class="cell-mono ta-r cell-sub">{{ c.leave_count }}</td>
              <td>
                <div class="rate-cell">
                  <span
                    class="rate-val font-mono"
                    :class="getClassRate(c) !== null && getClassRate(c)! < 0.90 ? 'c-accent fw-600' : (getClassRate(c) !== null && getClassRate(c)! >= 0.98 ? 'c-green fw-600' : '')"
                  >
                    {{ getClassRate(c) !== null ? (getClassRate(c)! * 100).toFixed(1) + '%' : '—' }}
                  </span>
                  <div class="prog rate-prog">
                    <i
                      :style="{
                        width: `${Math.min(100, (getClassRate(c) ?? 0) * 100)}%`,
                        background: getClassRate(c) !== null && getClassRate(c)! < 0.90 ? 'var(--accent)' : (getClassRate(c) !== null && getClassRate(c)! >= 0.98 ? 'var(--green)' : 'var(--blue)')
                      }"
                    ></i>
                  </div>
                </div>
              </td>
              <td class="cell-mono ta-r cell-sub">
                {{ c.abnormal_rate !== null && c.abnormal_rate !== undefined ? (c.abnormal_rate * 100).toFixed(1) + '%' : '—' }}
              </td>
              <td class="ta-c">
                <span v-if="c.class_ratio_available" class="tag tag-green" title="名单及分母完全对齐">有效</span>
                <span v-else class="tag tag-amber" :title="`人工只调总数剔除 ${c.excluded_task_count} 堂`">剔除 {{ c.excluded_task_count }}</span>
              </td>
              <td class="ta-c">
                <button class="btn-text font-mono" @click.stop="openClassDetail(c)">
                  查看 &rarr;
                </button>
              </td>
            </tr>
          </tbody>
        </table>
<AppPagination v-model:current-page="display0Page" :total="display0Total" />
      </div>
    </div>

    <!-- ============ TAB 02 · 教学班与课堂 ============ -->
    <div v-show="activeTab === 'task'">
      <div class="filter-bar">
        <div class="fgroup fgroup-grow">
          <AppIcon name="search" :size="13" />
          <input v-model="taskSearch" type="text" class="f-input" placeholder="搜索课程 / 教学班 / 教室 / 教师…" />
        </div>
        <div class="fsep"></div>
        <label class="fgroup chk-row">
          <input v-model="taskOnlyAbnormal" type="checkbox" class="chk" />
          <span>仅看有缺勤异常课堂</span>
        </label>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>排序</label>
          <select v-model="taskSort" class="input">
            <option value="time_asc">查课时间 先 → 后</option>
            <option value="rate_asc">到课率 低 → 高（找异常）</option>
            <option value="rate_desc">到课率 高 → 低</option>
          </select>
        </div>
        <div class="f-count font-mono">展示 {{ filteredTasks.length }} / {{ attendanceStats?.tasks?.length || 0 }} 堂</div>
      </div>

      <div class="tbl-wrap">
        <div v-if="filteredTasks.length === 0" class="empty-text">无匹配的教学班或巡查课堂数据。</div>
        <table v-else class="tbl">
          <thead>
            <tr>
              <th style="width: 150px;">查课日期 / 节次</th>
              <th>课程名称</th>
              <th>教学班 / 合班</th>
              <th>教室</th>
              <th class="ta-r">应到</th>
              <th class="ta-r">实到</th>
              <th class="ta-r">异常</th>
              <th style="width: 170px;">课堂到课率</th>
              <th class="ta-c">出勤状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in display1Rows" :key="t.task_id">
              <td>
                <div class="cell-main font-mono">{{ t.inspection_date }}</div>
                <div class="cell-sub font-mono">
                  {{ t.start_period && t.end_period ? `第 ${t.start_period}–${t.end_period} 节` : '全天' }}
                </div>
              </td>
              <td>
                <div class="cell-main">{{ t.course_name_snapshot || '—' }}</div>
                <div v-if="t.teacher_name_snapshot" class="cell-sub">授课教师 {{ t.teacher_name_snapshot }}</div>
              </td>
              <td class="cell-sub">{{ t.class_name_snapshot || '—' }}</td>
              <td><span class="room-pill font-mono">{{ t.classroom_snapshot || '—' }}</span></td>
              <td class="cell-mono ta-r">{{ t.expected_count }}</td>
              <td class="cell-mono ta-r c-green fw-600">{{ t.normal_count }}</td>
              <td class="cell-mono ta-r">
                <span v-if="t.abnormal_count > 0" class="c-accent fw-600">{{ t.abnormal_count }}</span>
                <span v-else class="cell-sub">0</span>
              </td>
              <td>
                <div class="rate-cell">
                  <span
                    class="rate-val font-mono"
                    :class="getTaskRate(t) !== null && getTaskRate(t)! < 0.90 ? 'c-accent fw-600' : (getTaskRate(t) !== null && getTaskRate(t)! >= 0.98 ? 'c-green fw-600' : '')"
                  >
                    {{ getTaskRate(t) !== null ? (getTaskRate(t)! * 100).toFixed(1) + '%' : '—' }}
                  </span>
                  <div class="prog rate-prog">
                    <i
                      :style="{
                        width: `${Math.min(100, (getTaskRate(t) ?? 0) * 100)}%`,
                        background: getTaskRate(t) !== null && getTaskRate(t)! < 0.90 ? 'var(--accent)' : (getTaskRate(t) !== null && getTaskRate(t)! >= 0.98 ? 'var(--green)' : 'var(--blue)')
                      }"
                    ></i>
                  </div>
                </div>
              </td>
              <td class="ta-c">
                <span v-if="t.absent_count > 0" class="tag tag-red">旷课 {{ t.absent_count }}</span>
                <span v-else-if="t.late_count > 0" class="tag tag-amber">迟到 {{ t.late_count }}</span>
                <span v-else-if="t.leave_count > 0" class="tag tag-blue">请假 {{ t.leave_count }}</span>
                <span v-else class="tag tag-green">全勤</span>
              </td>
            </tr>
          </tbody>
        </table>
<AppPagination v-model:current-page="display1Page" :total="display1Total" />
      </div>
    </div>

    <!-- ============ TAB 03 · 详细考勤表 ============ -->
    <div v-show="activeTab === 'detail'">
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div>
            <h3>课堂考勤详细记录表</h3>
            <div class="meta font-mono">
              第 {{ selectedWeek }} 周共登记 {{ filteredDetails.length }} / {{ allAbnormalDetails.length }} 条考勤明细 · 严格对齐 5 列 Word 详表规范
            </div>
          </div>
          <div class="tbl-tools">
            <button
              class="btn btn-dark btn-sm"
              :disabled="downloadLoading || !attendanceStats"
              title="导出100%对齐模板格式的独立【课堂考勤详表】Word文档（居中标题+5列考勤明细）"
              @click="handleExportDetailWord"
            >
              <AppIcon v-if="!downloadLoading" name="download" :size="12" />
              <span>{{ downloadLoading ? '正在导出…' : '导出详细考勤表 (Word)' }}</span>
            </button>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="downloadLoading || !attendanceStats"
              title="导出100%对齐模板格式的4列自习与日常考勤 Excel 表格"
              @click="handleExportStudyExcel"
            >
              <AppIcon v-if="!downloadLoading" name="download" :size="12" />
              <span>导出自习考勤表 (Excel)</span>
            </button>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="exportLoading || !attendanceStats"
              title="导出包含全院看板、行政班与教学班明细的多 Sheet 分析 Excel"
              @click="handleExportAnalytics"
            >
              <AppIcon v-if="!exportLoading" name="download" :size="12" />
              <span>{{ exportLoading ? '正在导出…' : '导出到课率分析 (Excel)' }}</span>
            </button>
          </div>
        </div>

        <!-- 详细考勤表筛选栏 -->
        <div class="filter-bar">
          <div class="fgroup fgroup-grow">
            <AppIcon name="search" :size="13" />
            <input
              v-model="detailSearch"
              type="text"
              class="f-input"
              placeholder="搜索学生姓名 / 学号 / 班级 / 课程 / 教师 / 教室…"
            />
          </div>
          <div class="fsep"></div>
          <div class="fgroup">
            <label>考勤情况</label>
            <select v-model="detailTypeFilter" class="input">
              <option value="ALL">全部异常</option>
              <option value="ABSENT">旷课 (缺勤)</option>
              <option value="LATE">迟到</option>
              <option value="LEAVE">请假</option>
            </select>
          </div>
          <div class="fsep"></div>
          <div class="fgroup">
            <label>排序</label>
            <select v-model="detailSort" class="input">
              <option value="date_desc">日期时间 新 → 旧</option>
              <option value="date_asc">日期时间 旧 → 新</option>
              <option value="type">缺勤严重程度优先</option>
            </select>
          </div>
          <div class="f-count font-mono">
            展示 {{ filteredDetails.length }} / {{ allAbnormalDetails.length }} 条
          </div>
        </div>

        <!-- 5 列详细考勤表格 (100% 对齐 Word 详表结构) -->
        <div v-if="filteredDetails.length === 0" class="empty-text">
          {{ allAbnormalDetails.length === 0 ? '本周全院查课全勤，暂无缺勤异常记录。' : '未找到匹配的考勤详细记录。' }}
        </div>
        <table v-else class="tbl">
          <thead>
            <tr>
              <th style="width: 120px;">日期</th>
              <th style="width: 150px;">班级</th>
              <th>课程</th>
              <th style="width: 170px;">姓名 / 学号</th>
              <th class="ta-c" style="width: 100px;">迟/退/旷</th>
              <th style="width: 180px;">节次与教室</th>
              <th style="width: 120px;">任课教师</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(d, idx) in display2Rows" :key="idx">
              <td class="cell-mono fw-600">{{ d.date_display || d.inspection_date || '—' }}</td>
              <td>
                <span class="cell-main fw-600">{{ d.class_name_snapshot || '—' }}</span>
              </td>
              <td>
                <span class="cell-main">{{ d.course_name || '课堂考勤' }}</span>
              </td>
              <td>
                <div class="cell-main-row">
                  <span class="cell-main fw-600">{{ d.name }}</span>
                </div>
                <div class="cell-sub font-mono">{{ d.student_no }}</div>
              </td>
              <td class="ta-c">
                <span class="tag font-mono" :class="formatDetailTypeBadge(d.attendance_type).cls">
                  {{ formatDetailTypeBadge(d.attendance_type).label }}
                </span>
              </td>
              <td class="cell-mono cell-sub">
                <template v-if="d.start_period">
                  第 {{ d.start_period }}–{{ d.end_period }} 节
                </template>
                <template v-if="d.classroom">
                  · {{ d.classroom }}
                </template>
              </td>
              <td>
                <span class="cell-sub">{{ d.teacher_name || '—' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
<AppPagination v-model:current-page="display2Page" :total="display2Total" />
      </div>
    </div>

    <!-- ============ 行政班详细数据与学生考勤置顶抽屉 ============ -->
    <el-drawer
      v-model="showClassDetailDrawer"
      direction="rtl"
      size="min(820px, 94vw)"
      :lock-scroll="false"
      destroy-on-close
    >
      <template #header>
        <div v-if="selectedClass" class="drawer-header-wrap">
          <div class="dh-title-row">
            <span class="dh-title font-serif">{{ selectedClass.class_name }}</span>
            <span class="tag" :class="getTierMeta(getClassTier(getClassRate(selectedClass))).cls">
              {{ getTierMeta(getClassTier(getClassRate(selectedClass))).label }}
            </span>
            <span
              class="tag font-mono"
              :class="getClassRate(selectedClass) !== null && getClassRate(selectedClass)! < 0.90 ? 'tag-red' : (getClassRate(selectedClass) !== null && getClassRate(selectedClass)! >= 0.98 ? 'tag-green' : 'tag-blue')"
            >
              到课率 {{ getClassRate(selectedClass) !== null ? (getClassRate(selectedClass)! * 100).toFixed(1) + '%' : '—' }}
            </span>
          </div>
          <div class="dh-sub">
            <template v-if="selectedClass.head_teacher">班主任 {{ selectedClass.head_teacher }}</template>
            <template v-if="selectedClass.head_teacher && selectedClass.counselor"> · </template>
            <template v-if="selectedClass.counselor">辅导员 {{ selectedClass.counselor }}</template>
            <span class="dh-sep">|</span>
            <span class="dh-week font-mono">第 {{ selectedWeek }} 周考勤明细</span>
          </div>
        </div>
      </template>

      <div v-if="selectedClass" class="drawer-inner">
        <!-- 班级核心考勤指标看板 -->
        <div class="d-kpi-grid">
          <div class="d-kpi-card">
            <div class="dk-label">有效应到</div>
            <div class="dk-val font-mono">{{ selectedClass.expected_count }}<span class="dk-unit">人次</span></div>
          </div>
          <div class="d-kpi-card">
            <div class="dk-label">正常实到</div>
            <div class="dk-val font-mono c-green">{{ selectedClass.normal_count }}<span class="dk-unit">人次</span></div>
          </div>
          <div class="d-kpi-card" :class="{ 'card-warn': selectedClass.absent_count > 0 }">
            <div class="dk-label">旷课缺勤</div>
            <div class="dk-val font-mono" :class="selectedClass.absent_count > 0 ? 'c-accent' : 'c-mute'">
              {{ selectedClass.absent_count }}<span class="dk-unit">人次</span>
            </div>
          </div>
          <div class="d-kpi-card" :class="{ 'card-amber': selectedClass.late_count > 0 }">
            <div class="dk-label">迟到人次</div>
            <div class="dk-val font-mono" :class="selectedClass.late_count > 0 ? 'c-amber' : 'c-mute'">
              {{ selectedClass.late_count }}<span class="dk-unit">人次</span>
            </div>
          </div>
          <div class="d-kpi-card">
            <div class="dk-label">请假备案</div>
            <div class="dk-val font-mono c-blue">{{ selectedClass.leave_count }}<span class="dk-unit">人次</span></div>
          </div>
        </div>

        <!-- 抽屉内二级导航切换 -->
        <div class="d-tab-bar">
          <button
            class="d-tab-btn"
            :class="{ active: detailTab === 'students' }"
            @click="detailTab = 'students'"
          >
            学生考勤名单
            <span class="d-tab-badge font-mono">{{ classStudentRoster.length }}</span>
            <span v-if="abnormalStudentCount > 0" class="d-tab-warn font-mono">{{ abnormalStudentCount }} 人异常</span>
          </button>
          <button
            class="d-tab-btn"
            :class="{ active: detailTab === 'tasks' }"
            @click="detailTab = 'tasks'"
          >
            本周抽查课堂
            <span class="d-tab-badge font-mono">{{ selectedClassTasks.length }}</span>
          </button>
        </div>

        <!-- TAB 1: 学生名单（置顶有情况的同学） -->
        <div v-show="detailTab === 'students'" class="d-tab-content">
          <!-- 置顶规则提示条 -->
          <div class="pin-hint-bar">
            <div class="ph-icon">
              <AppIcon name="alert-triangle" :size="13" />
            </div>
            <div class="ph-text">
              <strong>智能置顶名单：</strong>已将本周存在违纪异常（旷课、迟到、请假）的同学<b>排在名单最上方置顶显示</b>；下方为全勤在籍同学。
            </div>
          </div>

          <!-- 筛选与搜索工具栏 -->
          <div class="d-toolbar">
            <div class="d-search">
              <AppIcon name="search" :size="13" />
              <input
                v-model="classStudentKeyword"
                type="text"
                class="d-search-input"
                placeholder="搜索学生姓名 / 学号…"
              />
            </div>
            <div class="d-chips">
              <button
                class="chip-btn"
                :class="{ active: classStudentStatusFilter === 'ALL' }"
                @click="classStudentStatusFilter = 'ALL'"
              >
                全部 <span class="font-mono">({{ classStudentRoster.length }})</span>
              </button>
              <button
                class="chip-btn chip-warn"
                :class="{ active: classStudentStatusFilter === 'ABNORMAL' }"
                @click="classStudentStatusFilter = 'ABNORMAL'"
              >
                有情况 <span class="font-mono">({{ abnormalStudentCount }})</span>
              </button>
              <button
                class="chip-btn chip-ok"
                :class="{ active: classStudentStatusFilter === 'NORMAL' }"
                @click="classStudentStatusFilter = 'NORMAL'"
              >
                全勤 <span class="font-mono">({{ normalStudentCount }})</span>
              </button>
            </div>
          </div>

          <!-- 学生列表加载或为空状态 -->
          <div v-if="classStudentsLoading && classStudentRoster.length === 0" class="d-loading font-mono">
            正在载入班级名单及考勤记录…
          </div>
          <div v-else-if="filteredClassStudents.length === 0" class="empty-text">
            未找到匹配的学生记录。
          </div>

          <!-- 学生考勤明细列表 -->
          <div v-else class="stu-list">
            <div
              v-for="(stu, sIdx) in display3Rows"
              :key="stu.student_no"
              class="stu-card"
              :class="{ 'stu-card-abnormal': stu.is_abnormal }"
            >
              <div class="stu-top">
                <div class="stu-ident">
                  <span class="stu-pin-index font-mono" :class="{ 'pin-active': stu.is_abnormal }">
                    {{ stu.is_abnormal ? '📌 置顶 ' + (sIdx + 1) : String(sIdx + 1).padStart(2, '0') }}
                  </span>
                  <span class="stu-name">{{ stu.name }}</span>
                  <span class="stu-no font-mono">{{ stu.student_no }}</span>
                </div>

                <!-- 状态徽章 -->
                <div class="stu-status-badges">
                  <template v-if="stu.is_abnormal">
                    <span v-if="stu.absent_count > 0" class="tag tag-red">
                      旷课 {{ stu.absent_count }} 次
                    </span>
                    <span v-if="stu.late_count > 0" class="tag tag-amber">
                      迟到 {{ stu.late_count }} 次
                    </span>
                    <span v-if="stu.leave_count > 0" class="tag tag-blue">
                      请假 {{ stu.leave_count }} 次
                    </span>
                  </template>
                  <template v-else>
                    <span class="tag tag-green">全勤</span>
                  </template>
                </div>
              </div>

              <!-- 违纪或考勤轨迹明细 -->
              <div v-if="stu.is_abnormal && stu.records.length > 0" class="stu-records">
                <div
                  v-for="(rec, rIdx) in stu.records"
                  :key="rIdx"
                  class="violation-pill"
                  :class="{
                    'vp-red': rec.attendance_type === 'ABSENT',
                    'vp-amber': rec.attendance_type === 'LATE',
                    'vp-blue': rec.attendance_type === 'LEAVE'
                  }"
                >
                  <span class="vp-date font-mono">{{ rec.date_display || rec.inspection_date }}</span>
                  <span v-if="rec.start_period" class="vp-period font-mono">
                    第 {{ rec.start_period }}–{{ rec.end_period }} 节
                  </span>
                  <span class="vp-course">{{ rec.course_name || '课堂考勤' }}</span>
                  <span v-if="rec.classroom" class="vp-room font-mono">{{ rec.classroom }}</span>
                  <span v-if="rec.teacher_name" class="vp-teacher">{{ rec.teacher_name }}</span>
                  <span class="vp-badge font-mono">{{ formatViolationType(rec.attendance_type) }}</span>
                </div>
              </div>
              <div v-else class="stu-ok-hint">
                <span class="cell-sub">本周查课无缺勤异常记录，全勤在籍</span>
              </div>
            </div>
<AppPagination v-model:current-page="display3Page" :total="display3Total" />
          </div>
        </div>

        <!-- TAB 2: 本周抽查课堂 -->
        <div v-show="detailTab === 'tasks'" class="d-tab-content">
          <div v-if="selectedClassTasks.length === 0" class="empty-text">
            本周未查到该班级作为主要受检对象的课堂记录。
          </div>
          <div v-else class="task-list">
            <div v-for="t in display4Rows" :key="t.task_id" class="task-card">
              <div class="tc-top">
                <div class="tc-time font-mono">
                  {{ t.inspection_date }} · {{ t.start_period && t.end_period ? `第 ${t.start_period}–${t.end_period} 节` : '全天' }}
                </div>
                <div class="tc-badges">
                  <span v-if="t.absent_count > 0" class="tag tag-red">旷课 {{ t.absent_count }} 人</span>
                  <span v-if="t.late_count > 0" class="tag tag-amber">迟到 {{ t.late_count }} 人</span>
                  <span v-if="t.leave_count > 0" class="tag tag-blue">请假 {{ t.leave_count }} 人</span>
                  <span v-if="t.abnormal_count === 0" class="tag tag-green">全勤</span>
                </div>
              </div>
              <div class="tc-course-row">
                <span class="tc-course">{{ t.course_name_snapshot || '未命名课程' }}</span>
                <span v-if="t.teacher_name_snapshot" class="tc-teacher">教师: {{ t.teacher_name_snapshot }}</span>
                <span v-if="t.classroom_snapshot" class="room-pill font-mono">{{ t.classroom_snapshot }}</span>
              </div>
              <div class="tc-meta">
                <span class="cell-sub">应到 {{ t.expected_count }} · 实到 {{ t.normal_count }} · 到课率 </span>
                <strong
                  class="font-mono"
                  :class="getTaskRate(t) !== null && getTaskRate(t)! < 0.90 ? 'c-accent' : (getTaskRate(t) !== null && getTaskRate(t)! >= 0.98 ? 'c-green' : 'c-blue')"
                >
                  {{ getTaskRate(t) !== null ? (getTaskRate(t)! * 100).toFixed(1) + '%' : '—' }}
                </strong>
              </div>
            </div>
<AppPagination v-model:current-page="display4Page" :total="display4Total" />
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.report-page { padding-bottom: 32px; }

/* ---------- 页头周次选择 ---------- */
.week-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  padding: 0 10px;
  height: 34px;
  background: var(--paper);
}
.wp-label {
  font-size: var(--text-caption);
  letter-spacing: 0.1em;
  color: var(--ink-mute);
}
.wp-select {
  border: none;
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
  outline: none;
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
}

/* ---------- 统计分栏（复用全局 stat-row，改为 5 列） ---------- */
.kpi-row {
  grid-template-columns: repeat(5, 1fr);
  margin-bottom: 28px;
}
.kpi-row .stat-cell { padding: 20px 22px; }
.kpi-row .unit {
  font-style: normal;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  font-weight: 400;
  color: var(--ink-mute);
  margin-left: 4px;
}
.kpi-prog {
  width: 100%;
  margin: 10px 0 10px;
}
.tier-strip {
  display: flex;
  height: 3px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  gap: 2px;
  margin: 12px 0 10px;
}
.ts { display: block; height: 100%; border-radius: var(--radius-sm); }
.ts-green { background: var(--green); }
.ts-blue { background: var(--blue); }
.ts-amber { background: var(--amber); }
.ts-red { background: var(--accent); }

/* ---------- 编号 Tab 导航 ---------- */
.tab-nav {
  display: flex;
  gap: 8px;
  padding: 0 4px;
  border-bottom: 2px solid var(--line);
  margin-bottom: 20px;
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  color: var(--ink-mute);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  transition: color var(--dur-f) var(--ease);
}
.tab-btn:hover { color: var(--ink); }
.tab-btn.active { color: var(--ink); border-bottom-color: var(--ink); }
.tab-no {
  font-size: var(--text-caption);
  letter-spacing: 0.08em;
  color: var(--ink-mute);
}
.tab-btn.active .tab-no { color: var(--accent); }
.tab-count {
  font-size: var(--text-caption);
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  background: var(--paper-deep);
  color: var(--ink-soft);
}
.tab-btn.active .tab-count { background: var(--ink); color: var(--paper); }
.tab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

/* ---------- 洞察提要条 ---------- */
.insight-strip {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
  padding: 12px 18px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--ink);
  border-radius: var(--radius);
  background: var(--paper-deep);
  margin-bottom: 0;
}
.is-item { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.is-name { font-weight: 700; color: var(--ink); }
.is-val { font-size: 14px; font-weight: 700; }
.is-sub { font-size: 11px; color: var(--ink-mute); }
.is-sep { width: 1px; height: 18px; background: var(--line-strong); }

/* ---------- 筛选条（与 ScheduleView 同构） ---------- */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-bottom: none;
  border-radius: var(--radius) var(--radius) 0 0;
  font-size: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
}
.fgroup { display: flex; align-items: center; gap: 8px; color: var(--ink-mute); }
.fgroup label { color: var(--ink-mute); font-weight: 500; white-space: nowrap; }
.fgroup-grow { flex: 1; min-width: 180px; }
.f-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  font-size: 12px;
  font-family: inherit;
  color: var(--ink);
  outline: none;
}
.f-input::placeholder { color: var(--ink-mute); }
.fsep { width: 1px; height: 16px; background: var(--line-strong); flex-shrink: 0; }
.f-count { margin-left: auto; font-size: 11px; color: var(--ink-mute); white-space: nowrap; }
.chk-row { cursor: pointer; user-select: none; color: var(--ink-soft); }
.filter-bar .input { font-size: 12px; padding: 6px 10px; }

/* ---------- 表格 ---------- */
.ta-r { text-align: right; }
.ta-c { text-align: center; }
.fw-600 { font-weight: 600; }
.rank { color: var(--ink-mute); }
.empty-text { padding: 32px 0; text-align: center; font-size: var(--text-xs); color: var(--ink-mute); }

.rate-cell { display: flex; align-items: center; gap: 10px; }
.rate-val { font-size: 12px; min-width: 48px; text-align: right; }
.rate-prog { flex: 1; width: auto; margin-right: 0; }

.room-pill {
  font-size: 11px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  color: var(--ink-soft);
}


/* ---------- 版本表 ---------- */
.role-tag { margin-left: 8px; font-size: var(--text-caption); }
.reason-cell {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dl-group { display: inline-flex; gap: 2px; }

/* ---------- 语义色工具 ---------- */
.c-green { color: var(--green); }
.c-amber { color: var(--amber); }
.c-accent { color: var(--accent); }
.c-blue { color: var(--blue); }
.kpi-version-val {
  font-size: 19px !important;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  line-height: 1.3;
  word-break: break-all;
}

@media (max-width: 1200px) {
  .kpi-row { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 768px) {
  .kpi-row { grid-template-columns: 1fr; }
}

/* ---------- 行政班列表行可点击 ---------- */
.clickable-row {
  cursor: pointer;
  transition: background-color var(--dur-f) var(--ease);
}
.clickable-row:hover {
  background-color: var(--paper-deep);
}
.cell-main-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.class-click-hint {
  font-size: 11px;
  color: var(--ink-mute);
  opacity: 0.6;
  transition: opacity var(--dur-f) var(--ease), color var(--dur-f) var(--ease);
}
.clickable-row:hover .class-click-hint {
  opacity: 1;
  color: var(--blue);
}
.btn-text {
  background: none;
  border: none;
  font-size: 12px;
  color: var(--blue);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: var(--radius-md);
  transition: background-color var(--dur-f) var(--ease), color var(--dur-f) var(--ease);
}
.btn-text:hover {
  background-color: var(--blue-soft);
  color: var(--ink);
}

/* ---------- 班级详情抽屉样式 ---------- */
.drawer-header-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dh-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dh-title {
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--ink);
}
.dh-sub {
  font-size: 12px;
  color: var(--ink-soft);
  display: flex;
  align-items: center;
  gap: 8px;
}
.dh-sep {
  color: var(--line-strong);
}
.dh-week {
  color: var(--ink-mute);
}

.drawer-inner {
  padding: 0 4px 24px;
}

/* 班级考勤指标小卡片 */
.d-kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 20px;
}
.d-kpi-card {
  padding: 12px 14px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.d-kpi-card.card-warn {
  border-color: color-mix(in srgb, var(--accent) 30%, transparent);
  background: color-mix(in srgb, var(--accent) 3%, transparent);
}
.d-kpi-card.card-amber {
  border-color: color-mix(in srgb, var(--amber) 30%, transparent);
  background: color-mix(in srgb, var(--amber) 3%, transparent);
}
.dk-label {
  font-size: 11px;
  color: var(--ink-mute);
}
.dk-val {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--ink);
}
.dk-unit {
  font-size: 11px;
  font-weight: 400;
  color: var(--ink-mute);
  margin-left: 2px;
}
.c-mute {
  color: var(--ink-mute);
}

/* 抽屉内二级导航 */
.d-tab-bar {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
}
.d-tab-btn {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-mute);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: -1px;
  transition: color var(--dur-f) var(--ease), border-color var(--dur-f) var(--ease);
}
.d-tab-btn:hover {
  color: var(--ink);
}
.d-tab-btn.active {
  color: var(--ink);
  border-bottom-color: var(--ink);
}
.d-tab-badge {
  font-size: var(--text-caption);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: var(--line);
  color: var(--ink-soft);
}
.d-tab-btn.active .d-tab-badge {
  background: var(--ink);
  color: var(--paper);
}
.d-tab-warn {
  font-size: var(--text-caption);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

/* 智能置顶提示条 */
.pin-hint-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--accent) 4%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--ink-soft);
  margin-bottom: 14px;
}
.ph-icon {
  color: var(--accent);
  display: flex;
  align-items: center;
}
.ph-text strong {
  color: var(--accent);
}
.ph-text b {
  color: var(--ink);
}

/* 工具栏 */
.d-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.d-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  flex: 1;
  max-width: 260px;
}
.d-search-input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 12px;
  color: var(--ink);
  width: 100%;
}
.d-search-input::placeholder {
  color: var(--ink-mute);
}
.d-chips {
  display: flex;
  gap: 6px;
}
.chip-btn {
  border: 1px solid var(--line);
  background: var(--paper-deep);
  color: var(--ink-soft);
  font-size: 11px;
  font-weight: 500;
  padding: 5px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--dur-f) var(--ease), border-color var(--dur-f) var(--ease);
}
.chip-btn:hover {
  background: var(--paper);
  border-color: var(--line-strong);
}
.chip-btn.active {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}
.chip-btn.chip-warn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--paper);
}
.chip-btn.chip-ok.active {
  background: var(--green);
  border-color: var(--green);
  color: var(--paper);
}

.d-loading {
  text-align: center;
  padding: 32px 0;
  font-size: 12px;
  color: var(--ink-mute);
}

/* 学生列表与置顶卡片 */
.stu-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.stu-card {
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  transition: border-color var(--dur-f) var(--ease), box-shadow var(--dur-f) var(--ease);
}
.stu-card-abnormal {
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  background: color-mix(in srgb, var(--accent) 2%, transparent);
  border-left: 3px solid var(--accent);
}
.stu-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.stu-ident {
  display: flex;
  align-items: center;
  gap: 10px;
}
.stu-pin-index {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-mute);
}
.stu-pin-index.pin-active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  padding: 1px 6px;
  border-radius: var(--radius);
}
.stu-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
}
.stu-no {
  font-size: 12px;
  color: var(--ink-mute);
}
.stu-status-badges {
  display: flex;
  gap: 6px;
}

/* 违纪记录列表药丸 */
.stu-records {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed color-mix(in srgb, var(--accent) 15%, transparent);
}
.violation-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  border-radius: var(--radius-md);
  font-size: 11px;
  line-height: 1.4;
  background: var(--paper-deep);
  border: 1px solid var(--line);
}
.violation-pill.vp-red {
  background: color-mix(in srgb, var(--accent) 6%, transparent);
  border-color: color-mix(in srgb, var(--accent) 25%, transparent);
  color: var(--accent);
}
.violation-pill.vp-amber {
  background: color-mix(in srgb, var(--amber) 6%, transparent);
  border-color: color-mix(in srgb, var(--amber) 25%, transparent);
  color: var(--amber);
}
.violation-pill.vp-blue {
  background: color-mix(in srgb, var(--blue) 6%, transparent);
  border-color: color-mix(in srgb, var(--blue) 25%, transparent);
  color: var(--blue);
}
.vp-date {
  font-weight: 700;
}
.vp-period {
  opacity: 0.85;
}
.vp-course {
  font-weight: 600;
}
.vp-room {
  opacity: 0.8;
}
.vp-teacher {
  opacity: 0.8;
}
.vp-badge {
  margin-left: auto;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--line);
}
.stu-ok-hint {
  font-size: 11px;
  color: var(--ink-mute);
  margin-top: 2px;
}

/* 课堂列表卡片 */
.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.task-card {
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tc-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tc-time {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-soft);
}
.tc-badges {
  display: flex;
  gap: 6px;
}
.tc-course-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.tc-course {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
}
.tc-teacher {
  font-size: 12px;
  color: var(--ink-mute);
}
.tc-meta {
  font-size: 12px;
  color: var(--ink-soft);
}
</style>
