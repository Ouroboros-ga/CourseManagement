<script setup lang="ts">
import AppPagination from '../AppPagination.vue'
import { computed, ref, watch } from 'vue'
import GroupMemberBatch from './GroupMemberBatch.vue'
import GroupMemberImport from './GroupMemberImport.vue'
import { useSessionStore } from '../../stores/session'
import { memberDates } from '../../utils/memberDates'
import GroupUnavailability from './GroupUnavailability.vue'
import { useGroupMembers } from '../../composables/useGroupMembers'

const props = defineProps<{
  collegeId: string
  groupId: string
  semesterId: string
  semesterName?: string
  canManage: boolean
  isSuper: boolean
  compact?: boolean
  asOf?: string
}>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore(), importing = ref(false), leaveOpen = ref(false), batchOpen = ref(false), keyword = ref('')

const state = useGroupMembers({
  collegeId: () => props.collegeId,
  groupId: () => props.groupId,
  semesterId: () => props.semesterId,
  canManage: () => props.canManage,
  isSuper: () => props.isSuper,
  canQualify: () => session.hasPermission('volunteer.manage')
})
const memberPage = ref(1)
const allVisibleRows = computed(() => state.members.value.filter(row => !keyword.value.trim() || `${row.name || ''} ${row.student_no || ''}`.includes(keyword.value.trim())))
const visibleRows = computed(() => allVisibleRows.value.slice((memberPage.value - 1) * 50, memberPage.value * 50))
watch(allVisibleRows, () => { memberPage.value = 1 })
watch(() => JSON.stringify(state.members.value), () => emit('changed'))
watch(() => [state.candidateFrom.value, state.candidateTo.value], () => { if (props.compact && state.creating.value) { state.selectedCandidate.value = null; state.candidates.value = [] } }, { flush: 'sync' })
function memberStatus(row: { status: string; effective_from: string; effective_to: string }) {
  const day = props.asOf || new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
  return row.status !== 'ACTIVE' ? '已停用' : row.effective_to <= day ? '已到期' : row.effective_from > day ? '待生效' : '有效'
}
const recordName = (row: { name?: string; student_no?: string; student_id: string }) =>
  row.name ? `${row.name}${row.student_no ? `（${row.student_no}）` : ''}` : `学生 ${row.student_id}`
const canEdit = computed(() => props.canManage)
function startCreate() {
  state.startCreate()
  const dates = memberDates(session.currentSemester)
  state.candidateFrom.value = dates.from; state.candidateTo.value = dates.to
}

function chooseCandidate(candidate: { id: string; name: string; student_no: string }) {
  state.selectedCandidate.value = candidate
  state.draft.value = { ...state.draft.value, student_id: candidate.id }
  state.draft.value.effective_from = state.candidateFrom.value
  state.draft.value.effective_to = state.candidateTo.value
}
</script>

