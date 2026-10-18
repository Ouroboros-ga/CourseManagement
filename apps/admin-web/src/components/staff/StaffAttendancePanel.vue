<script setup lang="ts">
/** 本人工作视图的查课面板：卡片、受限名单明细、更正、认定历史、正式课次日历与课次教室、同范围导出。
 *
 * 只显示服务端逐记录返回的 allowed_actions；按钮存在不代表授权，授权每次请求由服务端重算。
 * 正式课次日历独立于查课卡片：没有被抽到的课同样能定位并改教室。
 */
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  changeOccurrenceLocation,
  correctTeachingAttendance,
  exportRecords,
  getOccurrenceLocation,
  getRecordsSummary,
  listAttendanceRecordVersions,
  listRecordCards,
  listTaskAttendance,
  listTeachingOccurrences,
  type AttendanceVersion,
  type StaffAttendanceCounts,
  type StaffOccurrenceLocation,
  type StaffRecordCard,
  type StaffStudentAttendance,
  type StaffSummary,
  type StaffTeachingOccurrence,
  type StaffView
} from '../../api/staffRecords'
import { useSessionStore } from '../../stores/session'
import { useFileAccess } from '../../composables/useFileAccess'
import { ContextEpoch } from '../../utils/contextEpoch'
import { formatBeijingTime } from '../../utils/datetime'

const props = defineProps<{ view: StaffView }>()
const session = useSessionStore()

const labels: Record<string, string> = { NORMAL: '正常', LEAVE: '请假', LATE: '迟到', ABSENT: '旷课' }
const states: Record<string, string> = {
  RECORDED: '已查课',
  PENDING_SUBMISSION: '待提交',
  PENDING_REVIEW: '待复核',
  CANCELED: '已取消'
}

const cards = shallowRef<StaffRecordCard[]>([])
const total = shallowRef(0)
const page = ref(1)
const summary = shallowRef<StaffSummary | null>(null)
const busy = ref(false)
const exportBusy = ref(false)
const error = ref('')
// 写入失败单独存放：409 之后会立即重取列表与明细，读取路径会清空 error，不能把冲突说明一起擦掉。
const submitError = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const courseName = ref('')

