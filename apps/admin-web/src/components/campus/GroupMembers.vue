<script setup lang="ts">
import { computed } from 'vue'
import GroupMemberBatch from './GroupMemberBatch.vue'
import GroupUnavailability from './GroupUnavailability.vue'
import { useGroupMembers } from '../../composables/useGroupMembers'

const props = defineProps<{
  collegeId: string
  groupId: string
  semesterId: string
  semesterName?: string
  canManage: boolean
  isSuper: boolean
}>()

const state = useGroupMembers({
  collegeId: () => props.collegeId,
  groupId: () => props.groupId,
  semesterId: () => props.semesterId,
  canManage: () => props.canManage,
  isSuper: () => props.isSuper
})
const visibleRows = computed(() => state.activeKind.value === 'members' ? state.members.value : state.supports.value)
const recordName = (row: { name?: string; student_no?: string; student_id: string }) =>
  row.name ? `${row.name}${row.student_no ? `（${row.student_no}）` : ''}` : `学生 ${row.student_id}`
const canEdit = computed(() => props.canManage && (state.activeKind.value === 'members' || props.isSuper))

function chooseCandidate(candidate: { id: string; name: string; student_no: string }) {
  state.selectedCandidate.value = candidate
  state.draft.value = { ...state.draft.value, student_id: candidate.id }
  state.draft.value.effective_from = state.candidateFrom.value
  state.draft.value.effective_to = state.candidateTo.value
}
</script>

<template>
  <section class="group-members">
    <GroupMemberBatch v-if="canManage" :key="`${collegeId}:${groupId}:${semesterId}`" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" @changed="state.load" />
    <GroupUnavailability :key="`availability:${collegeId}:${groupId}:${semesterId}`" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" :members="state.members.value" :can-manage="canManage" />
    <header class="toolbar">
      <nav class="tabs" aria-label="成员类别">
        <button :class="{ active: state.activeKind.value === 'members' }" type="button" @click="state.setKind('members')">组成员</button>
        <button :class="{ active: state.activeKind.value === 'support-authorizations' }" type="button" @click="state.setKind('support-authorizations')">跨院支援</button>
      </nav>
      <div class="toolbar-actions">
        <button type="button" :disabled="state.busy.value" @click="state.load">刷新</button>
        <button v-if="canEdit" type="button" :disabled="state.busy.value" @click="state.startCreate">新增</button>
      </div>
    </header>

    <p v-if="state.activeKind.value === 'support-authorizations'" class="notice">支援权限固定为授权时已发布的课程类型与班级范围。组范围扩大后须由超管重新授权；未发布配置的授权暂不能用于排班。</p>
    <p v-if="state.error.value" class="notice error" role="alert">{{ state.error.value }}</p>
    <p v-if="state.message.value" class="notice success" role="status">{{ state.message.value }}</p>

    <div v-if="state.creating.value || state.editing.value" class="editor">
      <h3>{{ state.editing.value ? '编辑成员有效期' : state.activeKind.value === 'members' ? '新增组成员' : '新增跨院支援授权' }}</h3>
      <template v-if="state.creating.value">
        <div class="candidate-search">
          <label>有效开始日期<input v-model="state.candidateFrom.value" type="date"></label>
          <label>有效结束日期<input v-model="state.candidateTo.value" type="date"></label>
          <label>姓名或学号<input v-model="state.keyword.value" type="search" maxlength="100" placeholder="输入姓名或学号"></label>
          <button type="button" :disabled="state.busy.value || !state.candidateFrom.value || !state.candidateTo.value" @click="state.searchCandidates">搜索学生</button>
        </div>
        <p v-if="state.selectedCandidate.value" class="selected">已选：{{ state.selectedCandidate.value.name }}（{{ state.selectedCandidate.value.student_no }}）</p>
        <div v-if="state.candidates.value.length" class="candidate-list" aria-label="学生候选">
          <button v-for="candidate in state.candidates.value" :key="candidate.id" type="button" :class="{ selected: state.selectedCandidate.value?.id === candidate.id }" @click="chooseCandidate(candidate)">
            {{ candidate.name }}（{{ candidate.student_no }}）
          </button>
        </div>
      </template>
      <div class="date-fields">
        <label>开始日期<input v-model="state.draft.value.effective_from" type="date" :disabled="state.writing.value"></label>
        <label>结束日期<input v-model="state.draft.value.effective_to" type="date" :disabled="state.writing.value"></label>
        <label v-if="state.editing.value">状态
          <select v-model="state.draft.value.status" :disabled="state.writing.value"><option value="ACTIVE">有效</option><option value="INACTIVE">停用</option></select>
        </label>
      </div>
      <div v-if="state.pendingChange.value" class="impact" role="group" aria-label="未来任务影响确认">
        <p v-if="state.pendingChange.value.impact.retained_future_task_ids.length">
          影响查询发现 {{ state.pendingChange.value.impact.retained_future_task_ids.length }} 个未来受派任务（{{ state.pendingChange.value.impact.retained_future_task_ids.join('、') }}）。这些任务会保留，提交后需另行改派。
        </p>
        <p v-else>影响查询未发现未来受派任务。</p>
        <label v-if="state.pendingChange.value.impact.retained_future_task_ids.length" class="confirmation">
          <input v-model="state.confirmFutureAssignments.value" type="checkbox">
          我已了解未来任务会保留，并会安排改派
        </label>
      </div>
      <div class="editor-actions">
        <button type="button" :disabled="state.writing.value" @click="state.cancelEdit">取消</button>
        <button v-if="state.creating.value" type="button" class="primary" :disabled="state.busy.value || !state.selectedCandidate.value || !state.draft.value.effective_from || !state.draft.value.effective_to" @click="state.create">新增</button>
        <template v-else-if="state.editing.value">
          <button v-if="!state.pendingChange.value" type="button" class="primary" :disabled="state.busy.value || !state.draft.value.effective_from || !state.draft.value.effective_to" @click="state.prepareChange(state.editing.value)">查询影响并继续</button>
          <button v-else type="button" class="primary" :disabled="state.busy.value || (state.pendingChange.value.impact.retained_future_task_ids.length > 0 && !state.confirmFutureAssignments.value)" @click="state.applyChange">{{ state.pendingChange.value.revoke ? '确认停用' : '确认更新' }}</button>
        </template>
      </div>
    </div>

    <p v-if="state.loading.value" class="loading">正在读取成员记录…</p>
    <div v-else class="table-wrap">
      <table>
        <thead><tr><th>学生</th><th>学期</th><th>有效日期</th><th>状态</th><th>版本</th><th v-if="canEdit">操作</th></tr></thead>
        <tbody>
          <tr v-for="row in visibleRows" :key="row.id">
            <td>{{ recordName(row) }}</td>
            <td>{{ semesterName || '当前学期' }}</td>
            <td>{{ row.effective_from }} 至 {{ row.effective_to }}</td>
            <td><span :class="['status', row.status.toLowerCase()]">{{ row.status === 'ACTIVE' ? '有效' : '停用' }}</span></td>
            <td>{{ row.lock_version }}</td>
            <td v-if="canEdit" class="row-actions">
              <button type="button" :disabled="state.busy.value" @click="state.startEdit(row)">编辑</button>
              <button v-if="row.status === 'ACTIVE'" type="button" :disabled="state.busy.value" @click="state.prepareChange(row, true)">停用</button>
              <button v-else type="button" :disabled="state.busy.value" @click="state.startEdit(row); state.draft.value.status = 'ACTIVE'">重新启用</button>
            </td>
          </tr>
          <tr v-if="visibleRows.length === 0"><td :colspan="canEdit ? 6 : 5" class="empty">暂无记录</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.group-members { display: grid; gap: 16px; color: var(--el-text-color-primary); }