<template>
  <section class="group-members">
    <p class="notice">本组仅安排本学院学生。同一学生仍可加入本学院多个组。</p>
    <GroupMemberBatch v-if="canManage && !compact" :key="`${collegeId}:${groupId}:${semesterId}`" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" @changed="state.load" />
    <GroupUnavailability v-if="!compact" :key="`availability:${collegeId}:${groupId}:${semesterId}`" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" :members="state.members.value" :can-manage="canManage" />
    <header class="toolbar">
      <h3 v-if="!compact">组成员</h3>
      <el-input v-if="compact" v-model="keyword" placeholder="搜索姓名或学号" clearable aria-label="搜索本组成员" style="max-width:260px" />
      <div class="toolbar-actions">
        <button type="button" :disabled="state.busy.value" @click="state.load">刷新</button>
        <button v-if="canManage" type="button" :disabled="state.busy.value" @click="importing = true">导入成员 Excel</button>
        <button v-if="canEdit" type="button" :disabled="state.busy.value" @click="startCreate">添加成员</button>
      </div>
    </header>
    <div v-if="compact" class="secondary-actions">
      <el-button link @click="leaveOpen = true">请假记录与审批</el-button>
      <el-button v-if="canManage" link @click="batchOpen = true">粘贴学号批量加入</el-button>
    </div>

    <p v-if="state.error.value" class="notice error" role="alert">{{ state.error.value }}</p>
    <p v-if="state.message.value" class="notice success" role="status">{{ state.message.value }}</p>

    <div v-if="state.creating.value || state.editing.value" class="editor">
      <h3>{{ state.editing.value ? '编辑成员有效期' : '新增组成员' }}</h3>
      <label v-if="!compact && state.creating.value && session.hasPermission('volunteer.manage')"><input v-model="state.enableQualification.value" type="checkbox">同时开通本学期志愿者资格</label>
      <p v-if="compact && state.creating.value" class="notice">{{ session.hasPermission('volunteer.manage') ? '选人后同时开通缺失的本学期资格并加入本组，已加入的其他组织保留。' : '你可以维护成员，但无权开通志愿者资格；加入后需由学院管理员核对本学期资格，未满足资格不能排班。' }}</p>
      <template v-if="state.creating.value">
        <el-collapse v-if="compact"><el-collapse-item title="调整成员有效期（默认本学期）" name="dates"><div class="date-fields"><label>开始日期<input v-model="state.candidateFrom.value" type="date"></label><label>失效日期（不含）<input v-model="state.candidateTo.value" type="date"></label></div><p>修改有效期后请重新搜索并选择学生。</p></el-collapse-item></el-collapse>
        <div class="candidate-search">
          <label v-if="!compact">有效开始日期<input v-model="state.candidateFrom.value" type="date"></label>
          <label v-if="!compact">有效结束日期<input v-model="state.candidateTo.value" type="date"></label>
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
      <div v-if="!compact || state.editing.value" class="date-fields">
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
        <button v-if="state.creating.value" type="button" class="primary" :disabled="state.busy.value || !state.selectedCandidate.value || !state.draft.value.effective_from || !state.draft.value.effective_to" @click="state.create">确认加入本组</button>
        <template v-else-if="state.editing.value">
          <button v-if="!state.pendingChange.value" type="button" class="primary" :disabled="state.busy.value || !state.draft.value.effective_from || !state.draft.value.effective_to" @click="state.prepareChange(state.editing.value)">查询影响并继续</button>
          <button v-else type="button" class="primary" :disabled="state.busy.value || (state.pendingChange.value.impact.retained_future_task_ids.length > 0 && !state.confirmFutureAssignments.value)" @click="state.applyChange">{{ state.pendingChange.value.revoke ? '确认停用' : '确认更新' }}</button>
        </template>
      </div>
    </div>

    <el-dialog v-if="compact" v-model="leaveOpen" title="本组成员请假与不可用" width="min(1120px, 94vw)" destroy-on-close append-to-body>
      <GroupUnavailability v-if="leaveOpen" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" :members="state.members.value" :can-manage="canManage" expanded />
    </el-dialog>
    <el-dialog v-if="compact" v-model="batchOpen" title="粘贴学号批量加入本组" width="min(820px, 94vw)" destroy-on-close append-to-body>
      <GroupMemberBatch v-if="batchOpen" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" @changed="state.load" />
    </el-dialog>
    <p v-if="state.loading.value" class="loading">正在读取成员记录…</p>
    <div v-else class="table-wrap">
      <table>
        <thead><tr><th>学生</th><th v-if="!compact">学期</th><th>有效日期</th><th>状态</th><th v-if="!compact">版本</th><th v-if="canEdit">操作</th></tr></thead>
        <tbody>
          <tr v-for="row in visibleRows" :key="row.id">
            <td>{{ recordName(row) }}</td>
            <td v-if="!compact">{{ semesterName || '当前学期' }}</td>
            <td>{{ row.effective_from }} 至 {{ row.effective_to }}（不含结束日）</td>
            <td><span :class="['status', row.status.toLowerCase()]">{{ memberStatus(row) }}</span></td>
            <td v-if="!compact">{{ row.lock_version }}</td>
            <td v-if="canEdit" class="row-actions">
              <button type="button" :disabled="state.busy.value" @click="state.startEdit(row)">编辑</button>
              <button v-if="row.status === 'ACTIVE'" type="button" :disabled="state.busy.value" @click="state.prepareChange(row, true)">停用</button>
              <button v-else type="button" :disabled="state.busy.value" @click="state.startEdit(row); state.draft.value.status = 'ACTIVE'">重新启用</button>
            </td>
          </tr>
          <tr v-if="visibleRows.length === 0"><td :colspan="(canEdit ? 6 : 5) - (compact ? 2 : 0)" class="empty">{{ keyword ? '没有匹配的成员' : '本组还没有成员，请添加本学院已有学籍的学生或导入 Excel。' }}</td></tr>
        </tbody>
      </table>
      <AppPagination v-model:current-page="memberPage" :total="allVisibleRows.length" />
    </div>
  </section>
  <el-dialog v-model="importing" title="导入当前组成员" width="min(820px, 94vw)" destroy-on-close :close-on-click-modal="false">
    <GroupMemberImport v-if="importing" :key="`${collegeId}:${groupId}:${semesterId}`" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId" @changed="state.load" />
  </el-dialog>
