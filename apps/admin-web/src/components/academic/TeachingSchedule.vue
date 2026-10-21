<script setup lang="ts">
import AppPagination from '../AppPagination.vue'
import { listCourseTypes, type CourseType } from '../../api/campus'
import { confirmGroupPlan } from '../../composables/confirmGroupAssignment'
import { ref, watch, onMounted, computed, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import {
  listTasks,
  queryCourseOccurrences,
  generateExactTasks,
  triggerAutoAssign,
  smartSampleOccurrences,
  type CourseOccurrence,
  type InspectionTaskItem,
  type SmartSampleResult
} from '../../api/tasks'
import {
  administrativeClassOptions,
  getMasterTimetable,
  exportCourseSchedulesExcel,
  type AdministrativeClassItem,
  type MasterTimetableItem
} from '../../api/academic'
import {
  uploadImportFile,
  confirmImportBatch,
  uploadBulkImport,
  type ImportPreviewResult,
  type BulkImportResult
} from '../../api/importer'
import { batchCreateSelfStudy, getTeachingClassRoster, type TeachingClassStudentItem } from '../../api/scopedAcademic'
import TaskStatusTag from '../../components/TaskStatusTag.vue'
import AppIcon from '../../components/AppIcon.vue'
import { formatPeriodText } from '../../utils/period'
import DispatchFilters from './DispatchFilters.vue'
import { useDispatchOptions } from '../../composables/useDispatchOptions'

const props = withDefaults(defineProps<{ mode?: 'legacy' | 'academic' | 'inspection'; openImport?: boolean; openSelfStudy?: boolean; importOnly?: boolean }>(), { mode: 'legacy', openImport: false, openSelfStudy: false, importOnly: false })
const sessionStore = useSessionStore()

const activeTab = ref<'dispatch' | 'master'>(props.mode === 'academic' ? 'master' : 'dispatch')
const loading = ref(false)
const dispatchError = ref('')
const dispatchLoading = ref(false)
const adminClasses = ref<AdministrativeClassItem[]>([])
const selectedAdminClassId = ref<string>('')

// ---- 课次下发Tab状态 ----
const occurrences = ref<CourseOccurrence[]>([])
const weekTasks = ref<InspectionTaskItem[]>([])
const occurrencePage = ref(1), occurrenceTotal = ref(0)
const weekTaskPage = ref(1), weekTaskTotal = ref(0)
const masterPage = ref(1), masterTotal = ref(0)
const visibleMasterRows = computed(() => masterTimetableList.value)
const rosterPage = ref(1)
const visibleRosterRows = computed(() => filteredRosterStudents.value.slice((rosterPage.value - 1) * 50, rosterPage.value * 50))
const selectedKeys = ref<string[]>([])
const executionGroupId = ref('')
const dispatchCourseTypeId = ref('')
const organizationMode = computed(() => !!sessionStore.campusRuntime?.scheduling)
const { types: dispatchCourseTypes, groups: executionGroups, error: dispatchOptionsError } = useDispatchOptions(() => ({
  collegeId: sessionStore.workspaceCollegeId, userId: String(sessionStore.currentUser?.id || ''),
  enabled: props.mode !== 'academic', readTypes: sessionStore.hasPermission('academic.course_type.read'),
  readGroups: sessionStore.hasPermission('volunteer.group.read')
}))
const organizationPending = computed(() => !organizationMode.value && executionGroups.value.length > 0)
watch(() => [sessionStore.currentUser?.id, sessionStore.workspaceCollegeId], () => {
  executionGroupId.value = ''; dispatchCourseTypeId.value = ''; adminClasses.value = []
})
watch(dispatchCourseTypeId, value => {
  const group = executionGroups.value.find(row => row.id === executionGroupId.value)
  if (value && group && !group.configuration?.course_type_ids.includes(value)) executionGroupId.value = ''
})
// 课程类型与执行组默认选中第一项；执行组优先选可用且包含当前课程类型的组。
watch([dispatchCourseTypes, executionGroups, dispatchOptionsError], () => {
  if (props.mode === 'academic' || dispatchOptionsError.value) return
  if (!dispatchCourseTypeId.value) {
    const active = dispatchCourseTypes.value.find(kind => kind.status === 'ACTIVE')
    if (active) dispatchCourseTypeId.value = active.id
  }
  if (!executionGroupId.value && executionGroups.value.length > 0) {
    const usable = executionGroups.value.find(row => row.status === 'ACTIVE' && !!row.config_version
      && (!dispatchCourseTypeId.value || row.configuration?.course_type_ids.includes(dispatchCourseTypeId.value)))
    executionGroupId.value = (usable ?? executionGroups.value[0]).id
  }
})
const selectionRevision = ref<string>('')
const selectionScope = ref<Record<string, unknown>>({})
const hasData = computed(() => occurrences.value.length > 0 || weekTasks.value.length > 0)

// ---- 全校总课表Tab状态 ----
const masterTimetableList = ref<MasterTimetableItem[]>([])
const masterLoading = ref(false)
const masterWeekday = ref<number | ''>('')
const masterWeekNo = ref<number | ''>(sessionStore.currentWeekNo || '')
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

// ---- 导入教务数据弹窗 ----
const showImportDialog = ref(false)
const importMode = ref<'bulk' | 'single'>('bulk')
const importTarget = ref<'admin_roster' | 'grid_timetable' | 'timetable'>('grid_timetable')
const importFile = ref<File | null>(null)
const importUploading = ref(false)
const importConfirming = ref(false)
const importPreview = ref<ImportPreviewResult | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// ---- 学院课程类型（供课表导入时指定课程类型，默认普通课） ----
const collegeCourseTypes = ref<CourseType[]>([])
const selectedCourseTypeId = ref<string>('')
const loadingCourseTypes = ref(false)

async function loadCollegeCourseTypes() {
  const cid = sessionStore.workspaceCollegeId
  if (!cid) return
  loadingCourseTypes.value = true
  try {
    const list = await listCourseTypes(cid)
    collegeCourseTypes.value = list.filter(t => t.status === 'ACTIVE')
    const regular = collegeCourseTypes.value.find(t => t.code === 'builtin_regular' || t.name === '普通课')
    if (regular) {
      selectedCourseTypeId.value = regular.id
    } else if (collegeCourseTypes.value.length > 0 && !selectedCourseTypeId.value) {
      selectedCourseTypeId.value = collegeCourseTypes.value[0].id
    }
  } catch (err) {
    console.error('加载学院课程类型失败', err)
  } finally {
    loadingCourseTypes.value = false
  }
}

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
interface TargetClassItem {
  class_id: number
  class_name: string
  max_tasks: number
}

const showSmartSampleDialog = ref(false)
const smartSampling = ref(false)
const smartSampleResult = ref<SmartSampleResult | null>(null)
const smartSampleScopeMode = ref<'all' | 'targeted'>('all')
const targetClasses = ref<TargetClassItem[]>([])
const selectedClassToAdd = ref<string>('')
const targetClassQuota = ref<number>(1)
const smartSampleForm = ref({
  morning_only: false,
  max_tasks_per_class: 1,
  sample_ratio: 0.35,
  exclude_already_generated: true
})

// ---- 批量生成早/晚自习状态 ----
const showSelfStudyDialog = ref(false)
const selfStudySubmitting = ref(false)
const selfStudyClassSearch = ref('')
const selfStudyForm = ref({
  self_study_type: 'morning_study' as 'morning_study' | 'evening_study',
  selected_class_ids: [] as string[],
  start_week: 1,
  end_week: 18,
  weekdays: [1, 2, 3, 4, 5] as number[],
  period_start: 1,
  period_end: 2,
  classroom: '',
  teacher_name: '',
  remark: ''
})

const filteredAdminClassesForSelfStudy = computed(() => {
  const kw = selfStudyClassSearch.value.trim().toLowerCase()
  if (!kw) return adminClasses.value
  return adminClasses.value.filter(c => c.class_name.toLowerCase().includes(kw) || String(c.grade_year || '').includes(kw))
})

let dispatchEpoch = 0
const dispatchContext = () => JSON.stringify([sessionStore.currentUser?.id, sessionStore.workspaceCollegeId,
  sessionStore.currentSemesterId, sessionStore.currentWeekNo, selectedAdminClassId.value,
  executionGroupId.value, dispatchCourseTypeId.value, organizationMode.value])
async function loadData(reset = true) {
  if (reset) { occurrencePage.value = 1; weekTaskPage.value = 1; selectedKeys.value = [] }
  const ticket = ++dispatchEpoch, context = dispatchContext()
  const current = () => ticket === dispatchEpoch && context === dispatchContext()
  const previousRevision = selectionRevision.value
  occurrences.value = []
  weekTasks.value = []
  // Keep totals during page requests; Element Plus clamps a non-first page when total becomes zero.
  if (reset) { occurrenceTotal.value = 0; weekTaskTotal.value = 0 }
  dispatchError.value = ''
  if (reset) { selectionRevision.value = ''; selectionScope.value = {}; smartSampleResult.value = null }
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  try {
    // 1. 加载行政班列表（全校真实行政班）
    if (adminClasses.value.length === 0 && sessionStore.hasPermission('academic.read')) {
      const adminRes = await administrativeClassOptions()
      if (!current()) return
      adminClasses.value = adminRes.items || []
    }

    // 2. 加载本周已有的查课任务（可按选中的行政班联动过滤）
    try {
      const taskRes = sessionStore.hasPermission('inspection.read') ? await listTasks({
        semester_id: sessionStore.currentSemesterId,
        week_no: sessionStore.currentWeekNo,
        administrative_class_id: selectedAdminClassId.value ? selectedAdminClassId.value : undefined,
        page: weekTaskPage.value, page_size: 50
      }) : { items: [], total: 0 }
      if (!current()) return
      weekTasks.value = taskRes.items || []
      weekTaskTotal.value = taskRes.total
    } catch (err: unknown) {
      if (!current()) return
      weekTaskTotal.value = 0
      dispatchError.value = `已有任务加载失败：${err instanceof Error ? err.message : '请稍后重试'}`
    }

    // 3. 查询当周排课课次（支持按行政班精准过滤，或查当周全量课次）
    if (sessionStore.weekDateRange.start && sessionStore.weekDateRange.end && (!organizationMode.value || executionGroupId.value)) {
      try {
        const occRes = await queryCourseOccurrences({
          execution_group_id: organizationMode.value ? executionGroupId.value || undefined : undefined,
          course_type_id: dispatchCourseTypeId.value || undefined,
          semester_id: sessionStore.currentSemesterId,
          date_from: sessionStore.weekDateRange.start,
          date_to: sessionStore.weekDateRange.end,
          administrative_class_id: selectedAdminClassId.value || undefined,
          page: occurrencePage.value, page_size: 50
        })
        if (!current()) return
        occurrences.value = occRes.items || []
        occurrenceTotal.value = occRes.total
        if (!reset && previousRevision && previousRevision !== occRes.selection_revision) {
          selectedKeys.value = []; ElMessage.warning('课表或名单已变化，请重新选择课次')
        }
        selectionRevision.value = occRes.selection_revision
        selectionScope.value = occRes.selection_scope || {}
      } catch (err: unknown) {
        if (!current()) return
        occurrenceTotal.value = 0
        dispatchError.value = [dispatchError.value, `排课课次加载失败：${err instanceof Error ? err.message : '请稍后重试'}`].filter(Boolean).join('；')
        occurrences.value = []
      }
    } else {
      occurrences.value = []
      occurrenceTotal.value = 0
    }
  } catch (err: unknown) {
    if (current()) dispatchError.value = `查课安排加载失败：${err instanceof Error ? err.message : '请稍后重试'}`
  } finally {
    if (current()) loading.value = false
  }
}

async function loadMasterTimetableData(reset = true) {
  if (reset) masterPage.value = 1
  if (!sessionStore.currentSemesterId) return
  if (masterWeekNo.value === '' && sessionStore.currentWeekNo) {
    masterWeekNo.value = sessionStore.currentWeekNo
  }
  masterLoading.value = true
  try {
    if (!adminClasses.value.length && sessionStore.hasPermission('academic.read')) {
      const result = await administrativeClassOptions()
      adminClasses.value = result.items || []
    }
    const res = await getMasterTimetable({
      page: masterPage.value, page_size: 50,
      semester_id: sessionStore.currentSemesterId,
      weekday: masterWeekday.value ? Number(masterWeekday.value) : undefined,
      week_no: masterWeekNo.value ? Number(masterWeekNo.value) : undefined,
      administrative_class_id: masterAdminClassId.value ? Number(masterAdminClassId.value) : undefined,
      keyword: masterKeyword.value.trim() || undefined
    })
    masterTimetableList.value = res.items || []
    masterTotal.value = res.total
  } catch (err: unknown) {
    console.error('加载总课表失败:', err)
    ElMessage.error('加载总课表库失败')
  } finally {
    masterLoading.value = false
  }
}

const exportingMaster = ref(false)

async function handleExportMasterTimetable() {
  if (!sessionStore.currentSemesterId) {
    ElMessage.warning('未选择学期，无法导出课表')
    return
  }
  exportingMaster.value = true
  try {
    const blob = await exportCourseSchedulesExcel(sessionStore.currentSemesterId)
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `学期总课表_${sessionStore.currentSemesterName || '未命名学期'}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success('学期总课表 Excel 导出成功！')
  } catch (err: any) {
    ElMessage.error(err?.message || '导出学期课表失败')
  } finally {
    exportingMaster.value = false
  }
}

// ---- 查看教学班学生名单 ----
const showRosterDialog = ref(false)
const rosterLoading = ref(false)
const currentRosterItem = ref<MasterTimetableItem | null>(null)
const rosterStudents = ref<TeachingClassStudentItem[]>([])
const rosterSearch = ref('')

const filteredRosterStudents = computed(() => {
  const q = rosterSearch.value.trim().toLowerCase()
  if (!q) return rosterStudents.value
  return rosterStudents.value.filter(s =>
    (s.name && s.name.toLowerCase().includes(q)) ||
    (s.student_no && s.student_no.toLowerCase().includes(q)) ||
    (s.administrative_class_name && s.administrative_class_name.toLowerCase().includes(q))
  )
})

watch(() => [rosterSearch.value, rosterStudents.value], () => { rosterPage.value = 1 })

async function openTeachingClassRoster(item: MasterTimetableItem) {
  currentRosterItem.value = item
  rosterSearch.value = ''
  rosterStudents.value = []
  showRosterDialog.value = true
  rosterLoading.value = true
  try {
    const cid = sessionStore.workspaceCollegeId || '1'
    const tid = String(item.teaching_class_id)
    const list = await getTeachingClassRoster(cid, tid)
    rosterStudents.value = list || []
  } catch (err: unknown) {
    console.error('加载教学班学生名单失败:', err)
    ElMessage.error(err instanceof Error ? err.message : '加载教学班学生名单失败')
  } finally {
    rosterLoading.value = false
  }
}

watch(
  () => [sessionStore.currentSemesterId, sessionStore.currentWeekNo, selectedAdminClassId.value, executionGroupId.value, dispatchCourseTypeId.value, sessionStore.workspaceCollegeId, organizationMode.value],
  () => {
    if (props.importOnly) return
    if (activeTab.value === 'dispatch') {
      loadData()
    } else {
      loadMasterTimetableData()
    }
  }
)

watch(activeTab, (tab) => {
  if (props.importOnly) return
  if (tab === 'master') {
    masterWeekNo.value = sessionStore.currentWeekNo
    loadMasterTimetableData()
  } else {
    loadData()
  }
})

onMounted(async () => {
  if (props.mode === 'academic') {
    if (!props.importOnly) await loadMasterTimetableData()
    if (props.openImport) openImportDialog()
    if (props.openSelfStudy) openSelfStudyDialog()
  } else await loadData()
})

const selectableOccurrences = computed(() => occurrences.value.filter(o => o.selectable))

/**
 * 课次列表展示计算属性：被选中的课次自动置顶显示，未选中的课次保留在下方。
 * 两组各自保持自然时序（按日期与节次稳定排序）。
 */
const displayOccurrences = computed(() => {
  if (occurrences.value.length === 0) return []
  if (selectedKeys.value.length === 0) return occurrences.value

  const selectedSet = new Set(selectedKeys.value)
  const selectedList: CourseOccurrence[] = []
  const unselectedList: CourseOccurrence[] = []

  for (const item of occurrences.value) {
    const key = `${item.course_schedule_id}_${item.inspection_date}`
    if (selectedSet.has(key)) {
      selectedList.push(item)
    } else {
      unselectedList.push(item)
    }
  }

  return [...selectedList, ...unselectedList]
})

const selectedOccurrencesCount = computed(() => {
  if (occurrences.value.length === 0 || selectedKeys.value.length === 0) return 0
  const selectedSet = new Set(selectedKeys.value)
  return occurrences.value.filter(o => selectedSet.has(`${o.course_schedule_id}_${o.inspection_date}`)).length
})

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
  if (organizationPending.value) { ElMessage.warning('组织排班尚未启用，请先完成成员和规则准备，不能退回全院候选池'); return }
  if (organizationMode.value && !executionGroupId.value) { ElMessage.warning('请选择执行志愿者组'); return }
  if (!selectionRevision.value) { ElMessage.warning('请重新读取课次后下发'); return }
  if (selectedKeys.value.length === 0) {
    ElMessage.warning('请勾选需要下发的课次')
    return
  }

  dispatchLoading.value = true
  try {
    // Stable occurrence keys preserve selections across pages; the server revalidates the full revision.
    const selectedItems = selectedKeys.value.map(key => {
      const [course_schedule_id, inspection_date] = key.split('_')
      return { course_schedule_id: course_schedule_id!, inspection_date: inspection_date! }
    })

    const genRes = await generateExactTasks({
      execution_group_id: executionGroupId.value || undefined,
      semester_id: sessionStore.currentSemesterId,
      inspection_type: 'COURSE',
      selection_revision: selectionRevision.value,
      selection_scope: selectionScope.value,
      occurrences: selectedItems.map(o => ({
        course_schedule_id: o.course_schedule_id,
        inspection_date: o.inspection_date
      }))
    })

    let assignMsg = ''
    if (genRes.assignable_task_ids && genRes.assignable_task_ids.length > 0) {
      try {
        const assignRes = organizationMode.value ? await confirmGroupPlan(sessionStore.workspaceCollegeId, executionGroupId.value, {
          semester_id: sessionStore.currentSemesterId, task_ids: genRes.assignable_task_ids
        }) : await triggerAutoAssign({
          semester_id: sessionStore.currentSemesterId,
          task_ids: genRes.assignable_task_ids
        })
        assignMsg = assignRes ? `<br/>3. <b>已确认排班</b>：分配 ${assignRes.assigned_count} 个，未排 ${assignRes.unassigned_count} 个。` : '<br/>3. 任务已保留，您尚未确认派发。'
      } catch (assignErr: unknown) {
        const errMsg = assignErr && typeof assignErr === 'object' && 'message' in assignErr ? String(assignErr.message) : '自动排班求解未触发'
        assignMsg = `<br/>3. <b>自动排班提示</b>：${errMsg}（可前往任务中心查看或手动指派）。`
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

// ---- 批量生成早/晚自习逻辑 ----
function handleSelfStudyTypeChange() {
  if (selfStudyForm.value.self_study_type === 'morning_study') {
    selfStudyForm.value.period_start = 1
    selfStudyForm.value.period_end = 2
  } else {
    selfStudyForm.value.period_start = 9
    selfStudyForm.value.period_end = 10
  }
}

function openSelfStudyDialog() {
  if (!sessionStore.currentSemesterId) {
    ElMessage.warning('请先在顶部选择学期')
    return
  }
  selfStudyForm.value = {
    self_study_type: 'morning_study',
    selected_class_ids: [],
    start_week: 1,
    end_week: sessionStore.totalWeeks || 18,
    weekdays: [1, 2, 3, 4, 5],
    period_start: 1,
    period_end: 2,
    classroom: '',
    teacher_name: '',
    remark: ''
  }
  selfStudyClassSearch.value = ''
  showSelfStudyDialog.value = true
  if (adminClasses.value.length === 0 && sessionStore.hasPermission('academic.read')) {
    administrativeClassOptions().then(res => {
      adminClasses.value = res.items || []
    })
  }
}

function toggleSelectAllSelfStudyClasses() {
  const visibleIds = filteredAdminClassesForSelfStudy.value.map(c => c.id)
  const allSelected = visibleIds.length > 0 && visibleIds.every(id => selfStudyForm.value.selected_class_ids.includes(id))
  if (allSelected) {
    selfStudyForm.value.selected_class_ids = selfStudyForm.value.selected_class_ids.filter(id => !visibleIds.includes(id))
  } else {
    const set = new Set([...selfStudyForm.value.selected_class_ids, ...visibleIds])
    selfStudyForm.value.selected_class_ids = Array.from(set)
  }
}

function toggleSelfStudyClass(id: string) {
  const idx = selfStudyForm.value.selected_class_ids.indexOf(id)
  if (idx >= 0) {
    selfStudyForm.value.selected_class_ids.splice(idx, 1)
  } else {
    selfStudyForm.value.selected_class_ids.push(id)
  }
}

async function handleBatchSubmitSelfStudy() {
  const cid = sessionStore.workspaceCollegeId || sessionStore.workspaces[0]?.id
  if (!cid) {
    ElMessage.warning('未获取到当前学院标识，请确认当前工作区')
    return
  }
  if (!sessionStore.currentSemesterId) {
    ElMessage.warning('请先选择学期')
    return
  }
  if (selfStudyForm.value.selected_class_ids.length === 0) {
    ElMessage.warning('请至少勾选一个目标行政班')
    return
  }
  if (selfStudyForm.value.weekdays.length === 0) {
    ElMessage.warning('请至少勾选一个上课星期')
    return
  }
  if (selfStudyForm.value.start_week > selfStudyForm.value.end_week) {
    ElMessage.warning('起始周次不能大于结束周次')
    return
  }
  if (selfStudyForm.value.period_start > selfStudyForm.value.period_end) {
    ElMessage.warning('开始节次不能大于结束节次')
    return
  }

  selfStudySubmitting.value = true
  try {
    const weeks = Array.from(
      { length: selfStudyForm.value.end_week - selfStudyForm.value.start_week + 1 },
      (_, i) => selfStudyForm.value.start_week + i
    )
    const res = await batchCreateSelfStudy(cid, {
      study_type: selfStudyForm.value.self_study_type === 'morning_study' ? 'EARLY' : 'LATE',
      semester_id: Number(sessionStore.currentSemesterId),
      class_ids: selfStudyForm.value.selected_class_ids.map(Number),
      weeks,
      weekdays: selfStudyForm.value.weekdays,
      start_period: selfStudyForm.value.period_start,
      end_period: selfStudyForm.value.period_end,
      default_classroom: selfStudyForm.value.classroom.trim() || undefined,
      teacher_name: selfStudyForm.value.teacher_name.trim() || undefined,
      reason: selfStudyForm.value.remark.trim() || undefined
    })

    ElMessageBox.alert(
      `<div>
        <p style="font-weight:700;color:var(--green);margin-bottom:6px;">批量生成排课成功！</p>
        <div style="font-size:var(--text-xs);color:var(--ink-soft);background:var(--green-soft);padding:10px 14px;border-radius:var(--radius);border:1px solid var(--line);border-left:3px solid var(--green);line-height:1.7;">
          <div>覆盖行政班：<strong>${res.classes_count}</strong> 个</div>
          <div>新建教学班：<strong>${res.classes_created}</strong> 个</div>
          <div>生成课次排期：<strong>${res.schedules_created}</strong> 门</div>
          <div>同步关联学生：<strong>${res.students_linked}</strong> 人次</div>
        </div>
        <p style="font-size:var(--text-caption);color:var(--ink-mute);margin-top:8px;">已生成自习课表，可前往教务总课表查看或在此进行课次下发。</p>
      </div>`,
      '批量自习排课完成',
      { dangerouslyUseHTMLString: true, confirmButtonText: '知道了' }
    )
    showSelfStudyDialog.value = false
    if (activeTab.value === 'master') {
      await loadMasterTimetableData()
    } else {
      await loadData()
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '批量生成自习排课失败'
    ElMessage.error(msg)
  } finally {
    selfStudySubmitting.value = false
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
  loadCollegeCourseTypes()
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
      semester_id: sessionStore.currentSemesterId,
      course_type_id: selectedCourseTypeId.value || undefined
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
      `本次文件导入成功！<br/><br/>
      <b>数据概要：</b><br/>
      <pre style="background:var(--paper-deep);border:1px solid var(--line);border-radius:var(--radius);padding:8px 10px;font-size:var(--text-xs);font-family:'JetBrains Mono',monospace;">${JSON.stringify(res.summary, null, 2)}</pre>`,
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
    const res = await uploadBulkImport(
      sessionStore.currentSemesterId,
      bulkFiles.value,
      selectedCourseTypeId.value || undefined
    )
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
    if (activeTab.value === 'master') await loadMasterTimetableData()
    else await loadData()
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

  // 智能上下文联动：若主页面已筛选了某个行政班，且尚未配置指定班级，则自动预置该班并切入指定模式
  if (selectedAdminClassId.value) {
    const currentCls = adminClasses.value.find(c => String(c.id) === String(selectedAdminClassId.value))
    if (currentCls && targetClasses.value.length === 0) {
      targetClasses.value = [{
        class_id: Number(currentCls.id),
        class_name: currentCls.class_name,
        max_tasks: targetClassQuota.value
      }]
      smartSampleScopeMode.value = 'targeted'
    }
  }
}

async function handleAddTargetClass(val: string) {
  if (!val) return
  const found = adminClasses.value.find(c => String(c.id) === String(val))
  if (found) {
    if (!targetClasses.value.some(t => t.class_id === Number(found.id))) {
      targetClasses.value.push({
        class_id: Number(found.id),
        class_name: found.class_name,
        max_tasks: targetClassQuota.value
      })
    }
  }
  await nextTick()
  selectedClassToAdd.value = ''
}

function removeTargetClass(index: number) {
  targetClasses.value.splice(index, 1)
}

function handleTargetQuotaChange(quota: number) {
  for (const c of targetClasses.value) {
    c.max_tasks = quota
  }
}

async function runSmartSample() {
  const originalContext = dispatchContext()
  if (organizationPending.value) { ElMessage.warning('请先完成组织业务启用，再按组抽查'); return }
  if (organizationMode.value && !executionGroupId.value) { ElMessage.warning('请先选择执行组'); return }
  if (!sessionStore.currentSemesterId) return

  if (smartSampleScopeMode.value === 'targeted') {
    if (targetClasses.value.length === 0) {
      ElMessage.warning('请至少添加一个重点抽查班级，或切换为全校班级模式')
      return
    }
  }

  smartSampling.value = true
  try {
    const payload: Parameters<typeof smartSampleOccurrences>[0] = {
      execution_group_id: executionGroupId.value || undefined,
      course_type_id: dispatchCourseTypeId.value || undefined,
      semester_id: Number(sessionStore.currentSemesterId),
      week_no: sessionStore.currentWeekNo,
      morning_only: smartSampleForm.value.morning_only,
      max_tasks_per_class: smartSampleForm.value.max_tasks_per_class,
      exclude_already_generated: smartSampleForm.value.exclude_already_generated
    }

    if (smartSampleScopeMode.value === 'targeted') {
      payload.target_class_ids = targetClasses.value.map(c => c.class_id)
      payload.class_quotas = targetClasses.value.map(c => ({
        class_id: c.class_id,
        class_name: c.class_name,
        max_tasks: targetClassQuota.value
      }))
      payload.max_tasks_per_class = targetClassQuota.value
      // 指定重点班级模式下，不使用全局百分比截断，以严格满足各班设定的节数上限
      payload.sample_ratio = undefined
    } else {
      payload.sample_ratio = smartSampleForm.value.sample_ratio
    }

    const res = await smartSampleOccurrences(payload)
    if (originalContext !== dispatchContext()) return
    smartSampleResult.value = res
    if (res.sampled_count === 0) {
      ElMessage.info('未筛选出待查课次（可能已全部下发或无符合条件的早八课）')
    } else {
      const modeDesc = smartSampleScopeMode.value === 'targeted'
        ? `针对 ${targetClasses.value.length} 个重点班级精选 ${res.sampled_count} 门重点课次`
        : `共精选 ${res.sampled_count} 门重点查课课次`
      ElMessage.success(`智能推荐算法已就绪！${modeDesc}`)
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

  if (smartSampleScopeMode.value === 'targeted') {
    // 定向班级抽查：仅勾选推荐的目标班级课程
    selectedKeys.value = newKeys
    showSmartSampleDialog.value = false
    const targetNames = targetClasses.value.map(c => c.class_name).join('、')
    ElMessage.success(`已为您勾选重点班级【${targetNames}】推荐的 ${newKeys.length} 门课次！`)
  } else {
    const keySet = new Set([...selectedKeys.value, ...newKeys])
    selectedKeys.value = Array.from(keySet)
    showSmartSampleDialog.value = false
    ElMessage.success(`已为您自动勾选推荐的 ${newKeys.length} 门课次！您可以直接核对并点击【确认下发并排班】`)
  }
}
</script>

<template>
  <div class="teaching-schedule-container">
    <template v-if="!props.importOnly">
    <el-alert v-if="props.openImport" title="整包按文件依次处理：成功文件会保存，失败文件可修正后重试。需要先核对时，请选择单文件分步导入。" type="info" :closable="false" />
    <header class="page-head">
      <div class="head-row inspection-head-row">
        <div class="head-title">
          <h2>{{ props.mode === 'academic' ? '正式课表与资料导入' : '具体课次选择与下发' }}</h2>
          <p v-if="props.mode === 'academic'" class="sub">查看本院正式课表，按现有导入流程核对资料。导入不会自动发布给学生。</p>
        </div>

        <DispatchFilters
          v-if="activeTab === 'dispatch' && props.mode === 'inspection'"
          v-model:course-type-id="dispatchCourseTypeId" v-model:group-id="executionGroupId"
          :types="dispatchCourseTypes" :groups="executionGroups" :organization-mode="organizationMode" :error="dispatchOptionsError"
          compact
        />

        <div class="head-actions flex items-center gap-2">
          <button v-if="props.mode !== 'inspection' && (sessionStore.hasPermission('import.execute') || sessionStore.hasPermission('course_schedule.import'))" class="btn btn-outline" @click="openImportDialog">
            <AppIcon name="upload" :size="14" />
            <span>批量导入教务数据</span>
          </button>
          <button
            v-if="props.mode !== 'inspection' && (sessionStore.hasPermission('course_schedule.manage') || sessionStore.hasPermission('academic.manage'))"
            class="btn btn-outline"
            @click="openSelfStudyDialog"
          >
            <AppIcon name="calendar" :size="14" />
            <span>批量生成自习排课</span>
          </button>
          <button
            v-if="activeTab === 'dispatch'"
            class="btn btn-outline"
            @click="openSmartSampleDialog"
          >
            <AppIcon name="sparkles" :size="14" />
            <span class="btn-text-full">智能抽查推荐</span>
            <span class="btn-text-short">智能抽查</span>
          </button>
          <button
            v-if="activeTab === 'dispatch'"
            class="btn btn-dark"
            :disabled="dispatchLoading || selectedKeys.length === 0 || organizationPending || !!dispatchOptionsError || (organizationMode && !executionGroupId)"
            @click="triggerDispatch"
          >
            <AppIcon name="send" :size="14" />
            <span class="btn-text-full">{{ dispatchLoading ? '正在下发…' : `确认下发并排班 (${selectedKeys.length})` }}</span>
            <span class="btn-text-short">{{ dispatchLoading ? '下发中…' : `下发排班 (${selectedKeys.length})` }}</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Tab 切换 -->
    <div v-if="props.mode === 'legacy'" class="tab-nav">
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
        <span>教务总课表</span>
      </button>
    </div>

    <DispatchFilters v-if="activeTab === 'dispatch' && props.mode === 'legacy'"
      v-model:course-type-id="dispatchCourseTypeId" v-model:group-id="executionGroupId"
      :types="dispatchCourseTypes" :groups="executionGroups" :organization-mode="organizationMode" :error="dispatchOptionsError" />
    <!-- TAB 1: 课次勾选与下发 -->
    <div v-if="activeTab === 'dispatch'" v-loading="loading" class="tbl-wrap">
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
            当周待下发课次（共 {{ occurrenceTotal }} 节<template v-if="selectedOccurrencesCount > 0">，已勾选 {{ selectedOccurrencesCount }} 节已置顶</template>）
          </div>
          <div class="table-actions flex items-center gap-2 pr-6 py-2">
            <button
              v-if="selectableOccurrences.length > 0"
              type="button"
              class="btn btn-outline btn-xs"
              @click="toggleSelectAll"
            >
              {{ isAllSelected ? '取消全选' : '全选本页可下发' }}
            </button>
            <button
              v-if="selectedKeys.length > 0"
              type="button"
              class="btn btn-outline btn-xs"
              @click="selectedKeys = []"
            >
              清空选择
            </button>
          </div>
        </div>
        <table class="tbl">
          <thead>
            <tr>
              <th class="th-check">
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
            <template
              v-for="(item, idx) in displayOccurrences"
              :key="`${item.course_schedule_id}_${item.inspection_date}`"
            >
              <!-- 当有选中项且未全选时，在置顶列表与剩余课次间呈现清晰的分割提示条 -->
              <tr
                v-if="selectedOccurrencesCount > 0 && idx === selectedOccurrencesCount && selectedOccurrencesCount < occurrences.length"
                :key="`divider_${selectedOccurrencesCount}`"
                class="pinned-divider-row"
              >
                <td colspan="7" class="pinned-divider-cell">
                  <div class="divider-note font-mono">
                    <span class="divider-line"></span>
                    <span>⬆ 以上为已选课次（共 {{ selectedOccurrencesCount }} 节已置顶）· ⬇ 以下为未勾选课次</span>
                    <span class="divider-line"></span>
                  </div>
                </td>
              </tr>

              <tr
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
                  <div class="cell-sub text-xs flex items-center gap-1.5 flex-wrap">
                    <span class="font-mono">#{{ item.course_schedule_id }}</span>
                    <span v-if="item.teacher_name" class="chip chip-blue">
                      {{ item.teacher_name }}
                    </span>
                  </div>
                </td>
                <td>
                  <div class="cell-main flex items-center gap-1.5 flex-wrap">
                    <span>{{ item.class_name || item.teaching_class_name || '—' }}</span>
                    <span
                      v-if="(item.class_name || item.teaching_class_name || '').includes('合班') || (item.class_name || item.teaching_class_name || '').includes('+')"
                      class="chip chip-blue"
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
                  <span v-else-if="isSelected(item)" class="tag tag-blue font-semibold">已选置顶</span>
                  <span v-else class="tag tag-gray">待下发</span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <el-alert v-if="dispatchError" type="error" :closable="false" show-icon>
        <template #title>{{ dispatchError }}</template>
        <el-button :disabled="loading" @click="loadData(false)">重新加载</el-button>
      </el-alert>
      <AppPagination v-if="!dispatchError || occurrences.length" v-model:current-page="occurrencePage" :total="occurrenceTotal" @current-change="loadData(false)" />
      <p v-if="selectedKeys.length" class="sub">已跨页勾选 {{ selectedKeys.length }} 节；切换页码保留勾选，修改筛选条件会清空。</p>

      <!-- 本周已生成的任务清单 -->
      <div v-if="weekTasks.length > 0" class="week-tasks">
        <div class="section-title">本周数据库中已有查课任务（共 {{ weekTaskTotal }} 条）</div>
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
        <AppPagination v-model:current-page="weekTaskPage" :total="weekTaskTotal" @current-change="loadData(false)" />
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && !dispatchError && !hasData" class="empty-box empty-state">
        <AppIcon name="folder-open" :size="32" class="e-icon" />
        <div class="e-main">当前周次（第 {{ sessionStore.currentWeekNo }} 周）暂无可下发课次及已有任务</div>
        <div class="e-sub">您可以点击右上角“批量导入教务数据”录入班级花名册与课表</div>
      </div>
    </div>

    <!-- TAB 2: 全校教务总课表库 -->
    <div v-if="activeTab === 'master'" class="tbl-wrap">
      <!-- 搜索过滤条 -->
      <div class="filter-bar">
        <div class="fgroup">
          <label>教学周</label>
          <select v-model="masterWeekNo" class="input" @change="loadMasterTimetableData()">
            <option :value="''">全部周次</option>
            <option v-for="w in sessionStore.totalWeeks" :key="w" :value="w">第 {{ w }} 周</option>
          </select>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>星期</label>
          <select v-model="masterWeekday" class="input" @change="loadMasterTimetableData()">
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
          <select v-model="masterAdminClassId" class="input" @change="loadMasterTimetableData()">
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
            @keyup.enter="loadMasterTimetableData()"
          />
          <button class="btn btn-dark btn-sm" @click="loadMasterTimetableData()">查询</button>
        </div>
      </div>

      <!-- 课表结果区 -->
      <div v-loading="masterLoading" class="min-h-[160px]">
        <!-- 总课表列表 -->
        <div v-if="masterTimetableList.length > 0">
          <div class="section-title flex justify-between items-center py-1">
            <div class="flex items-center gap-3">
              <span>当前范围教务课表检索结果（共 {{ masterTotal }} 门排课）</span>
              <span class="dim-note">
                其中查课覆盖课次：{{ masterTimetableList.filter(m => m.is_inspectable).length }} 门
              </span>
            </div>
            <button
              type="button"
              class="btn btn-outline btn-xs flex items-center gap-1.5"
              :disabled="exportingMaster"
              @click="handleExportMasterTimetable"
            >
              <AppIcon name="download" :size="13" />
              <span>{{ exportingMaster ? '正在导出…' : '导出学期总课表 Excel' }}</span>
            </button>
          </div>
          <table class="tbl">
            <thead>
              <tr>
                <th>时间</th>
                <th>课程信息</th>
                <th>教学班</th>
                <th>上课地点</th>
                <th>生效周次</th>
                <th>人员与考勤追踪</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in visibleMasterRows" :key="item.id">
                <td>
                  <div class="font-bold">周{{ item.weekday }}</div>
                  <div class="cell-sub font-mono">{{ formatPeriodText(item.start_period, item.end_period) }}</div>
                </td>
                <td>
                  <div class="cell-main font-bold">{{ item.course_name }}</div>
                  <div class="cell-sub font-mono text-xs">代码: {{ item.course_code }}</div>
                  <div
                    v-if="item.teacher_name"
                    class="chip chip-blue chip-mt"
                    :title="item.head_teacher && (item.teacher_name === item.head_teacher) ? '优先采用班主任兜底呈现' : (item.head_teacher ? `班主任: ${item.head_teacher}` : undefined)"
                  >
                    <AppIcon name="user" :size="11" />
                    <span>教师: {{ item.teacher_name }}</span>
                  </div>
                </td>
                <td>
                  <div class="cell-main flex items-center gap-1.5 flex-wrap">
                    <span>{{ item.teaching_class_name }}</span>
                    <span
                      v-if="item.teaching_class_name && (item.teaching_class_name.includes('合班') || item.teaching_class_name.includes('+'))"
                      class="chip chip-blue"
                      title="合班课程"
                    >
                      合班
                    </span>
                  </div>
                  <div v-if="item.administrative_classes && item.administrative_classes.length > 0" class="cell-sub text-xs mt-1">
                    行政班: {{ item.administrative_classes.join(', ') }}
                  </div>
                </td>
                <td>
                  <span class="cell-main">{{ item.classroom || '未排教室' }}</span>
                </td>
                <td class="font-mono text-xs">
                  <span class="chip chip-gray">
                    {{ item.weeks.length > 8 ? `${item.weeks[0]}-${item.weeks[item.weeks.length - 1]}周 (共${item.weeks.length}周)` : item.weeks.join(',') + '周' }}
                  </span>
                </td>
                <td>
                  <div v-if="item.is_physical_education" class="chip chip-gray">
                    <AppIcon name="ban" :size="12" />
                    <span>体育课 · 免查</span>
                  </div>
                  <div
                    v-else-if="item.enrolled_student_count > 0"
                    class="chip chip-green cursor-pointer hover:opacity-80 transition-opacity"
                    title="点击查看教学班学生名单"
                    @click="openTeachingClassRoster(item)"
                  >
                    <AppIcon name="users" :size="12" />
                    <span>需查课 · 名单 {{ item.enrolled_student_count }} 人</span>
                  </div>
                  <div
                    v-else
                    class="chip chip-amber cursor-pointer hover:opacity-80 transition-opacity"
                    title="点击排查/查看教学班学生名单"
                    @click="openTeachingClassRoster(item)"
                  >
                    <AppIcon name="alert" :size="12" />
                    <span>暂无学生名单</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <AppPagination v-model:current-page="masterPage" :total="masterTotal" @current-change="loadMasterTimetableData(false)" />
        </div>

        <div v-if="!masterLoading && masterTimetableList.length === 0" class="empty-box empty-state">
          <AppIcon name="book" :size="32" class="e-icon" />
          <div class="e-main">未检索到符合条件的排课记录</div>
          <div class="e-sub">请检查筛选条件，或使用上方“批量导入教务数据”导入网格课表</div>
        </div>
      </div>
    </div>
    </template>

    <div v-else class="import-only-panel">
      <h2 class="import-only-title">资料导入</h2>
      <p class="import-only-desc">
        当前学院使用批量导入流程：整包按文件依次处理，成功文件会保存，失败文件可修正后重试。
        需要先核对时，在导入窗口中选择“单文件分步导入”。
      </p>
      <div class="import-only-actions">
        <button
          v-if="sessionStore.hasPermission('import.execute') || sessionStore.hasPermission('course_schedule.import')"
          class="btn btn-dark btn-sm"
          @click="openImportDialog"
        >
          打开批量导入
        </button>
        <button
          v-if="sessionStore.hasPermission('course_schedule.manage') || sessionStore.hasPermission('academic.manage')"
          class="btn btn-outline btn-sm"
          @click="openSelfStudyDialog"
        >
          批量生成自习排课
        </button>
      </div>
    </div>

    <!-- 弹窗: 查看教学班学生名单 -->
    <el-dialog
      v-model="showRosterDialog"
      :title="`教学班学生名单 · ${currentRosterItem?.course_name || ''}`"
      width="min(820px, 94vw)"
      :append-to-body="true"
      class="roster-dialog"
    >
      <div v-if="currentRosterItem" class="roster-dialog-content">
        <!-- 头部概览信息 -->
        <div class="roster-meta-grid mb-4 p-3 bg-deep border border-[var(--line)] rounded-lg text-sm grid grid-cols-2 gap-2">
          <div><span class="t-mute">教学班：</span><span class="font-medium t-ink">{{ currentRosterItem.teaching_class_name }}</span></div>
          <div><span class="t-mute">任课教师：</span><span class="font-medium t-ink">{{ currentRosterItem.teacher_name || '未指定' }}</span></div>
          <div><span class="t-mute">关联行政班：</span><span class="t-soft">{{ currentRosterItem.administrative_classes?.join(', ') || '未关联' }}</span></div>
          <div><span class="t-mute">当前名单：</span><span class="font-semibold t-green">{{ rosterStudents.length }} 人</span></div>
        </div>

        <!-- 搜索过滤 -->
        <div class="flex items-center justify-between mb-3 gap-2">
          <div class="text-xs t-mute">
            共找到 {{ filteredRosterStudents.length }} 名学生
          </div>
          <el-input
            v-model="rosterSearch"
            placeholder="搜索姓名、学号或行政班..."
            clearable
            size="small"
            style="width: 240px;"
          />
        </div>

        <!-- 名单表格 -->
        <div v-loading="rosterLoading" style="min-height: 180px; max-height: 400px; overflow-y: auto;">
          <table v-if="filteredRosterStudents.length > 0" class="w-full text-left border-collapse text-sm">
            <thead>
              <tr class="border-b border-[var(--line-strong)] bg-deep text-xs t-soft font-medium">
                <th class="py-2 px-3 w-12 text-center">#</th>
                <th class="py-2 px-3">学号</th>
                <th class="py-2 px-3">姓名</th>
                <th class="py-2 px-3">行政班级</th>
                <th class="py-2 px-3 w-20 text-center">状态</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--line)]">
              <tr v-for="(stu, idx) in visibleRosterRows" :key="stu.id" class="hover:bg-[var(--paper-deep)]">
                <td class="py-2 px-3 text-center text-xs t-mute font-mono">{{ idx + 1 }}</td>
                <td class="py-2 px-3 font-mono text-xs t-soft">{{ stu.student_no }}</td>
                <td class="py-2 px-3 font-medium t-ink">{{ stu.name }}</td>
                <td class="py-2 px-3 text-xs t-soft">{{ stu.administrative_class_name || currentRosterItem.administrative_classes?.[0] || '-' }}</td>
                <td class="py-2 px-3 text-center">
                  <span class="tag tag-green">在籍</span>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-else-if="!rosterLoading" class="empty-state">
            <AppIcon name="users" :size="32" class="e-icon" />
            <p v-if="rosterSearch" class="e-main">未找到符合搜索条件的学生</p>
            <p v-else class="e-main">该教学班尚未关联在籍学生名单</p>
          </div>
          <AppPagination v-if="filteredRosterStudents.length" v-model:current-page="rosterPage" :total="filteredRosterStudents.length" />
        </div>
      </div>
      <template #footer>
        <button type="button" class="btn btn-secondary" @click="showRosterDialog = false">关闭</button>
      </template>
    </el-dialog>

    <!-- 弹窗: 导入教务数据 -->
    <el-dialog
      v-model="showImportDialog"
      title="导入教务数据"
      width="min(820px, 94vw)"
      :close-on-click-modal="false"
      :append-to-body="true"
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
          <span class="mode-desc">ZIP 压缩包 / 多文件，按文件依次处理</span>
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

        <!-- 课程类型选择 -->
        <div v-if="!bulkResult" class="step-block" style="margin-bottom: 14px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div class="step-label font-mono">课程类型（课表自动分类）</div>
            <span v-if="loadingCourseTypes" style="font-size:var(--text-xs); color:var(--ink-mute);">加载学院配置中…</span>
          </div>
          <select v-model="selectedCourseTypeId" class="input dlg-select" style="margin-top:6px;">
            <option v-for="t in collegeCourseTypes" :key="t.id" :value="t.id">
              {{ t.name }} {{ (t.code === 'builtin_regular' || t.name === '普通课') ? '（默认）' : '' }}
            </option>
          </select>
          <div class="dz-sub" style="margin-top:4px;">压缩包内的课表将按所选类型建立教学班，默认全部建立为普通课。</div>
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
            accept=".zip,.xlsx,.xls,.csv"
            multiple
            class="hidden"
            @change="handleBulkFileSelect"
          />
          <div class="dz-icon"><AppIcon name="cloud-upload" :size="22" /></div>
          <div class="dz-title">点击选择文件，或将文件拖拽至此处</div>
          <div class="dz-sub">支持整包 .zip 压缩包（内含花名册、责任区名单及课表），或按住 Ctrl 多选 .xlsx / .xls / .csv 表格</div>
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
          <span>{{ bulkUploading ? '正在解析并依次导入，请稍候…' : `开始解析并导入所选文件（${bulkFiles.length}）` }}</span>
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
            <option value="admin_roster">责任区班主任辅导员名单 / 行政班花名册（.xlsx / .xls / .csv）</option>
            <option value="grid_timetable">学校网格课表（.xls / .xlsx）— 提取排课并关联行政班名单</option>
            <option value="timetable">平台标准教务排课长表（.xlsx / .xls / .csv）</option>
          </select>
        </div>

        <div v-if="importTarget !== 'admin_roster' && !importPreview" class="step-block">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div class="step-label font-mono">STEP 1.5 · 课程类型</div>
            <span v-if="loadingCourseTypes" style="font-size:var(--text-xs); color:var(--ink-mute);">加载学院配置中…</span>
          </div>
          <select v-model="selectedCourseTypeId" class="input dlg-select" style="margin-top:6px;">
            <option v-for="t in collegeCourseTypes" :key="t.id" :value="t.id">
              {{ t.name }} {{ (t.code === 'builtin_regular' || t.name === '普通课') ? '（默认）' : '' }}
            </option>
          </select>
          <div class="dz-sub" style="margin-top:4px;">导入该课表所生成的教学班将归入该课程类型（默认全部为普通课）。</div>
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
              accept=".xlsx,.xls,.csv"
              class="hidden"
              @change="handleFileSelect"
            />
            <div class="dz-icon"><AppIcon name="file-text" :size="20" /></div>
            <div class="dz-title">{{ importFile ? importFile.name : '点击选择表格文件（.xlsx / .xls / .csv），或拖拽至此' }}</div>
            <div class="dz-sub">支持 .xlsx / .xls / .csv 格式花名册、责任区名单或课表</div>
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
                <span>{{ importConfirming ? '正在落库…' : '确认本次文件导入' }}</span>
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
      :append-to-body="true"
      class="sample-dialog"
    >
      <!-- 范围模式切换 -->
      <div class="scope-mode-tabs">
        <button
          type="button"
          class="scope-tab"
          :class="{ active: smartSampleScopeMode === 'all' }"
          @click="smartSampleScopeMode = 'all'"
        >
          授权范围班级均衡抽查
        </button>
        <button
          type="button"
          class="scope-tab"
          :class="{ active: smartSampleScopeMode === 'targeted' }"
          @click="smartSampleScopeMode = 'targeted'"
        >
          指定重点班级抽查
        </button>
      </div>

      <!-- 如果是指定重点班级模式 -->
      <div v-if="smartSampleScopeMode === 'targeted'" class="targeted-box-block">
        <!-- 顶部选择控制栏: 行政班级选择框 + 统一抽查上限配置选择框 -->
        <div class="target-controls-row">
          <div class="tc-ctrl-item class-select-wrapper">
            <label class="ctrl-label">重点行政班级</label>
            <el-select
              v-model="selectedClassToAdd"
              placeholder="搜索或选择行政班级加入..."
              filterable
              clearable
              class="w-full"
              @change="handleAddTargetClass"
            >
              <el-option
                v-for="c in adminClasses"
                :key="c.id"
                :label="c.class_name"
                :value="String(c.id)"
                :disabled="targetClasses.some(t => t.class_id === Number(c.id))"
              >
                <div class="flex items-center justify-between w-full">
                  <span>{{ c.class_name }}</span>
                  <span
                    v-if="targetClasses.some(t => t.class_id === Number(c.id))"
                    class="dim-note font-mono"
                  >
                    已添加
                  </span>
                </div>
              </el-option>
            </el-select>
          </div>

          <div class="tc-ctrl-item quota-select-wrapper">
            <label class="ctrl-label">抽查上限</label>
            <el-select
              v-model="targetClassQuota"
              placeholder="每班上限"
              class="w-full"
              @change="handleTargetQuotaChange"
            >
              <el-option :value="1" label="1 节 / 周 (推荐)" />
              <el-option :value="2" label="2 节 / 周" />
              <el-option :value="3" label="3 节 / 周" />
              <el-option :value="4" label="4 节 / 周" />
              <el-option :value="5" label="5 节 / 周" />
            </el-select>
          </div>
        </div>

        <!-- 已选重点班级列表（结构与样式完全对齐推荐查课清单） -->
        <div class="target-list-section">
          <div class="rb-head">
            <div class="rb-title">
              <AppIcon name="usergroup" :size="15" />
              <span>已选重点班级</span>
            </div>
            <div class="rb-head-side">
              <span class="rb-meta font-mono">已选 {{ targetClasses.length }} 个班 · 每班上限 {{ targetClassQuota }} 节</span>
              <button
                v-if="targetClasses.length > 0"
                type="button"
                class="row-action danger"
                title="清空所有已选班级"
                @click="targetClasses = []"
              >
                清空
              </button>
            </div>
          </div>

          <div class="rb-files target-classes-files">
            <div
              v-for="(tc, idx) in targetClasses"
              :key="tc.class_id"
              class="course-row class-item-row"
            >
              <div class="cr-left">
                <span class="cr-course font-mono">{{ tc.class_name }}</span>
                <span class="cr-class">重点抽查班级</span>
              </div>
              <div class="cr-right">
                <span class="font-mono text-xs dim">上限 {{ targetClassQuota }} 节/周</span>
                <button
                  type="button"
                  class="btn-remove-class"
                  title="移除该班级"
                  @click="removeTargetClass(idx)"
                >
                  <AppIcon name="close" :size="12" />
                </button>
              </div>
            </div>
            <div v-if="targetClasses.length === 0" class="more-row roomy font-mono">
              暂未添加重点班级，请在上方选择行政班级加入
            </div>
          </div>
        </div>
      </div>

      <!-- 全校模式抽查参数 -->
      <div v-else class="param-grid">
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

      <button
        class="btn btn-dark dlg-primary"
        :disabled="smartSampling"
        @click="runSmartSample"
      >
        <AppIcon v-if="!smartSampling" name="search" :size="14" />
        <span v-if="smartSampling" class="spin">⟳</span>
        <span>
          {{
            smartSampling
              ? '正在运算推荐课次…'
              : (smartSampleScopeMode === 'targeted'
                  ? `计算重点推荐课次 (${targetClasses.length} 个班级 · 每班上限 ${targetClassQuota} 节)`
                  : '计算智能推荐课次')
          }}
        </span>
      </button>

      <!-- 计算结果预览 -->
      <div v-if="smartSampleResult" class="result-block">
        <div class="rb-head">
          <div class="rb-title">
            <AppIcon name="check-circle" :size="15" />
            <span>推荐查课清单</span>
          </div>
          <div class="rb-head-side">
            <span class="rb-meta font-mono">精选 {{ smartSampleResult.sampled_count }} / 候选 {{ smartSampleResult.total_candidates }} 门</span>
            <button
              type="button"
              class="row-action"
              :disabled="smartSampling"
              title="重新随机生成一套推荐课次"
              @click="runSmartSample"
            >
              <span v-if="smartSampling">⟳ 计算中</span>
              <span v-else>🎲 换一批</span>
            </button>
          </div>
        </div>

        <div v-if="smartSampleResult.items && smartSampleResult.items.length > 0" class="rb-files tall">
          <div v-for="item in smartSampleResult.items.slice(0, 15)" :key="item.course_schedule_id" class="course-row">
            <div class="cr-left">
              <span class="cr-course">{{ item.course_name }}</span>
              <span class="cr-class">{{ item.class_name }}</span>
            </div>
            <div class="cr-right font-mono">
              <span class="cell-main">{{ item.inspection_date }} (周{{ formatWeekday(item.inspection_date) }})</span> · {{ formatPeriodText(item.start_period, item.end_period) }} · {{ item.classroom }}
            </div>
          </div>
          <div v-if="smartSampleResult.items.length > 15" class="more-row font-mono">
            … 另有 {{ smartSampleResult.items.length - 15 }} 门课次未列出
          </div>
        </div>

        <div class="rb-actions">
          <button class="btn btn-sm" @click="showSmartSampleDialog = false">取消</button>
          <button
            type="button"
            class="btn btn-sm"
            :disabled="smartSampling"
            @click="runSmartSample"
          >
            🎲 重新随机（换一批）
          </button>
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

    <!-- 弹窗: 批量生成早/晚自习排课 -->
    <el-dialog
      v-model="showSelfStudyDialog"
      title="批量生成早/晚自习排课"
      width="min(820px, 94vw)"
      :close-on-click-modal="false"
      :append-to-body="true"
      class="self-study-dialog"
    >
      <div class="space-y-4">
        <!-- 业务提示 -->
        <div class="note-box note-blue">
          <div class="font-bold flex items-center gap-1 mb-1">
            <AppIcon name="info" :size="14" />
            <span>自习排课说明</span>
          </div>
          <p>
            系统将针对所选行政班，自动匹配学院已有的“早自习”或“晚自习”课程类型，建立专属教学班，并自动同步该班当前有效在籍学生名单与排课时间安排。无需再制作或上传自习 Excel 表格。
          </p>
        </div>

        <!-- 自习类型选择 -->
        <div class="step-block">
          <label class="form-label upper mb-2">自习类型</label>
          <div class="flex gap-4">
            <label class="radio-card" :class="{ selected: selfStudyForm.self_study_type === 'morning_study' }">
              <input type="radio" v-model="selfStudyForm.self_study_type" value="morning_study" @change="handleSelfStudyTypeChange" />
              <div>
                <div class="rt">早自习 (Morning Study)</div>
                <div class="rs">通常安排在清晨或上午第 1-2 节前/时段</div>
              </div>
            </label>
            <label class="radio-card" :class="{ selected: selfStudyForm.self_study_type === 'evening_study' }">
              <input type="radio" v-model="selfStudyForm.self_study_type" value="evening_study" @change="handleSelfStudyTypeChange" />
              <div>
                <div class="rt">晚自习 (Evening Study)</div>
                <div class="rs">通常安排在晚间第 9-10 节或 10-11 节时段</div>
              </div>
            </label>
          </div>
        </div>

        <!-- 目标行政班选择 -->
        <div class="step-block">
          <div class="flex items-center justify-between mb-2">
            <label class="form-label upper">
              目标行政班级（已选 {{ selfStudyForm.selected_class_ids.length }} / {{ adminClasses.length }} 个）
            </label>
            <div class="flex items-center gap-2">
              <input
                v-model="selfStudyClassSearch"
                type="text"
                placeholder="搜索班级或年级..."
                class="input input-xs"
              />
              <button
                type="button"
                class="link-btn"
                @click="toggleSelectAllSelfStudyClasses"
              >
                {{ filteredAdminClassesForSelfStudy.length > 0 && filteredAdminClassesForSelfStudy.every(c => selfStudyForm.selected_class_ids.includes(c.id)) ? '取消全选' : '全选筛选班级' }}
              </button>
            </div>
          </div>
          <div class="class-grid-box">
            <div
              v-for="c in filteredAdminClassesForSelfStudy"
              :key="c.id"
              class="class-pick-item"
              @click="toggleSelfStudyClass(c.id)"
            >
              <input
                type="checkbox"
                :value="c.id"
                v-model="selfStudyForm.selected_class_ids"
                @click.stop
              />
              <span class="truncate" :title="c.class_name">{{ c.class_name }}</span>
            </div>
            <div v-if="filteredAdminClassesForSelfStudy.length === 0" class="class-pick-empty">
              未找到匹配的行政班
            </div>
          </div>
        </div>

        <!-- 排课周期与时间 -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="form-label mb-1">周次范围 (周)</label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="selfStudyForm.start_week"
                type="number"
                min="1"
                max="30"
                class="input text-center font-mono w-20"
              />
              <span class="dim">至</span>
              <input
                v-model.number="selfStudyForm.end_week"
                type="number"
                min="1"
                max="30"
                class="input text-center font-mono w-20"
              />
              <span class="dim-note font-mono">第 {{ selfStudyForm.start_week }}-{{ selfStudyForm.end_week }} 周</span>
            </div>
          </div>
          <div>
            <label class="form-label mb-1">节次时段 (节)</label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="selfStudyForm.period_start"
                type="number"
                min="1"
                max="20"
                class="input text-center font-mono w-20"
              />
              <span class="dim">至</span>
              <input
                v-model.number="selfStudyForm.period_end"
                type="number"
                min="1"
                max="20"
                class="input text-center font-mono w-20"
              />
              <span class="dim-note font-mono">第 {{ selfStudyForm.period_start }}-{{ selfStudyForm.period_end }} 节</span>
            </div>
          </div>
        </div>

        <!-- 星期选择 -->
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="form-label">上课星期</label>
            <div class="flex gap-2 text-xs">
              <button type="button" class="link-btn" @click="selfStudyForm.weekdays = [1, 2, 3, 4, 5]">周一至周五</button>
              <button type="button" class="link-btn" @click="selfStudyForm.weekdays = [1, 2, 3, 4, 5, 6, 7]">全周</button>
              <button type="button" class="link-btn mute" @click="selfStudyForm.weekdays = []">清空</button>
            </div>
          </div>
          <div class="flex gap-2">
            <label
              v-for="d in [{ k: 1, l: '周一' }, { k: 2, l: '周二' }, { k: 3, l: '周三' }, { k: 4, l: '周四' }, { k: 5, l: '周五' }, { k: 6, l: '周六' }, { k: 7, l: '周日' }]"
              :key="d.k"
              class="day-pick"
              :class="selfStudyForm.weekdays.includes(d.k) ? 'selected' : ''"
            >
              <input type="checkbox" :value="d.k" v-model="selfStudyForm.weekdays" class="hidden" />
              <span>{{ d.l }}</span>
            </label>
          </div>
        </div>

        <!-- 选填信息：地点、值班人、备注 -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="form-label mb-1">上课教室 / 地点 (选填)</label>
            <input
              v-model="selfStudyForm.classroom"
              type="text"
              placeholder="如：各班固定教室 / 综教楼"
              class="input text-xs w-full"
            />
          </div>
          <div>
            <label class="form-label mb-1">负责 / 值班教师 (选填)</label>
            <input
              v-model="selfStudyForm.teacher_name"
              type="text"
              placeholder="如：辅导员 / 班主任姓名"
              class="input text-xs w-full"
            />
          </div>
        </div>

        <div>
          <label class="form-label mb-1">备注说明 (选填)</label>
          <input
            v-model="selfStudyForm.remark"
            type="text"
            placeholder="如：2026秋季学期大一晚自习统一排课"
            class="input text-xs w-full"
          />
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-2 pt-2">
          <button class="btn btn-sm" @click="showSelfStudyDialog = false">取消</button>
          <button
            class="btn btn-dark btn-sm"
            :disabled="selfStudySubmitting || selfStudyForm.selected_class_ids.length === 0"
            @click="handleBatchSubmitSelfStudy"
          >
            <span v-if="selfStudySubmitting" class="spin">⟳</span>
            <span>{{ selfStudySubmitting ? '正在批量生成…' : `确认批量生成 (${selfStudyForm.selected_class_ids.length} 班级)` }}</span>
          </button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.import-only-panel {
  max-width: 620px;
  margin: 32px auto;
  padding: 32px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  text-align: center;
}
.import-only-title {
  font-family: 'Noto Serif SC', serif;
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 8px;
}
.import-only-desc {
  color: var(--ink-soft);
  font-size: var(--text-sm);
  line-height: 1.8;
  margin-bottom: 20px;
}
.import-only-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
}
.sel-info { font-size: var(--text-sm); color: var(--ink-mute); }
.sel-info strong { color: var(--ink); font-size: var(--text-lg); }

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
  transition: color var(--dur-f) var(--ease), border-color var(--dur-f) var(--ease);
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
  transition: background-color var(--dur-f) var(--ease);
}

.selectable-row:hover:not(.row-disabled) {
  background-color: var(--paper-deep);
}

.selectable-row.row-selected {
  background-color: var(--blue-soft) !important;
}

.selectable-row.row-selected:hover {
  background-color: color-mix(in srgb, var(--blue) 18%, var(--paper)) !important;
}

.pinned-divider-row td {
  background: var(--paper-deep) !important;
  padding: 4px 16px !important;
  border-top: 1px dashed var(--line-strong);
  border-bottom: 1px dashed var(--line-strong);
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
  border-radius: var(--radius-md);
  accent-color: var(--ink);
  cursor: pointer;
  transition: transform var(--dur-f) var(--ease);
}

.checkbox-lg:hover:not(:disabled) {
  transform: scale(1.15);
}

.checkbox-lg:disabled {
  cursor: not-allowed;
}

.empty-box {
  padding: 60px 20px;
}

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
  transition: background var(--dur-f) var(--ease);
}
.mode-tab:hover { background: var(--paper); }
.mode-tab.active { background: var(--paper); box-shadow: inset 0 2px 0 var(--ink); }
.mode-no {
  font-size: var(--text-caption);
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
  transition: border-color var(--dur-m) var(--ease), background var(--dur-m) var(--ease);
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
  transition: color var(--dur-f) var(--ease);
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
  border-radius: var(--radius-sm);
  transition: color var(--dur-f) var(--ease), background var(--dur-f) var(--ease);
  flex-shrink: 0;
}
.fp-del:hover { color: var(--accent); background: var(--accent-soft); }

/* ---------- 步骤块（单文件导入） ---------- */
.step-block { margin-bottom: 16px; }
.step-label {
  font-size: var(--text-caption);
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
  font-size: var(--text-caption);
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}
.rb-stat .s-value { font-size: var(--text-2xl); font-weight: 600; line-height: 1; color: var(--ink); }
.rb-stat .s-value em {
  font-style: normal;
  font-size: var(--text-caption);
  font-weight: 400;
  color: var(--ink-mute);
  margin-left: 3px;
}
.rb-stat .s-value.hl-green { color: var(--green); }

.rb-files {
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  margin-bottom: 12px;
}
.rb-files.tall {
  height: 195px;
  max-height: 195px;
}
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
  font-size: var(--text-caption);
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
  transition: background var(--dur-f) var(--ease);
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

/* ---------- 智能抽查：模式切换与指定班级 ---------- */
.scope-mode-tabs {
  display: flex;
  background: var(--paper-deep);
  padding: 3px;
  border-radius: var(--radius);
  gap: 4px;
  margin-bottom: 14px;
}
.scope-tab {
  flex: 1;
  border: none;
  background: transparent;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-soft);
  border-radius: calc(var(--radius) - 2px);
  cursor: pointer;
  transition: background var(--dur-f) var(--ease), color var(--dur-f) var(--ease), box-shadow var(--dur-f) var(--ease);
}
.scope-tab.active {
  background: var(--paper);
  color: var(--ink);
  box-shadow: 0 1px 3px rgba(28, 27, 26, 0.08);
}
/* ---------- 智能抽查：重点行政班级与配额控制 ---------- */
.targeted-box-block {
  margin-bottom: 14px;
}
.target-controls-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}
.tc-ctrl-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tc-ctrl-item.class-select-wrapper {
  flex: 1;
  min-width: 0;
}
.tc-ctrl-item.quota-select-wrapper {
  width: 175px;
  flex-shrink: 0;
}
.ctrl-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-soft);
  letter-spacing: 0.02em;
}

/* 重点班级列表（结构与样式对齐推荐查课清单） */
.target-list-section {
  margin-top: 14px;
}
.rb-files.target-classes-files {
  height: 135px;
  max-height: 135px;
  background: var(--paper);
  margin-bottom: 0;
}
.btn-remove-class {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--ink-mute);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--dur-f) var(--ease), color var(--dur-f) var(--ease);
}
.btn-remove-class:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

:deep(.sample-dialog .el-dialog__body) {
  max-height: 80vh;
  overflow-y: auto;
}

/* ============================================================
   纸面秩序语义化补充（替代 Tailwind 原色工具类）
   ============================================================ */
.th-check { width: 52px; text-align: center; }
.week-tasks { margin-top: 24px; }
.btn-xs { padding: 2px 6px; font-size: 11px; border-radius: var(--radius); }

.dim { color: var(--ink-mute); }
.dim-note { font-size: 11px; color: var(--ink-mute); }

/* ---------- 语义徽标 ---------- */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}
.chip-blue { background: var(--blue-soft); color: var(--blue); }
.chip-green { background: var(--green-soft); color: var(--green); }
.chip-amber { background: var(--amber-soft); color: var(--amber); }
.chip-red { background: var(--accent-soft); color: var(--accent); }
.chip-gray { background: var(--paper-deep); color: var(--ink-mute); }
.chip-mt { margin-top: 4px; }

/* ---------- 行内小按钮 ---------- */
.row-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  font-family: inherit;
  color: var(--ink-soft);
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  cursor: pointer;
  transition: background var(--dur-f) var(--ease), border-color var(--dur-f) var(--ease), color var(--dur-f) var(--ease), opacity var(--dur-f) var(--ease);
  white-space: nowrap;
}
.row-action:hover { border-color: var(--ink); color: var(--ink); }
.row-action.danger { color: var(--accent); }
.row-action.danger:hover { border-color: var(--accent); background: var(--accent-soft); }
.row-action:disabled { opacity: 0.5; cursor: not-allowed; }

/* ---------- 提示框 ---------- */
.note-box {
  border: 1px solid var(--line);
  border-left: 3px solid var(--ink-mute);
  background: var(--paper-deep);
  border-radius: var(--radius);
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-soft);
}
.note-box.note-blue { border-left-color: var(--blue); background: var(--blue-soft); }

/* ---------- 分割提示条 ---------- */
.divider-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 11px;
  color: var(--ink-mute);
}
.divider-line { height: 1px; flex: 1; background: var(--line-strong); }

/* ---------- 结果块头部侧栏 / 变体 ---------- */
.rb-head-side { display: flex; align-items: center; gap: 8px; }
.class-item-row .cr-right { display: flex; align-items: center; gap: 10px; }
.more-row.roomy { padding: 28px 12px; }

/* ---------- 表单标签与链接按钮 ---------- */
.form-label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: var(--ink-soft);
}
.form-label.upper {
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 12px;
  font-family: inherit;
  color: var(--blue);
  cursor: pointer;
}
.link-btn:hover { color: var(--ink); text-decoration: underline; }
.link-btn.mute { color: var(--ink-mute); }
.link-btn.mute:hover { color: var(--ink); }

/* ---------- 自习类型单选卡片 ---------- */
.radio-card {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  padding: 12px;
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  cursor: pointer;
  transition: border-color var(--dur-f) var(--ease), box-shadow var(--dur-f) var(--ease);
}
.radio-card:hover { border-color: var(--ink); }
.radio-card.selected { border-color: var(--ink); box-shadow: inset 0 0 0 1px var(--ink); }
.radio-card input { accent-color: var(--ink); }
.radio-card .rt { font-size: 13px; font-weight: 700; color: var(--ink); }
.radio-card .rs { font-size: 11px; color: var(--ink-mute); }

/* ---------- 行政班勾选网格 ---------- */
.input-xs { padding: 4px 8px; font-size: 11px; width: 144px; }
.class-grid-box {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  padding: 8px;
  max-height: 160px;
  overflow-y: auto;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
@media (min-width: 640px) {
  .class-grid-box { grid-template-columns: repeat(3, 1fr); }
}
.class-pick-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: var(--radius);
  transition: background var(--dur-f) var(--ease), border-color var(--dur-f) var(--ease);
}
.class-pick-item:hover { background: var(--paper); border-color: var(--line-strong); }
.class-pick-item input { accent-color: var(--ink); }
.class-pick-empty {
  grid-column: 1 / -1;
  padding: 12px 0;
  text-align: center;
  font-size: 12px;
  color: var(--ink-mute);
}

/* ---------- 星期选择按钮 ---------- */
.day-pick {
  flex: 1;
  padding: 6px 8px;
  text-align: center;
  font-size: 12px;
  color: var(--ink-mute);
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  cursor: pointer;
  user-select: none;
  transition: background var(--dur-f) var(--ease), border-color var(--dur-f) var(--ease), color var(--dur-f) var(--ease);
}
.day-pick:hover { border-color: var(--ink); color: var(--ink); }
.day-pick.selected {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
  font-weight: 700;
}

.inspection-head-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
  width: 100%;
  min-height: 36px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.inspection-head-row::-webkit-scrollbar {
  display: none;
}
.inspection-head-row .head-title {
  flex-shrink: 0;
  white-space: nowrap;
}
.inspection-head-row .head-title h2 {
  font-family: 'Noto Serif SC', serif;
  font-size: var(--text-lg);
  font-weight: 700;
  margin: 0;
  line-height: 32px;
  white-space: nowrap;
}
.inspection-head-row .head-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  margin-left: auto;
}
.inspection-head-row .head-actions .btn {
  height: 32px;
  padding: 0 12px;
  font-size: var(--text-xs);
  line-height: 32px;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.inspection-head-row .btn-text-short {
  display: none;
}
.inspection-head-row .btn-text-full {
  display: inline;
}
@media (max-width: 1100px) {
  .inspection-head-row {
    gap: 8px;
  }
  .inspection-head-row .head-title h2 {
    font-size: var(--text-md);
  }
  .inspection-head-row .btn-text-full {
    display: none;
  }
  .inspection-head-row .btn-text-short {
    display: inline;
  }
  .inspection-head-row .head-actions .btn {
    padding: 0 9px;
    font-size: 12px;
  }
}
</style>