function isoDay(offsetDays: number) {
  const day = new Date()
  day.setDate(day.getDate() + offsetDays)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

const contextKey = computed(() => JSON.stringify([
  session.currentUser?.id || '',
  session.staffContext?.staff_id || '',
  props.view,
  session.currentSemesterId || '',
  String(session.workspace?.authorization_revision || '')
]))
const epoch = new ContextEpoch(() => contextKey.value)
// 课次日历与卡片各自一个 epoch：共用会让后发起的一方把先发起的响应判成过期。
const occurrenceEpoch = new ContextEpoch(() => contextKey.value)

const filters = () => ({
  // 纯教工没有 academic.read，拿不到学期目录；服务端按“关系同时覆盖今日与课次日”
  // 自然只返回当前有效任职的课次，因此学期只在会话确实选中时才作为过滤条件。
  semester_id: session.currentSemesterId || undefined,
  date_from: dateFrom.value || undefined,
  date_to: dateTo.value || undefined,
  course_name: courseName.value.trim() || undefined
})

const selected = ref<StaffRecordCard | null>(null)
const detailOpen = ref(false)
const detailRows = shallowRef<StaffStudentAttendance[]>([])
const detailBusy = ref(false)
const detailPage = ref(1)
const detailTotal = ref(0)
const detailPageSize = 50
const photoOwner = ref<StaffStudentAttendance | null>(null)
const photoContext = computed(() => `${contextKey.value}:${selected.value?.task_id || ''}`)
const photos = useFileAccess(photoContext)

const correctionOpen = ref(false)
const correctionRow = ref<StaffStudentAttendance | null>(null)
const correctionType = ref('NORMAL')
const correctionReason = ref('')
const correctionBusy = ref(false)

const historyOpen = ref(false)
const historyRows = shallowRef<AttendanceVersion[]>([])
const historyBusy = ref(false)
const historyRow = ref<StaffStudentAttendance | null>(null)

const locationOpen = ref(false)
const locationInfo = shallowRef<StaffOccurrenceLocation | null>(null)
const locationInput = ref('')
const locationReason = ref('')
const locationBusy = ref(false)
// 改教室弹窗的两个入口（查课卡片 / 正式课次日历）共用这一份目标，不再依附 selected 卡片。
const locationTarget = ref<{
  classId: string
  key: string
  label: string
  location: string
  from: 'card' | 'calendar'
} | null>(null)

const occurrenceFrom = ref(isoDay(0))
const occurrenceTo = ref(isoDay(6))
const occurrences = shallowRef<StaffTeachingOccurrence[]>([])
const occurrenceTotal = ref(0)
const occurrencePage = ref(1)
const occurrenceBusy = ref(false)
const occurrenceScope = ref('')
const occurrenceError = ref('')
const occurrencePageSize = 20

function countsText(card: StaffRecordCard) {
  if (!card.counts) return '未查课'
  const c = card.counts as StaffAttendanceCounts
  return `应到 ${c.total} · 正常 ${c.NORMAL} · 请假 ${c.LEAVE} · 迟到 ${c.LATE} · 旷课 ${c.ABSENT}`
}

async function load() {
  const ticket = epoch.begin()
  cards.value = []
  summary.value = null
  error.value = ''
  busy.value = true
  try {
    const [list, stats] = await Promise.all([
      listRecordCards(props.view, filters(), page.value, 20),
      getRecordsSummary(props.view, filters())
    ])
    if (!ticket.isCurrent()) return
    cards.value = Array.isArray(list.items) ? list.items : []
    total.value = list.total || 0
    summary.value = stats
  } catch (e) {
    if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '本人查课记录读取失败'
  } finally {
    if (ticket.isLatest()) busy.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function closePanels() {
  detailOpen.value = false
  correctionOpen.value = false
  historyOpen.value = false
  locationOpen.value = false
  selected.value = null
  correctionRow.value = null
  locationInfo.value = null
  locationTarget.value = null
  detailRows.value = []
  detailPage.value = 1
  detailTotal.value = 0
  historyRows.value = []
  historyRow.value = null
  photoOwner.value = null
  submitError.value = ''
}

async function openDetail(card: StaffRecordCard, resetPage = true) {
  selected.value = card
  photoOwner.value = null
  detailOpen.value = true
  if (resetPage) {
    detailPage.value = 1
    detailRows.value = []
    detailTotal.value = 0
  }
  await loadDetail()
}

// 名单按服务端分页取，超过一页的学生必须能继续翻页，否则第 51 位之后既看不到也改不了。
async function loadDetail() {
  const card = selected.value
  if (!card) return
  const captured = contextKey.value
  const taskId = card.task_id
  detailBusy.value = true
  try {
    const result = await listTaskAttendance(taskId, props.view, undefined, detailPage.value, detailPageSize)
    // 只回填“当前选中的那条任务”：先点 A 再点 B 时，A 的慢响应不能填进 B 的标题下。
    if (captured !== contextKey.value || selected.value?.task_id !== taskId) return
    detailRows.value = Array.isArray(result.items) ? result.items : []
    detailTotal.value = result.total || 0
  } catch (e) {
    if (captured === contextKey.value && selected.value?.task_id === taskId) {
      error.value = e instanceof Error ? e.message : '名单明细读取失败'
    }
  } finally {
    if (captured === contextKey.value && selected.value?.task_id === taskId) detailBusy.value = false
  }
}

async function gotoDetailPage(value: number) {
  detailPage.value = value
  await loadDetail()
}

async function showPhotos(row: StaffStudentAttendance) {
  const captured = photoContext.value
  if (!row.photo_file_ids?.length) return
  photoOwner.value = row
  try {
    await Promise.all(row.photo_file_ids.map(id => photos.getUrl(id)))
  } catch (e) {
    if (captured === photoContext.value) {
      error.value = e instanceof Error ? e.message : '现场照片暂不可访问'
      photoOwner.value = null
    }
  }
}

function startCorrection(row: StaffStudentAttendance) {
  correctionRow.value = row
  correctionType.value = row.effective_type
  correctionReason.value = ''
  correctionOpen.value = true
}

const isConflict = (e: unknown) =>
  typeof e === 'object' && e !== null && 'status' in e && (e as { status?: unknown }).status === 409

async function saveCorrection() {
  const row = correctionRow.value
  const card = selected.value
  if (!row || correctionBusy.value) return
  correctionBusy.value = true
  submitError.value = ''
  try {
    await correctTeachingAttendance(row.attendance_record_id, {
      attendance_type: correctionType.value,
      current_version: row.current_version,
      reason: correctionReason.value.trim()
    })
    ElMessage.success('已更正并追加认定版本')
    correctionOpen.value = false
    correctionRow.value = null
    if (card) await openDetail(card)
    void load()
  } catch (e) {
    if (isConflict(e)) {
      submitError.value = '该记录已被他人更正（409）。已按最新认定刷新，请核对后重新提交。'
      // 保持当前页重取：学生可能不在第一页，回到第 1 页会找不到刚核对的那一条。
      if (card) await openDetail(card, false)
      // 表单继续可用但改绑刷新后的行：保留老师刚选的认定和备注，只把提交版本号换成所见的新版本。
      const fresh = detailRows.value.find(item => item.attendance_record_id === row.attendance_record_id)
      if (fresh) correctionRow.value = fresh
      else {
        correctionOpen.value = false
        correctionRow.value = null
        submitError.value = '该记录已被他人更正（409），且已不在当前名单页。请翻页或重新选择该生后再核对。'
      }
      void load()
    } else {
      submitError.value = e instanceof Error ? e.message : '更正失败'
    }
  } finally {
    correctionBusy.value = false
  }
}

async function openHistory(row: StaffStudentAttendance) {
  historyOpen.value = true
  historyRows.value = []
  historyBusy.value = true
  historyRow.value = row
  const captured = contextKey.value
  // ref 会把对象包成响应式代理，因此按键值而不是对象身份判断“还是不是同一条记录”。
  const recordId = row.attendance_record_id
  const stillCurrent = () =>
    captured === contextKey.value && historyRow.value?.attendance_record_id === recordId
  try {
    const rows = await listAttendanceRecordVersions(recordId, props.view)
    if (stillCurrent()) historyRows.value = Array.isArray(rows) ? rows : []
  } catch (e) {
    if (stillCurrent()) error.value = e instanceof Error ? e.message : '认定历史读取失败'
  } finally {
    if (stillCurrent()) historyBusy.value = false
  }
}

function occurrencePeriod(item: StaffTeachingOccurrence) {
  return `第 ${item.start_period}-${item.end_period} 节`
}

async function loadOccurrences() {
  const ticket = occurrenceEpoch.begin()
  occurrenceBusy.value = true
  occurrenceError.value = ''
  try {
    const result = await listTeachingOccurrences(
      occurrenceFrom.value, occurrenceTo.value, occurrencePage.value, occurrencePageSize
    )
    if (!ticket.isCurrent()) return
    occurrences.value = Array.isArray(result.items) ? result.items : []
    occurrenceTotal.value = result.total || 0
    occurrenceScope.value = result.scope_description || ''
  } catch (e) {
    if (ticket.isCurrent()) {
      occurrences.value = []
      occurrenceTotal.value = 0
      occurrenceError.value = e instanceof Error ? e.message : '本人正式课次读取失败'
    }
  } finally {
    if (ticket.isLatest()) occurrenceBusy.value = false
  }
}

function searchOccurrences() {
  occurrencePage.value = 1
  void loadOccurrences()
}

async function gotoOccurrencePage(value: number) {
  occurrencePage.value = value
  await loadOccurrences()
}

async function openLocation(card: StaffRecordCard) {
  if (!card.teaching_class_id) return
  locationTarget.value = {
    classId: card.teaching_class_id,
    key: card.occurrence_key,
    label: `${card.course_name} · ${card.inspection_date} · ${periodText(card)}`,
    location: card.classroom || '',
    from: 'card'
  }
  await openLocationForm()
}

async function openOccurrenceLocation(item: StaffTeachingOccurrence) {
  locationTarget.value = {
    classId: item.teaching_class_id,
    key: item.occurrence_key,
    label: `${item.course_names.join('、')} · ${item.inspection_date} · ${occurrencePeriod(item)}`,
    location: item.current_location || item.base_location || '',
    from: 'calendar'
  }
  await openLocationForm()
}

// 版本号和地点以服务端 GET 为准；输入框保留列表里的初值，不在响应回来后覆盖老师刚输入的内容。
async function openLocationForm() {
  const target = locationTarget.value
  if (!target) return
  locationInfo.value = null
  locationInput.value = target.location
  locationReason.value = ''
  locationOpen.value = true
  const captured = contextKey.value
  const signature = `${target.classId}|${target.key}`
  const stillCurrent = () =>
    captured === contextKey.value &&
    locationTarget.value !== null &&
    `${locationTarget.value.classId}|${locationTarget.value.key}` === signature
  try {
    const info = await getOccurrenceLocation(target.classId, target.key)
    if (stillCurrent()) locationInfo.value = info
  } catch (e) {
    if (stillCurrent()) {
      error.value = e instanceof Error ? e.message : '课次地点读取失败'
      locationOpen.value = false
    }
  }
}

async function saveLocation(restore = false) {
  const target = locationTarget.value
  const info = locationInfo.value
  if (!target || !info || locationBusy.value) return
  const location = restore ? null : locationInput.value.trim()
  if (!restore && !location) {
    submitError.value = '请填写新的教室，或使用“恢复课表原地点”'
    return
  }
  locationBusy.value = true
  submitError.value = ''
  try {
    const next = await changeOccurrenceLocation(target.classId, target.key, {
      location,
      revision: info.revision,
      reason: locationReason.value.trim() || null
    })
    locationInfo.value = next
    ElMessage.success(
      restore
        ? `已恢复课表原地点，${next.affected_task_ids.length} 个未完成任务同步`
        : `已改为 ${next.current_location}，${next.affected_task_ids.length} 个未完成任务同步`
    )
    locationOpen.value = false
    void load()
    if (props.view === 'teaching') void loadOccurrences()
  } catch (e) {
    if (isConflict(e)) {
      submitError.value = '教室版本已变化（409），请刷新后重看本节地点'
      void load()
      if (props.view === 'teaching') void loadOccurrences()
    } else {
      submitError.value = e instanceof Error ? e.message : '教室修改失败'
    }
  } finally {
    locationBusy.value = false
  }
}

async function exportExcel() {
  exportBusy.value = true
  error.value = ''
  try {
    const { blob, filename } = await exportRecords(props.view, filters())
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(link.href)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导出失败'
  } finally {
    exportBusy.value = false
  }
}

watch(contextKey, () => {
  page.value = 1
  occurrencePage.value = 1
  closePanels()
  void load()
  // 日历只服务“我的授课”视图：责任区面板不重复请求，也不显示改教室入口。
  if (props.view === 'teaching') void loadOccurrences()
}, { immediate: true })
watch(page, () => void load())
onUnmounted(() => { epoch.invalidate(); occurrenceEpoch.invalidate() })

function periodText(card: StaffRecordCard) {
  if (card.starts_at || card.ends_at) return `${card.starts_at || ''} - ${card.ends_at || ''}`
  return card.inspection_date
}

function revisionText(card: StaffRecordCard) {
  return card.location_revision ? `已改教室` : '课表地点'
}
</script>

<template>
  <section>
    <div class="filters">
      <el-date-picker v-model="dateFrom" type="date" value-format="YYYY-MM-DD" placeholder="起始日期" style="width: 150px" />
      <el-date-picker v-model="dateTo" type="date" value-format="YYYY-MM-DD" placeholder="截止日期" style="width: 150px" />
      <el-input v-model="courseName" placeholder="课程名称" clearable style="width: 180px" @keyup.enter="search" />
      <el-button @click="search">查询</el-button>
      <el-button :loading="exportBusy" @click="exportExcel">导出 Excel</el-button>
    </div>

    <p class="scope">
      {{ summary?.scope_description || (view === 'teaching' ? '仅统计本人有效授课关系覆盖的课次' : '仅统计本人责任班级在名单快照中的学生') }}
    </p>
    <div v-if="summary" class="metrics">
      <span>查课任务 {{ summary.task_count }}</span>
      <span>已查课 {{ summary.recorded_task_count }}</span>
      <span>未查课 {{ summary.unrecorded_task_count }}（不计入出勤或缺勤）</span>
      <span v-for="college in summary.college_summaries" :key="college.college_id">
        {{ college.college_name }}：{{ college.task_count }} 任务
      </span>
    </div>

    <el-alert v-if="submitError" :title="submitError" type="error" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />

    <el-table :data="cards" v-loading="busy" empty-text="当前视图暂无查课记录">
      <el-table-column prop="course_name" label="课程" min-width="140" />
      <el-table-column label="日期" width="120"><template #default="{ row }">{{ row.inspection_date }}</template></el-table-column>
      <el-table-column label="时段" width="150"><template #default="{ row }">{{ periodText(row) }}</template></el-table-column>
      <el-table-column label="教室" min-width="150">
        <template #default="{ row }">
          {{ row.classroom || '—' }}<span class="tag">{{ revisionText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="负责学院" width="130">
        <template #default="{ row }">{{ row.responsible_college?.name || '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">{{ states[row.attendance_state] || row.attendance_state }}</template>
      </el-table-column>
      <el-table-column label="认定分布" min-width="230"><template #default="{ row }">{{ countsText(row) }}</template></el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <el-button link @click="openDetail(row)">名单与认定</el-button>
          <el-button
            v-if="view === 'teaching' && row.teaching_class_id && row.allowed_actions.includes('view_detail')"
            link
            @click="openLocation(row)"
          >改教室</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      :current-page="page"
      :page-size="20"
      :total="total"
      layout="prev, pager, next"
      background
      @current-change="(value: number) => { page = value }"
    />

    <div v-if="view === 'teaching'" class="occurrences">
      <div class="occ-head">
        <h3>近期正式课次</h3>
        <el-date-picker v-model="occurrenceFrom" type="date" value-format="YYYY-MM-DD" placeholder="起始日期" style="width: 150px" />
        <el-date-picker v-model="occurrenceTo" type="date" value-format="YYYY-MM-DD" placeholder="截止日期" style="width: 150px" />
        <el-button :loading="occurrenceBusy" @click="searchOccurrences">查询课次</el-button>
      </div>
      <p class="hint">
        {{ occurrenceScope || '列出本人课表上的正式课次，与是否被抽到查课无关；未抽查的课也能在这里更换本节教室。' }}
        区间最多 31 天。
      </p>
      <el-alert v-if="occurrenceError" :title="occurrenceError" type="error" :closable="false" />
      <el-table :data="occurrences" v-loading="occurrenceBusy" empty-text="所选区间内暂无本人正式课次">
        <el-table-column label="课程" min-width="140">
          <template #default="{ row }">{{ row.course_names.join('、') }}</template>
        </el-table-column>
        <el-table-column label="教学班" min-width="140">
          <template #default="{ row }">{{ row.class_names.join('、') }}</template>
        </el-table-column>
        <el-table-column prop="inspection_date" label="日期" width="110" />
        <el-table-column label="节次" width="110">
          <template #default="{ row }">{{ occurrencePeriod(row) }}</template>
        </el-table-column>
        <el-table-column label="教室" min-width="150">
          <template #default="{ row }">
            {{ row.current_location || '—' }}<span class="tag">{{ row.overridden ? '已改教室' : '课表地点' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="查课" width="100">
          <template #default="{ row }">{{ row.task_ids.length ? '已安排查课' : '未抽查' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link @click="openOccurrenceLocation(row)">改教室</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="roster-pager">
        <span class="hint">共 {{ occurrenceTotal }} 节。</span>
        <el-pagination
          v-if="occurrenceTotal > occurrencePageSize"
          :current-page="occurrencePage"
          :page-size="occurrencePageSize"
          :total="occurrenceTotal"
          layout="prev, pager, next"
          background
          @current-change="gotoOccurrencePage"
        />
      </div>
    </div>

    <el-dialog v-model="detailOpen" title="名单与当前认定" width="820px">
      <p class="hint">
        {{ selected?.course_name }} · {{ selected?.inspection_date }} ·
        {{ selected?.responsible_college?.name }}
        <template v-if="view === 'responsible'">；只列出本人责任班级的学生，跨学院任务按负责学院分别显示</template>
      </p>
      <el-table :data="detailRows" v-loading="detailBusy" empty-text="本视图暂无可见学生记录">
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column prop="administrative_class_name_snapshot" label="名单快照班级" min-width="140" />
        <el-table-column label="当前认定" width="110">
          <template #default="{ row }">{{ labels[row.effective_type] || row.effective_type }}</template>
        </el-table-column>
        <el-table-column prop="current_version" label="版本" width="70" />
        <el-table-column label="照片" width="80">
          <template #default="{ row }">
            <el-button v-if="row.photo_file_ids?.length" link @click="showPhotos(row)">{{ row.photo_file_ids.length }} 张</el-button>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.allowed_actions.includes('correct')" link @click="startCorrection(row)">更正</el-button>
            <el-button v-if="row.allowed_actions.includes('view_history')" link @click="openHistory(row)">历史</el-button>
            <span v-if="row.restriction_reason" class="tag">{{ row.restriction_reason }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="photoOwner?.photo_file_ids?.length" class="photos">
        <p class="hint">{{ photoOwner.name }} 的现场照片：按逐文件授权短期链接展示，过期后重新点开即可再取，不是永久下载权限。</p>
        <el-image
          v-for="id in photoOwner.photo_file_ids"
          :key="id"
          :src="photos.urls.value[id]"
          :preview-src-list="Object.values(photos.urls.value)"
          fit="contain"
          style="width: 160px; height: 120px"
        />
      </div>
      <div class="roster-pager">
        <span class="hint">共 {{ detailTotal }} 名可见学生，每页 {{ detailPageSize }} 名。</span>
        <el-pagination
          v-if="detailTotal > detailPageSize"
          :current-page="detailPage"
          :page-size="detailPageSize"
          :total="detailTotal"
          layout="prev, pager, next"
          background
          @current-change="gotoDetailPage"
        />
      </div>
    </el-dialog>

    <el-dialog v-model="correctionOpen" title="更正本人授课记录的认定" width="480px">
      <p class="hint">
        {{ selected?.course_name }} · {{ selected?.inspection_date }} · {{ correctionRow?.name }}（{{ correctionRow?.student_no }}）
        <br />
        当前认定 {{ labels[correctionRow?.effective_type || ''] || correctionRow?.effective_type }}
        · 所见版本 v{{ correctionRow?.current_version }}。原提交、照片与既往版本保留，本次追加更正版本。
      </p>
      <el-form label-position="top">
        <el-form-item label="更正为">
          <el-select v-model="correctionType" style="width: 100%">
            <el-option v-for="(label, value) in labels" :key="value" :value="value" :label="label" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注（选填）">
          <el-input v-model="correctionReason" type="textarea" :rows="2" maxlength="512" show-word-limit />
        </el-form-item>
      </el-form>
      <p class="hint">若该生已提异议，更正不等于结案：异议继续待处理，由责任学院重新审核后认定。</p>
      <template #footer>
        <el-button @click="correctionOpen = false">取消</el-button>
        <el-button type="primary" :loading="correctionBusy" @click="saveCorrection">提交更正</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyOpen" title="认定历史" width="640px">
      <p class="hint">
        {{ selected?.course_name }} · {{ selected?.inspection_date }} ·
        {{ historyRow?.name }}（{{ historyRow?.student_no }}）· 当前 v{{ historyRow?.current_version }}
      </p>
      <el-table :data="historyRows" v-loading="historyBusy" empty-text="暂无历史版本">
        <el-table-column prop="version_no" label="版本" width="70" />
        <el-table-column label="认定" width="90">
          <template #default="{ row }">{{ labels[row.attendance_type] || row.attendance_type }}</template>
        </el-table-column>
        <el-table-column prop="source_type" label="来源" width="140" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatBeijingTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="备注" min-width="160" />
      </el-table>
    </el-dialog>

    <el-dialog v-model="locationOpen" title="更换本节教室" width="520px">
      <template v-if="locationInfo">
        <p class="hint">{{ locationTarget?.label }}</p>
        <p class="hint">
          课表原地点 {{ locationInfo.base_location || '—' }} · 当前 {{ locationInfo.current_location || '—' }}
          · 地点版本 v{{ locationInfo.revision }}
        </p>
        <el-alert
          title="只修改选中的这一节真实课次；长期调整请由教务维护正式课表。已完成、已取消或已形成考勤的任务保留现场原地点。"
          type="info"
          :closable="false"
        />
        <el-form label-position="top">
          <el-form-item label="新教室">
            <el-input v-model="locationInput" maxlength="128" placeholder="例如 教305" />
          </el-form-item>
          <el-form-item label="原因（选填）">
            <el-input v-model="locationReason" type="textarea" :rows="2" maxlength="512" show-word-limit />
          </el-form-item>
        </el-form>
        <p v-if="locationInfo.affected_task_ids.length" class="hint">
          受影响未完成任务 {{ locationInfo.affected_task_ids.length }} 个，志愿者下次读取任务即得到新地点。
        </p>
        <p v-else class="hint">本课次暂无未完成查课任务，地点已对本人课表生效；之后生成的任务会带上新地点。</p>
      </template>
      <template #footer>
        <el-button @click="locationOpen = false">取消</el-button>
        <el-button v-if="locationInfo?.overridden" :loading="locationBusy" @click="saveLocation(true)">恢复课表原地点</el-button>
        <el-button type="primary" :loading="locationBusy" @click="saveLocation(false)">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.filters { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.scope { color: var(--ink-mute); font-size: 13px; margin: 0 0 8px; }
.metrics { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; margin-bottom: 12px; color: var(--ink-mute); }
.hint { color: var(--ink-mute); font-size: 12px; line-height: 1.7; }
.tag { color: var(--blue); font-size: 12px; margin-left: 6px; }
.photos { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; font-size: 13px; }
.roster-pager { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.occurrences { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--line, #e5e7eb); }
.occ-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.occ-head h3 { margin: 0; font-size: 15px; }
</style>
