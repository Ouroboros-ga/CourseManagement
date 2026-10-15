<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { correctArchivedAttendance, listAttendance, type AttendanceRecord, type AttendanceType } from '../../api/attendance'
import { useWorkspaceContext } from '../../composables/useWorkspaceContext'
import { useFileAccess } from '../../composables/useFileAccess'
import { ContextEpoch } from '../../utils/contextEpoch'
const { session, key } = useWorkspaceContext()
const rows = shallowRef<AttendanceRecord[]>([]), total = shallowRef(0), page = shallowRef(1)
const filter = shallowRef<AttendanceType | ''>(''), busy = shallowRef(false), error = shallowRef('')
const selected = shallowRef<AttendanceRecord | null>(null)
let active = true
const correctionType = ref<AttendanceType>('NORMAL'), correctionReason = ref(''), correcting = ref(false)
const canCorrectArchived = computed(() => session.currentSemester?.status === 'ARCHIVED' && session.hasPermission('attendance.correct') && session.hasAnyRole('SUPER_ADMIN', 'TEACHER_ADMIN'))
const photoContext = computed(() => `${key.value}:${selected.value?.id || ''}`)
const photos = useFileAccess(photoContext)
const epoch = new ContextEpoch(() => `${key.value}:${page.value}:${filter.value}`)
const labels: Record<AttendanceType, string> = { NORMAL: '正常', LEAVE: '请假', LATE: '迟到', ABSENT: '旷课' }
async function load() {
  const ticket = epoch.begin()
  rows.value = []; error.value = ''; selected.value = null; busy.value = false
  if (!session.currentSemesterId) return
  busy.value = true
  try {
    const result = await listAttendance({ semester_id: session.currentSemesterId, page: page.value, page_size: 20, effective_type: filter.value || undefined })
    if (ticket.isCurrent()) { rows.value = result.items; total.value = result.total }
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '考勤读取失败' }
  finally { if (ticket.isCurrent()) busy.value = false }
}
async function open(row: AttendanceRecord) {
  selected.value = row
  correctionReason.value = ''; correctionType.value = row.effective_type
  const context = photoContext.value
  try { await Promise.all((row.photo_file_ids || []).map(id => photos.getUrl(id))) }
  catch (e) { if (context === photoContext.value) error.value = e instanceof Error ? e.message : '现场照片暂不可访问' }
}
async function correctArchived() {
  const row = selected.value, cid = session.workspaceCollegeId, captured = key.value
  if (!row || !canCorrectArchived.value || !correctionReason.value.trim() || correcting.value) return
  correcting.value = true; error.value = ''
  try {
    await correctArchivedAttendance(cid, row.id, { attendance_type: correctionType.value, reason: correctionReason.value, current_version: row.current_version })
    if (active && captured === key.value && selected.value?.id === row.id) await load()
  } catch (e) { if (active && captured === key.value) error.value = e instanceof Error ? e.message : '归档更正失败，请刷新记录' }
  finally { if (active && captured === key.value) correcting.value = false }
}
watch([key, filter], () => { page.value = 1; total.value = 0 }, { flush: 'sync' })
watch([key, page, filter], () => { void load() }, { immediate: true })
onUnmounted(() => { active = false; epoch.invalidate() })
</script>
<template>
  <section>
    <div class="filters"><el-select v-model="filter" aria-label="考勤状态" style="width: 160px"><el-option value="" label="全部认定" /><el-option v-for="(label, value) in labels" :key="value" :value="value" :label="label" /></el-select><el-button @click="load">刷新</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="rows" v-loading="busy" empty-text="当前学期和筛选条件下暂无考勤记录">
      <el-table-column prop="student_no" label="学号" /><el-table-column prop="name" label="姓名" />
      <el-table-column label="课程"><template #default="{ row }">{{ row.task?.course_name_snapshot || '—' }}</template></el-table-column>
      <el-table-column label="检查日期"><template #default="{ row }">{{ row.task?.inspection_date || '—' }}</template></el-table-column>
      <el-table-column label="当前认定"><template #default="{ row }">{{ labels[row.effective_type as AttendanceType] }}</template></el-table-column>
      <el-table-column label="详情"><template #default="{ row }"><el-button link @click="open(row)">照片与记录详情</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" />
    <el-dialog :model-value="!!selected" title="本次考勤与现场照片" @close="selected = null">
      <template v-if="selected"><p>{{ selected.name }} · {{ selected.task?.course_name_snapshot }} · {{ labels[selected.effective_type] }}</p>
        <p>考勤 ID：{{ selected.id }} · 当前版本：{{ selected.current_version }}</p>
        <p>任务负责学院：{{ selected.task?.responsible_college_name || session.workspace?.name || '历史归属待核对' }}</p>
        <el-image v-for="id in selected.photo_file_ids || []" :key="id" :src="photos.urls.value[id]" :preview-src-list="Object.values(photos.urls.value)" fit="contain" style="width: 160px; height: 120px; margin: 8px" />
        <el-empty v-if="!selected.photo_file_ids?.length" description="本次记录没有可关联的现场照片" />
        <section v-if="canCorrectArchived" data-unsaved-form><h3>归档考勤更正</h3><p>仅追加认定与审计版本；原报表文件与其他学院记录保留。</p><el-select v-model="correctionType" :disabled="correcting"><el-option v-for="(label, value) in labels" :key="value" :value="value" :label="label" /></el-select><el-input v-model="correctionReason" placeholder="更正依据（必填）" maxlength="512" :disabled="correcting" /><el-button type="primary" :disabled="!correctionReason.trim()" :loading="correcting" @click="correctArchived">确认归档更正</el-button></section>
      </template>
    </el-dialog>
  </section>
</template>
<style scoped>.filters { display: flex; gap: 12px; margin: 16px 0; }.el-pagination { margin-top: 16px; }</style>
