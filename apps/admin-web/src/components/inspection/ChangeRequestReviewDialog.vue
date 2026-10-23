<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getTask, listTaskCandidateVolunteers, assignTask, reviewChangeRequest,
  type ChangeRequestItem, type InspectionTaskItem, type TaskCandidateVolunteerItem } from '../../api/tasks'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch } from '../../utils/contextEpoch'
import { confirmGroupAssignment } from '../../composables/confirmGroupAssignment'
import { formatPeriodText } from '../../utils/period'
const props = defineProps<{ request: ChangeRequestItem | null }>()
const emit = defineEmits<{ close: []; processed: [] }>()
const session = useSessionStore()
const task = ref<InspectionTaskItem | null>(null)
const candidates = ref<TaskCandidateVolunteerItem[]>([])
const selected = ref(''), comment = ref(''), error = ref(''), loading = ref(false), busy = ref(false)
const context = () => JSON.stringify([props.request?.id, session.currentUser?.id,
  session.workspaceCollegeId, session.currentSemesterId, session.workspace?.authorization_revision])
const epoch = new ContextEpoch(context)
onUnmounted(() => epoch.invalidate())
const current = computed(() => !!task.value && !!props.request && props.request.can_process
  && task.value.assignment?.change_request_id === props.request.id
  && task.value.assignment?.change_request_status === 'PENDING'
  && !task.value.exception_reported_at && !task.value.canceled_at && !task.value.deleted_at
  && !['已完成', '待审核', 'REVIEWED', 'SUBMITTED'].includes(task.value.status))
const chosen = computed(() => candidates.value.find(row => row.user_id === selected.value))
const canAssign = computed(() => current.value && session.hasPermission('assignment.manage')
  && chosen.value?.eligible && selected.value !== props.request?.request_user_id)
watch(context, async () => {
  const ticket = epoch.begin()
  task.value = null; candidates.value = []; selected.value = ''; comment.value = ''; error.value = ''
  if (!props.request) { loading.value = false; return }
  loading.value = true
  try {
    const data = await getTask(props.request.task_id)
    if (!ticket.isCurrent()) return
    task.value = data
    if (!current.value) { error.value = '申请或任务状态已变化，请关闭并刷新列表'; return }
    if (session.hasPermission('assignment.manage')) {
      const people = await listTaskCandidateVolunteers(data.id)
      if (ticket.isCurrent()) candidates.value = people
    }
  } catch (e) {
    if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '任务资料读取失败'
  } finally { if (ticket.isLatest()) loading.value = false }
}, { immediate: true })
async function process(decision: 'APPROVED' | 'REJECTED') {
  const row = props.request, source = task.value
  if (busy.value || !row || !source || !current.value) return
  if (decision === 'APPROVED' && !canAssign.value) return
  const ticket = epoch.begin()
  busy.value = true
  try {
    if (decision === 'REJECTED') {
      await reviewChangeRequest(row.id, { decision, comment: comment.value })
    } else {
      const result = source.group_id
        ? await confirmGroupAssignment(source, selected.value, comment.value, ticket.isCurrent)
        : await assignTask(source.id, { volunteer_user_id: selected.value,
          lock_version: source.lock_version ?? 0, reason: comment.value })
      if (!result) return
    }
    if (!ticket.isCurrent()) return
    ElMessage.success(decision === 'APPROVED' ? '已同意换班并完成改派' : '已驳回申请，原受派保持不变')
    emit('processed'); emit('close')
  } catch (e) {
    if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '处理失败，请刷新后核对'
  } finally { busy.value = false }
}
</script>
<template>
  <el-dialog :model-value="!!request" title="处理换班申请" width="660px" :close-on-click-modal="!busy"
    :close-on-press-escape="!busy" :show-close="!busy" @close="emit('close')">
    <div v-if="request" v-loading="loading">
      <div class="request-overview">
        <h3>{{ request.course_name || '未命名课程' }}</h3>
        <p>{{ request.inspection_date }} · {{ formatPeriodText(request.start_period, request.end_period, request) }} · {{ request.classroom || '未指定教室' }}</p>
        <p>{{ request.class_name || '未指定班级' }}</p>
        <p><strong>{{ request.requester_name || '原受派人' }}</strong> {{ request.requester_student_no || '' }}</p>
        <p>申请说明：{{ request.reason || '未填写' }}</p>
      </div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-form label-position="top">
        <el-form-item v-if="session.hasPermission('assignment.manage')" label="顶班志愿者">
          <el-select v-model="selected" placeholder="搜索并选择顶班人员" filterable clearable :disabled="busy || !current" style="width:100%">
            <el-option v-for="person in candidates" :key="person.user_id" :value="person.user_id"
              :label="`${person.name} · ${person.student_no} · ${person.class_name || '未分班'}`"
              :disabled="!person.eligible || person.user_id === request.request_user_id">
              <span>{{ person.name }} · {{ person.student_no }}</span>
              <small v-if="person.user_id === request.request_user_id"> 原受派人</small>
              <small v-else-if="!person.eligible"> {{ person.conflict_message || '不符合排班条件' }}</small>
            </el-option>
          </el-select>
        </el-form-item>
        <p class="muted">同意申请后，任务会直接改派给所选人员。人员不足时可暂不处理。</p>
        <el-form-item label="处理说明（选填）"><el-input v-model="comment" type="textarea" :maxlength="512" show-word-limit :disabled="busy" /></el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button :disabled="busy" @click="emit('close')">暂不处理</el-button>
      <el-button type="danger" plain :disabled="busy || loading || !current" @click="process('REJECTED')">驳回申请</el-button>
      <el-button type="primary" :loading="busy" :disabled="loading || !canAssign" @click="process('APPROVED')">同意并改派</el-button>
    </template>
  </el-dialog>
</template>
<style scoped>
.request-overview { padding:16px 20px; background:var(--paper-deep); border:1px solid var(--line); margin-bottom:20px; }
.request-overview h3 { margin:0 0 10px; }.request-overview p { margin:6px 0; overflow-wrap:anywhere; }
.muted, small { color:var(--ink-mute); } .muted { font-size:13px; margin:0 0 16px; }
</style>
