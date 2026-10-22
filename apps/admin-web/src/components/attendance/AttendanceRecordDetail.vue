<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { attendanceLabels, correctArchivedAttendance, type AttendanceRecord, type AttendanceType } from '../../api/attendance'
import { useWorkspaceContext } from '../../composables/useWorkspaceContext'
import { useFileAccess } from '../../composables/useFileAccess'
import FileAccessImage from '../FileAccessImage.vue'
const props = defineProps<{ record: AttendanceRecord | null }>()
const emit = defineEmits<{ close: []; updated: [] }>()
const { session, key } = useWorkspaceContext()
const photoContext = computed(() => `${key.value}:${props.record?.id || ''}`)
const photos = useFileAccess(photoContext)
const error = ref(''), correctionType = ref<AttendanceType>('NORMAL'), reason = ref(''), busy = ref(false)
const canCorrect = computed(() => session.currentSemester?.status === 'ARCHIVED' && session.hasPermission('attendance.correct') && session.hasAnyRole('SUPER_ADMIN', 'TEACHER_ADMIN'))
watch(() => props.record, async row => {
  error.value = ''; reason.value = ''; busy.value = false
  if (!row) return
  correctionType.value = row.effective_type
  const context = photoContext.value
  try { await Promise.all((row.photo_file_ids || []).map(id => photos.getUrl(id))) }
  catch (e) { if (context === photoContext.value) error.value = e instanceof Error ? e.message : '照片读取失败' }
}, { immediate: true })
watch(key, () => emit('close'))
async function correct() {
  const row = props.record, captured = photoContext.value
  if (!row || !canCorrect.value || !reason.value.trim() || busy.value) return
  busy.value = true
  try {
    await correctArchivedAttendance(session.workspaceCollegeId, row.id, { attendance_type: correctionType.value, reason: reason.value, current_version: row.current_version })
    if (captured === photoContext.value) { emit('updated'); emit('close') }
  } catch (e) { if (captured === photoContext.value) error.value = e instanceof Error ? e.message : '更正失败，请刷新后重试' }
  finally { if (captured === photoContext.value) busy.value = false }
}
</script>
<template>
  <el-dialog :model-value="!!record" title="考勤记录与现场照片" width="min(820px, 94vw)" append-to-body @update:model-value="emit('close')">
    <template v-if="record">
      <p><strong>{{ record.name }} · {{ record.student_no }}</strong> · {{ attendanceLabels[record.effective_type] }}</p>
      <p>{{ record.administrative_class_name || '历史班级待核对' }} · {{ record.task?.course_name_snapshot }} · {{ record.task?.inspection_date }}</p>
      <p class="muted">任务负责学院：{{ record.task?.responsible_college_name || session.workspace?.name || '历史归属待核对' }} · 当前版本 {{ record.current_version }}</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <FileAccessImage v-for="id in record.photo_file_ids || []" :key="id" :src="photos.urls.value[id]" :preview-src-list="Object.values(photos.urls.value)" :error="photos.errors.value[id]" @failed="photos.retry(id)" @retry="photos.retry(id, true)" fit="contain" style="width:160px;height:120px;margin:8px" />
      <el-empty v-if="!record.photo_file_ids?.length" description="本次记录没有关联的现场照片" />
      <section v-if="canCorrect" data-unsaved-form><h3>归档考勤更正</h3><p>追加认定与审计版本，保留原报表文件。</p><el-select v-model="correctionType" :disabled="busy"><el-option v-for="(label, value) in attendanceLabels" :key="value" :value="value" :label="label" /></el-select><el-input v-model="reason" placeholder="更正依据（必填）" maxlength="512" :disabled="busy" /><el-button type="primary" :disabled="!reason.trim()" :loading="busy" @click="correct">确认归档更正</el-button></section>
    </template>
  </el-dialog>
</template>
<style scoped>.muted { font-size:12px;color:var(--ink-mute); }</style>
