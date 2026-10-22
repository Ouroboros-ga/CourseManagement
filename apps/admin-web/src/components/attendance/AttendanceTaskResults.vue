<script setup lang="ts">
import { computed, ref, shallowRef, watch, onUnmounted } from 'vue'
import { listAttendance, type AttendanceGroup, type AttendanceRecord, type ListAttendanceParams } from '../../api/attendance'
import { useWorkspaceContext } from '../../composables/useWorkspaceContext'
import { useFileAccess } from '../../composables/useFileAccess'
import { ContextEpoch } from '../../utils/contextEpoch'
import AppPagination from '../AppPagination.vue'
import AttendanceRecordTable from './AttendanceRecordTable.vue'
import AttendanceRecordDetail from './AttendanceRecordDetail.vue'
import FileAccessImage from '../FileAccessImage.vue'
const props = defineProps<{ task: AttendanceGroup; filters: ListAttendanceParams }>()
const emit = defineEmits<{ updated: [] }>()
const { key } = useWorkspaceContext()
const page = ref(1), total = ref(0), busy = ref(false), error = ref(''), onlyAbnormal = ref(false)
const rows = shallowRef<AttendanceRecord[]>([]), selected = shallowRef<AttendanceRecord | null>(null)
const photoIds = shallowRef<string[]>([])
const photoContext = computed(() => `${key.value}:${props.task.task_id}`)
const photos = useFileAccess(photoContext)
const epoch = new ContextEpoch(() => `${photoContext.value}:${page.value}:${onlyAbnormal.value}:${JSON.stringify(props.filters)}`)
async function load() {
  const ticket = epoch.begin()
  busy.value = true; error.value = ''; rows.value = []; selected.value = null
  try {
    const result = await listAttendance({ ...props.filters, task_id: props.task.task_id, page: page.value, page_size: 50, abnormal_only: onlyAbnormal.value || props.filters.abnormal_only })
    if (!ticket.isCurrent()) return
    rows.value = result.items; total.value = result.total
    if (!photoIds.value.length && result.items[0]?.photo_file_ids?.length) {
      photoIds.value = result.items[0].photo_file_ids
      await Promise.all(photoIds.value.map(id => photos.getUrl(id)))
    }
  } catch (e) { if (ticket.isCurrent()) { error.value = e instanceof Error ? e.message : '查课结果读取失败'; total.value = 0 } }
  finally { if (ticket.isLatest()) busy.value = false }
}
watch(onlyAbnormal, () => { page.value = 1 }, { flush: 'sync' })
watch([page, onlyAbnormal], () => void load(), { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <section>
    <p class="muted">{{ task.teaching_class_name }} · {{ task.inspection_date }} · {{ task.classroom }} · {{ task.volunteer_name || '历史执行人待核对' }}</p>
    <div v-if="photoIds.length" class="photos"><span>查课现场照片</span><FileAccessImage v-for="id in photoIds" :key="id" :src="photos.urls.value[id]" :preview-src-list="Object.values(photos.urls.value)" :error="photos.errors.value[id]" @failed="photos.retry(id)" @retry="photos.retry(id, true)" fit="cover" style="width:112px;height:80px" /></div>
    <div class="toolbar"><span>本次学生名单</span><el-checkbox v-model="onlyAbnormal">只看异常（迟到、旷课、请假）</el-checkbox><el-button @click="load">刷新</el-button></div>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <AttendanceRecordTable :rows="rows" :busy="busy" max-height="52vh" @open="selected = $event" />
    <AppPagination v-model:current-page="page" :total="total" />
    <AttendanceRecordDetail :record="selected" @close="selected = null" @updated="load(); emit('updated')" />
  </section>
</template>
<style scoped>.muted { color:var(--ink-mute);font-size:13px;margin-bottom:20px; }.photos { display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0; }.toolbar { display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin:15px 0; }.toolbar > span { font-weight:600; }</style>