.toolbar, .toolbar-actions, .tabs, .editor-actions, .row-actions { display: flex; align-items: center; gap: 8px; }
.toolbar { justify-content: space-between; }
.tabs button, .toolbar button, .editor button, .row-actions button { border: 1px solid var(--el-border-color); border-radius: 6px; background: var(--el-bg-color); color: inherit; padding: 7px 12px; cursor: pointer; }
.tabs button.active, button.primary { border-color: var(--el-color-primary); background: var(--el-color-primary); color: white; }
button:disabled { opacity: .55; cursor: not-allowed; }
.editor { display: grid; gap: 14px; border: 1px solid var(--el-border-color); border-radius: 8px; padding: 16px; }
.editor h3 { margin: 0; font-size: 16px; }
.candidate-search, .date-fields { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; }
label { display: grid; gap: 5px; color: var(--el-text-color-secondary); font-size: 13px; }
input, select { min-height: 34px; border: 1px solid var(--el-border-color); border-radius: 5px; padding: 4px 8px; color: var(--el-text-color-primary); background: var(--el-bg-color); }
.candidate-list { display: flex; flex-wrap: wrap; gap: 8px; }
.candidate-list button { text-align: left; }
.candidate-list button.selected { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.selected { margin: 0; color: var(--el-color-primary); }
.impact { border-left: 3px solid var(--el-color-warning); padding: 8px 12px; background: var(--el-fill-color-light); }
.impact p { margin: 4px 0 10px; }
.confirmation { display: flex; align-items: center; gap: 8px; color: var(--el-text-color-primary); }
.confirmation input { min-height: unset; }
.editor-actions { justify-content: flex-end; }
.notice { margin: 0; padding: 9px 12px; border-radius: 6px; }
.notice.error { color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.notice.success { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { border-bottom: 1px solid var(--el-border-color-lighter); padding: 10px 12px; text-align: left; white-space: nowrap; }
th { color: var(--el-text-color-secondary); font-weight: 600; }
.status { border-radius: 999px; padding: 3px 8px; }
.status.active { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.status.inactive { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
.empty, .loading { padding: 20px; text-align: center; color: var(--el-text-color-secondary); }
</style>
