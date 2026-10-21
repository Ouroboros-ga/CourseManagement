<script setup lang="ts">
import { useDisplayPage } from '../../composables/useDisplayPage'
import AppPagination from '../../components/AppPagination.vue'
import { computed } from 'vue'
import { assignmentWarnings } from '../../utils/assignmentWarnings'
import { useGroupSampling } from '../../composables/useGroupSampling'

const props = defineProps<{
  collegeId: string
  groupId: string
  semesterId: string
  canGenerate: boolean
  canAssign: boolean
}>()

const state = useGroupSampling({
  collegeId: () => props.collegeId,
  groupId: () => props.groupId,
  semesterId: () => props.semesterId,
  canGenerate: () => props.canGenerate,
  canAssign: () => props.canAssign
})
const dateFrom = computed({
  get: () => state.form.value.date_from,
  set: value => state.setDateRange(value, state.form.value.date_to)
})
const dateTo = computed({
  get: () => state.form.value.date_to,
  set: value => state.setDateRange(state.form.value.date_from, value)
})
const requirePhoto = computed({
  get: () => state.form.value.require_photo,
  set: value => state.setRequirePhoto(value)
})
const formLocked = computed(() => state.writing.value || Boolean(state.generateResult.value) || !props.canGenerate)
const selected = (id: string) => state.form.value.selectedClassIds.includes(id)

function classChanged(id: string, event: Event) {
  state.toggleClass(id, (event.target as HTMLInputElement).checked)
}
function countChanged(id: string, event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (Number.isInteger(value)) state.setCount(id, value)
}

const { page: display0Page, rows: display0Rows, total: display0Total } = useDisplayPage(() => state.previewResult.value?.items || [])
const { page: display1Page, rows: display1Rows, total: display1Total } = useDisplayPage(() => state.generateResult.value?.tasks || [])
const { page: display2Page, rows: display2Rows, total: display2Total } = useDisplayPage(() => state.assignmentPlan.value?.assigned || [])
const { page: display3Page, rows: display3Rows, total: display3Total } = useDisplayPage(() => state.assignmentResult.value?.assigned || [])
const { page: display4Page, rows: display4Rows, total: display4Total } = useDisplayPage(() => state.assignmentResult.value?.unassigned || [])
</script>