</template>

<style scoped>
.group-members { display: grid; gap: 16px; color: var(--el-text-color-primary); }
.toolbar, .toolbar-actions, .tabs, .editor-actions, .row-actions { display: flex; align-items: center; gap: 8px; }
.toolbar { justify-content: space-between; flex-wrap: wrap; }
.secondary-actions { display: flex; gap: 16px; flex-wrap: wrap; }
.tabs button, .toolbar button, .editor button, .row-actions button { border: 1px solid var(--el-border-color); border-radius: var(--radius-md); background: var(--el-bg-color); color: inherit; padding: 7px 12px; cursor: pointer; }
.tabs button.active, button.primary { border-color: var(--el-color-primary); background: var(--el-color-primary); color: white; }
button:disabled { opacity: .55; cursor: not-allowed; }
.editor { display: grid; gap: 14px; border: 1px solid var(--el-border-color); border-radius: var(--radius-md); padding: 16px; }
.editor h3 { margin: 0; }
.candidate-search, .date-fields { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; }
label { display: grid; gap: 5px; color: var(--el-text-color-secondary); font-size: var(--text-sm); }
input, select { min-height: 34px; border: 1px solid var(--el-border-color); border-radius: var(--radius-md); padding: 4px 8px; color: var(--el-text-color-primary); background: var(--el-bg-color); }
.candidate-list { display: flex; flex-wrap: wrap; gap: 8px; }
.candidate-list button { text-align: left; }
.candidate-list button.selected { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.selected { margin: 0; color: var(--el-color-primary); }
.impact { border-left: 3px solid var(--el-color-warning); padding: 8px 12px; background: var(--el-fill-color-light); }
.impact p { margin: 4px 0 10px; }
.confirmation { display: flex; align-items: center; gap: 8px; color: var(--el-text-color-primary); }
.confirmation input { min-height: unset; }
.editor-actions { justify-content: flex-end; }
.notice { margin: 0; padding: 9px 12px; border-radius: var(--radius-md); }
.notice.error { color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.notice.success { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { border-bottom: 1px solid var(--el-border-color-lighter); padding: 10px 12px; text-align: left; white-space: nowrap; }
th { color: var(--el-text-color-secondary); font-weight: 600; }
.status { border-radius: var(--radius-pill); padding: 3px 8px; }
.status.active { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.status.inactive { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
.empty, .loading { padding: 20px; text-align: center; color: var(--el-text-color-secondary); }
</style>
