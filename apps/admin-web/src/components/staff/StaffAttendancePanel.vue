<script setup lang="ts">
/** 本人工作视图的查课面板：卡片、受限名单明细、更正、认定历史、课次教室与同范围导出。
 *
 * 只显示服务端逐记录返回的 allowed_actions；按钮存在不代表授权，授权每次请求由服务端重算。
 */
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  changeOccurrenceLocation,
  correctTeachingAttendance,
  exportRecords,
  getOccurrenceLocation,
  getRecordsSummary,
  listRecordCards,
  listTaskAttendance,
  listTeachingAttendanceVersions,
  type AttendanceVersion,
  type StaffAttendanceCounts,
  type StaffOccurrenceLocation,
  type StaffRecordCard,
  type StaffStudentAttendance,
  type StaffSummary,
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

const contextKey = computed(() => JSON.stringify([
  session.currentUser?.id || '',
  session.staffContext?.staff_id || '',
  props.view,
  session.currentSemesterId || '',
  String(session.workspace?.authorization_revision || '')
]))
const epoch = new ContextEpoch(() => contextKey.value)

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

const locationOpen = ref(false)
const locationInfo = shallowRef<StaffOccurrenceLocation | null>(null)
const locationInput = ref('')
const locationReason = ref('')
const locationBusy = ref(false)

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
  detailRows.value = []
  historyRows.value = []
  photoOwner.value = null
  submitError.value = ''
}

async function openDetail(card: StaffRecordCard) {
  selected.value = card
  photoOwner.value = null
  detailOpen.value = true
  detailBusy.value = true
  const captured = contextKey.value
  try {
    const result = await listTaskAttendance(card.task_id, props.view)
    if (captured === contextKey.value) detailRows.value = Array.isArray(result.items) ? result.items : []
  } catch (e) {
    if (captured === contextKey.value) error.value = e instanceof Error ? e.message : '名单明细读取失败'
  } finally {
    if (captured === contextKey.value) detailBusy.value = false
  }
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
      if (card) await openDetail(card)
      // 表单继续可用但改绑刷新后的行：保留老师刚选的认定和备注，只把提交版本号换成所见的新版本。
      const fresh = detailRows.value.find(item => item.attendance_record_id === row.attendance_record_id)
      if (fresh) correctionRow.value = fresh
      else {
        correctionOpen.value = false
        correctionRow.value = null
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
  const captured = contextKey.value
  try {
    const rows = await listTeachingAttendanceVersions(row.attendance_record_id)
    if (captured === contextKey.value) historyRows.value = Array.isArray(rows) ? rows : []
  } catch (e) {
    if (captured === contextKey.value) error.value = e instanceof Error ? e.message : '认定历史读取失败'
  } finally {
    if (captured === contextKey.value) historyBusy.value = false
  }
}

async function openLocation(card: StaffRecordCard) {
  if (!card.teaching_class_id) return
  selected.value = card
  locationInfo.value = null
  locationInput.value = card.classroom || ''
  locationReason.value = ''
  locationOpen.value = true
  const captured = contextKey.value
  try {
    const info = await getOccurrenceLocation(card.teaching_class_id, card.occurrence_key)
    if (captured === contextKey.value) locationInfo.value = info
  } catch (e) {
    if (captured === contextKey.value) {
      error.value = e instanceof Error ? e.message : '课次地点读取失败'
      locationOpen.value = false
    }
  }
}

async function saveLocation(restore = false) {
  const card = selected.value
  const info = locationInfo.value
  if (!card?.teaching_class_id || !info || locationBusy.value) return
  const location = restore ? null : locationInput.value.trim()
  if (!restore && !location) {
    submitError.value = '请填写新的教室，或使用“恢复课表原地点”'
    return
  }
  locationBusy.value = true
  submitError.value = ''
  try {
    const next = await changeOccurrenceLocation(card.teaching_class_id, card.occurrence_key, {
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
  } catch (e) {
    if (isConflict(e)) {
      submitError.value = '教室版本已变化（409），请刷新后重看本节地点'
      void load()
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
  closePanels()
  void load()
}, { immediate: true })
watch(page, () => void load())
onUnmounted(() => { epoch.invalidate() })

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
    </el-dialog>

    <el-dialog v-model="correctionOpen" title="更正本人授课记录的认定" width="480px">
      <p class="hint">
        {{ correctionRow?.name }} · 当前认定 {{ labels[correctionRow?.effective_type || ''] || correctionRow?.effective_type }}
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
        <p class="hint">受影响未完成任务 {{ locationInfo.affected_task_ids.length }} 个，志愿者下次读取任务即得到新地点。</p>
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
</style>