<template>
  <section class="group-sampling">
    <header class="header">
      <div>
        <h2>组范围抽查</h2>
        <p>选择本院行政班和每班次数，先预览，再确认生成，最后为生成的任务排班。</p>
      </div>
      <button type="button" :disabled="state.busy.value || !props.canGenerate" @click="state.loadClasses">刷新行政班</button>
    </header>

    <p v-if="state.error.value" class="notice error" role="alert">{{ state.error.value }}</p>
    <p v-if="state.message.value" class="notice success" role="status">{{ state.message.value }}</p>

    <fieldset class="configuration" :disabled="formLocked">
      <legend>抽查范围</legend>
      <div class="range-fields">
        <label>开始日期<input v-model="dateFrom" type="date"></label>
        <label>结束日期<input v-model="dateTo" type="date"></label>
        <label class="photo-option"><input v-model="requirePhoto" type="checkbox">需要现场照片</label>
      </div>

      <div class="class-heading">
        <h3>行政班与抽查次数</h3>
        <span>已选 {{ state.form.value.selectedClassIds.length }} 个班 · 合计 {{ state.totalRequested.value }} 次</span>
      </div>
      <p v-if="state.classLoading.value" class="muted">正在读取行政班…</p>
      <div v-else-if="state.activeClasses.value.length" class="class-list">
        <div v-for="item in state.activeClasses.value" :key="item.id" class="class-row">
          <label class="class-choice">
            <input type="checkbox" :checked="selected(item.id)" @change="classChanged(item.id, $event)">
            <span>{{ item.class_name }}<small v-if="item.class_code">（{{ item.class_code }}）</small></span>
          </label>
          <label v-if="selected(item.id)" class="count-field">次数
            <input type="number" min="1" max="50" step="1" :value="state.form.value.counts[item.id]" @change="countChanged(item.id, $event)">
          </label>
        </div>
      </div>
      <p v-else class="muted">没有可选的有效行政班。</p>
      <p v-if="state.totalRequested.value > 500" class="notice error">总次数不能超过 500。</p>
    </fieldset>

    <div class="actions" aria-label="抽查与排班步骤">
      <button type="button" class="primary" :disabled="state.busy.value || !state.canPreview.value || Boolean(state.generateResult.value)" @click="state.preview">
        {{ state.previewing.value ? '正在预览…' : '1. 预览抽查' }}
      </button>
      <button type="button" class="primary" :disabled="state.busy.value || !state.previewResult.value || !props.canGenerate || Boolean(state.generateResult.value)" @click="state.generate">
        2. 确认生成任务
      </button>
      <button v-if="state.generateResult.value && props.canAssign" type="button" class="primary" :disabled="state.busy.value || !state.generateResult.value.assignable_task_ids.length" @click="state.assign">
        {{ state.writing.value ? '正在准备…' : '3. 预览排班计划' }}
      </button>
      <span v-if="state.generateResult.value && !state.generateResult.value.assignable_task_ids.length" class="muted">没有可排班任务，未发送排班请求。</span>
      <span v-else-if="state.generateResult.value && !props.canAssign" class="muted">当前账号没有排班权限。</span>
    </div>

    <section v-if="state.previewResult.value" class="result-panel">
      <h3>抽查预览</h3>
      <p>候选 {{ state.previewResult.value.candidate_count }} 项，选中 {{ state.previewResult.value.selected_count }} 项；修订号 {{ state.previewResult.value.selection_revision }}</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>日期</th><th>周次 / 节次</th><th>班级</th><th>课程</th><th>地点</th><th>人数</th></tr></thead>
          <tbody>
            <tr v-for="item in display0Rows" :key="item.task_key">
              <td>{{ item.inspection_date }}</td>
              <td>第 {{ item.week_no }} 周 · 第 {{ item.start_period }}–{{ item.end_period }} 节</td>
              <td>{{ item.class_name_snapshot }}</td>
              <td>{{ item.course_name_snapshot }}</td>
              <td>{{ item.classroom_snapshot || '未填写' }}</td>
              <td>{{ item.expected_count }}</td>
            </tr>
            <tr v-if="state.previewResult.value.items.length === 0"><td colspan="6" class="empty">本次没有可抽查课次。</td></tr>
          </tbody>
        </table>
<AppPagination v-model:current-page="display0Page" :total="display0Total" />
      </div>
    </section>

    <section v-if="state.generateResult.value" class="result-panel generated">
      <h3>已生成任务</h3>
      <p>新增 {{ state.generateResult.value.created }} 项，已存在 {{ state.generateResult.value.existed }} 项，共计划 {{ state.generateResult.value.total_planned }} 项。</p>
      <p v-if="state.generatedBody.value" class="muted">对应抽查日期 {{ state.generatedBody.value.date_from }} 至 {{ state.generatedBody.value.date_to }}；照片要求：{{ state.generatedBody.value.require_photo ? '需要' : '不需要' }}。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>任务 ID</th><th>状态</th><th>本次是否新建</th><th>已有排班 ID</th></tr></thead>
          <tbody>
            <tr v-for="task in display1Rows" :key="task.task_id">
              <td>{{ task.task_id }}</td><td>{{ task.status }}</td><td>{{ task.created ? '是' : '否' }}</td><td>{{ task.assignment_id || '—' }}</td>
            </tr>
            <tr v-if="state.generateResult.value.tasks.length === 0"><td colspan="4" class="empty">生成接口未返回任务明细。</td></tr>
          </tbody>
        </table>
<AppPagination v-model:current-page="display1Page" :total="display1Total" />
      </div>
    </section>

    <section v-if="state.assignmentPlan.value" class="result-panel assignments">
      <h3>待确认排班计划</h3>
      <p>尚未派发。请核对每项任务、志愿者和警告，计划有效期十分钟。</p>
      <table><thead><tr><th>任务</th><th>志愿者</th><th>规则警告与确认</th></tr></thead><tbody>
        <tr v-for="item in display2Rows" :key="item.task_id">
          <td>{{ item.task_id }}</td><td>{{ item.volunteer_user_id }}</td>
          <td><label v-if="item.warning_codes.length"><input v-model="state.confirmedWarnings.value" type="checkbox" :value="item.task_id" :disabled="state.writing.value">我确认：{{ assignmentWarnings(item.warning_codes) }}</label><span v-else>无警告</span></td>
        </tr>
      </tbody></table>
