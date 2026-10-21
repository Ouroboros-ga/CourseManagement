<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { listAttendance, listAttendanceGroups, attendanceLabels, type AttendanceGroup, type AttendanceRecord, type AttendanceCounts, type AttendanceType, type ListAttendanceParams } from '../../api/attendance'
import { listCourseTypes, type CourseType } from '../../api/campus'
import { useWorkspaceContext } from '../../composables/useWorkspaceContext'
import { ContextEpoch } from '../../utils/contextEpoch'
import AppPagination from '../AppPagination.vue'
import AttendanceGroupTable from './AttendanceGroupTable.vue'
import AttendanceRecordTable from './AttendanceRecordTable.vue'
import AttendanceRecordDetail from './AttendanceRecordDetail.vue'
import AttendanceTaskResults from './AttendanceTaskResults.vue'

const { session, key } = useWorkspaceContext()
const view = ref<'task' | 'administrative_class' | 'records'>('task')
const page = ref(1), total = ref(0), busy = ref(false), error = ref('')
const status = ref<AttendanceType | ''>(''), typeId = ref(''), keyword = ref(''), search = ref('')
const dateRange = ref<string[] | null>(null), onlyAbnormal = ref(false)
const types = shallowRef<CourseType[]>([]), groups = shallowRef<AttendanceGroup[]>([]), records = shallowRef<AttendanceRecord[]>([])
const summary = shallowRef<AttendanceCounts | null>(null), classScope = shallowRef<AttendanceGroup | null>(null)
const selectedTask = shallowRef<AttendanceGroup | null>(null), selectedRecord = shallowRef<AttendanceRecord | null>(null)
const groupBy = computed(() => view.value === 'administrative_class' && !classScope.value ? 'administrative_class' : 'task')
const filters = computed<ListAttendanceParams>(() => ({ semester_id: session.currentSemesterId,
  effective_type: status.value || undefined, course_type_id: typeId.value || undefined,
  keyword: search.value || undefined, start_date: dateRange.value?.[0], end_date: dateRange.value?.[1],
  abnormal_only: onlyAbnormal.value || undefined,
  administrative_class_id: classScope.value?.administrative_class_id || undefined,
  unknown_class: classScope.value && !classScope.value.administrative_class_id ? true : undefined }))
const epoch = new ContextEpoch(() => `${key.value}:${view.value}:${page.value}:${JSON.stringify(filters.value)}`)
async function load() {
  const ticket = epoch.begin()
  records.value = []; groups.value = []; error.value = ''; selectedRecord.value = null
  busy.value = false
  if (!session.currentSemesterId) { summary.value = null; total.value = 0; return }
  busy.value = true
  try {
    const query = { ...filters.value, page: page.value, page_size: 50 }
    if (view.value === 'records') {
      const result = await listAttendance(query)
      if (ticket.isCurrent()) { records.value = result.items; total.value = result.total; summary.value = null }
    } else {
      const result = await listAttendanceGroups(groupBy.value, query)
      if (ticket.isCurrent()) { groups.value = result.items; total.value = result.total; summary.value = result.summary }
    }
  } catch (e) { if (ticket.isCurrent()) { error.value = e instanceof Error ? e.message : '考勤读取失败，请重试'; total.value = 0; summary.value = null } }
  finally { if (ticket.isLatest()) busy.value = false }
}
function openGroup(row: AttendanceGroup) {
  if (groupBy.value === 'administrative_class') classScope.value = row
  else selectedTask.value = row
}
function reset() { status.value = ''; typeId.value = ''; keyword.value = ''; search.value = ''; dateRange.value = null; onlyAbnormal.value = false; classScope.value = null }
watch(key, async () => {
  reset(); page.value = 1; total.value = 0; summary.value = null; selectedTask.value = null; selectedRecord.value = null; types.value = []
  const captured = key.value
  if (session.workspaceCollegeId && session.hasPermission('academic.course_type.read')) {
    try { const result = await listCourseTypes(session.workspaceCollegeId); if (captured === key.value) types.value = result }
    catch { /* 考勤读取不依赖类型目录；目录不可用时不替换筛选值。 */ }
  }
}, { immediate: true, flush: 'sync' })
watch(view, () => { classScope.value = null }, { flush: 'sync' })
watch([filters, view], () => { page.value = 1; selectedTask.value = null; selectedRecord.value = null }, { flush: 'sync' })
watch([key, filters, view, page], () => void load(), { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <section class="attendance-browser">
    <div class="attendance-browser__heading"><div><h2>查课结果</h2><p>先看每次查课的整体结果，再查看学生名单和现场照片。</p></div><el-radio-group v-model="view" aria-label="考勤查看方式"><el-radio-button value="task">按课次</el-radio-button><el-radio-button value="administrative_class">按行政班</el-radio-button><el-radio-button value="records">学生明细</el-radio-button></el-radio-group></div>
    <div class="attendance-browser__filters">
      <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" aria-label="查课日期范围" />
      <el-select v-model="status" aria-label="考勤状态" placeholder="全部认定" clearable><el-option v-for="(label, value) in attendanceLabels" :key="value" :value="value" :label="label" /></el-select>
      <el-select v-if="types.length" v-model="typeId" aria-label="课程类型" placeholder="全部课程类型" clearable><el-option v-for="type in types" :key="type.id" :value="type.id" :label="type.name" /></el-select>
      <el-input v-model="keyword" placeholder="姓名 / 学号 / 班级 / 课程" aria-label="搜索考勤结果" clearable @keyup.enter="search = keyword.trim()" @clear="search = ''" />
      <el-button @click="search = keyword.trim()">搜索</el-button><el-button @click="reset">重置</el-button><el-button @click="load">刷新</el-button>
      <el-checkbox v-model="onlyAbnormal">只看异常</el-checkbox>
    </div>
    <div v-if="classScope" class="attendance-browser__breadcrumb"><el-button link @click="classScope = null">全部行政班</el-button><span> / {{ classScope.class_name }} · 各次查课</span></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="summary" class="attendance-browser__summary"><span>符合筛选的考勤记录 <b>{{ summary.record_count }}</b> 条</span><span>{{ summary.task_count }} 次查课</span><span class="normal">正常 {{ summary.normal_count }}</span><span class="late">迟到 {{ summary.late_count }}</span><span class="absent">旷课 {{ summary.absent_count }}</span><span>请假 {{ summary.leave_count }}</span></div>
    <p class="attendance-browser__hint">{{ view === 'administrative_class' ? '班级按查课时名单快照归类；同一学生多次被查会分别计为考勤记录。' : '每个课次对应一项具体查课任务；重复查课与不同负责学院的结果各自保留。' }}</p>
    <AttendanceRecordTable v-if="view === 'records'" :rows="records" :busy="busy" @open="selectedRecord = $event" />
    <AttendanceGroupTable v-else :rows="groups" :group-by="groupBy" :busy="busy" @open="openGroup" />
    <AppPagination v-model:current-page="page" :total="total" />
    <AttendanceRecordDetail :record="selectedRecord" @close="selectedRecord = null" @updated="load" />
    <el-dialog v-if="selectedTask" :model-value="true" :title="selectedTask.course_name || '本次查课结果'" width="min(1120px, 94vw)" top="5vh" @update:model-value="selectedTask = null">
      <AttendanceTaskResults :key="selectedTask.task_id" :task="selectedTask" :filters="filters" @updated="load" />
    </el-dialog>
  </section>
</template>
<style scoped>
.attendance-browser__heading { display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin:12px 0 22px; }
.attendance-browser__heading h2 { margin:0 0 7px; }.attendance-browser__heading p { margin:0;font-size:var(--text-sm);color:var(--ink-mute); }
.attendance-browser__filters { display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:18px; }
.attendance-browser__filters :deep(.el-date-editor) { max-width:280px;flex:none; }.attendance-browser__filters .el-select { width:140px; }.attendance-browser__filters .el-input { width:240px; }.attendance-browser__filters .el-button + .el-button { margin-left:0; }
.attendance-browser__summary { display:flex;align-items:center;flex-wrap:wrap;gap:14px 28px;padding:17px 20px;border:1px solid var(--line);background:white;font-size:var(--text-sm); }.attendance-browser__summary b { font-size:var(--text-2xl);margin:0 5px; }.normal { color:var(--green); }.late { color:var(--amber); }.absent { color:var(--red); }
.attendance-browser__hint { margin:14px 0;color:var(--ink-mute);font-size:var(--text-xs); }.attendance-browser__breadcrumb { display:flex;align-items:center;gap:8px;margin:12px 0; }
</style>