<AppPagination v-model:current-page="display2Page" :total="display2Total" />
      <p v-for="item in state.assignmentPlan.value.unassigned" :key="item.task_id">任务 {{ item.task_id }} 未排：{{ item.message }}</p>
      <button type="button" class="primary" :disabled="state.writing.value || !state.canConfirmAssignment.value" @click="state.confirmAssignment">确认计划并派发</button>
    </section>

    <section v-if="state.assignmentResult.value" class="result-panel assignments">
      <h3>排班结果</h3>
      <p>已排 {{ state.assignmentResult.value.assigned_count }} / {{ state.assignmentResult.value.target_task_count }} 项，未排 {{ state.assignmentResult.value.unassigned_count }} 项。</p>
      <div v-if="state.assignmentResult.value.assigned.length" class="table-wrap">
        <table><thead><tr><th>任务 ID</th><th>志愿者账号 ID</th><th>规则提示</th></tr></thead>
          <tbody><tr v-for="item in display3Rows" :key="item.task_id"><td>{{ item.task_id }}</td><td>{{ item.volunteer_user_id }}</td><td>{{ assignmentWarnings(item.warning_codes) || '无' }}</td></tr></tbody>
        </table>
<AppPagination v-model:current-page="display3Page" :total="display3Total" />
      </div>
      <div v-if="state.assignmentResult.value.unassigned.length" class="table-wrap">
        <table><thead><tr><th>未排任务 ID</th><th>原因</th><th>说明</th></tr></thead>
          <tbody><tr v-for="item in display4Rows" :key="item.task_id"><td>{{ item.task_id }}</td><td>{{ item.reason_code }}</td><td>{{ item.message }}</td></tr></tbody>
        </table>
<AppPagination v-model:current-page="display4Page" :total="display4Total" />
      </div>
    </section>
  </section>
</template>

<style scoped>
.group-sampling { display: grid; gap: 18px; color: var(--el-text-color-primary); }
.header, .class-heading, .actions, .range-fields { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.header h2, .class-heading h3, .result-panel h3 { margin: 0; }
.header p, .result-panel p { color: var(--el-text-color-secondary); margin: 6px 0 0; }
button { border: 1px solid var(--el-border-color); border-radius: var(--radius-md); background: var(--el-bg-color); color: inherit; padding: 8px 12px; cursor: pointer; }
button.primary { border-color: var(--el-color-primary); background: var(--el-color-primary); color: var(--paper); }
button:disabled { cursor: not-allowed; opacity: .55; }
.configuration, .result-panel { min-width: 0; border: 1px solid var(--el-border-color); border-radius: var(--radius-md); padding: 16px; }
.configuration legend { padding: 0 6px; font-weight: 600; }
.range-fields { justify-content: flex-start; margin-bottom: 18px; }
.range-fields > label, .count-field { display: grid; gap: 5px; color: var(--el-text-color-secondary); font-size: 13px; }
input[type="date"], input[type="number"] { min-height: 34px; width: 150px; border: 1px solid var(--el-border-color); border-radius: var(--radius-md); padding: 4px 8px; background: var(--el-bg-color); color: var(--el-text-color-primary); }
.photo-option { display: flex !important; align-items: center; gap: 8px !important; min-height: 36px; }
.class-heading { margin-bottom: 8px; }
.class-heading span, .muted { color: var(--el-text-color-secondary); font-size: 13px; }
.class-list { border-top: 1px solid var(--el-border-color-lighter); }
.class-row { display: flex; min-height: 48px; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--el-border-color-lighter); padding: 6px 4px; }
.class-choice { display: flex; align-items: center; gap: 10px; }
.class-choice small { color: var(--el-text-color-secondary); }
.count-field { display: flex; align-items: center; }
.count-field input { width: 84px; }
.actions { justify-content: flex-start; }
.notice { margin: 0; padding: 9px 12px; border-radius: var(--radius-md); }
.notice.error { color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.notice.success { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.result-panel { display: grid; gap: 12px; }
.table-wrap { max-width: 100%; overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--el-border-color-lighter); text-align: left; white-space: nowrap; }
th { color: var(--el-text-color-secondary); font-weight: 600; }
.empty { padding: 18px; text-align: center; color: var(--el-text-color-secondary); }
</style>
