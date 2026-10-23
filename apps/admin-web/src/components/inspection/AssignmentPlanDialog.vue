<script setup lang="ts">
import { computed, ref, watch, watchEffect, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import AppPagination from '../AppPagination.vue'
import { assignmentPlanReview as review, finishAssignmentPlanReview as finish } from '../../composables/useAssignmentPlanDialog'
import { assignmentPlanRows } from '../../utils/assignmentPlanRows'
import { assignmentWarnings } from '../../utils/assignmentWarnings'
import { formatPeriodText } from '../../utils/period'

const tab = ref('assigned'), search = ref(''), page = ref(1)
const route = useRoute()
const rows = computed(() => review.value ? assignmentPlanRows(review.value.plan, review.value.tasks) : { assigned: [], unassigned: [] })
const warningCount = computed(() => rows.value.assigned.filter(row => row.warningCodes.length).length)
const dates = computed(() => [...rows.value.assigned, ...rows.value.unassigned].map(row => row.inspectionDate).filter(Boolean).sort())
const dateRange = computed(() => dates.value.length ? `${dates.value[0]} — ${dates.value[dates.value.length - 1]}` : '')
const filtered = computed(() => {
  const source = tab.value === 'assigned' ? rows.value.assigned : rows.value.unassigned
  const word = search.value.trim().toLowerCase()
  return source.filter(row => !word || [row.courseName, row.teachingClassName, row.inspectionDate, row.classroom,
    'volunteerName' in row ? row.volunteerName : row.reason,
    'studentNo' in row ? row.studentNo : ''].join(' ').toLowerCase().includes(word))
})
const visible = computed(() => filtered.value.slice((page.value - 1) * 50, page.value * 50))
watch(() => review.value?.plan.id, () => {
  tab.value = review.value?.plan.assigned.length ? 'assigned' : 'unassigned'
  search.value = ''; page.value = 1
})
watch(tab, () => { search.value = ''; page.value = 1 })
watch(search, () => { page.value = 1 })
watch(() => route.fullPath, () => finish(false))
watchEffect(() => { if (review.value && !review.value.isCurrent()) finish(false) })
onBeforeUnmount(() => finish(false))
function updateOpen(value: boolean) { if (!value) finish(false) }
</script>

<template>
  <el-dialog v-if="review" :model-value="true" title="核对排班计划" class="assignment-preview" width="min(1120px, 94vw)"
    top="5vh" :close-on-click-modal="false" @update:model-value="updateOpen">
    <template #header>
      <div class="assignment-preview__header">
        <h2>核对排班计划</h2>
        <p>{{ review.plan.display?.group_name || '当前志愿者组' }}<span v-if="review.plan.display?.semester_name"> · {{ review.plan.display.semester_name }}</span></p>
      </div>
    </template>

    <div class="assignment-preview__scope">
      <span>{{ review.scopeLabel }}</span><span v-if="dateRange">{{ dateRange }}</span>
    </div>
    <div class="assignment-preview__summary">
      <div><span>本组待排任务</span><strong>{{ review.targetCount }}<small>项</small></strong></div>
      <div class="assignment-preview__ready"><span>拟派发</span><strong>{{ rows.assigned.length }}<small>项</small></strong></div>
      <div class="assignment-preview__pending"><span>暂未分配</span><strong>{{ rows.unassigned.length }}<small>项</small></strong></div>
    </div>
    <div v-if="warningCount" class="assignment-preview__notice">{{ warningCount }} 项拟派发任务有规则提醒，请核对下方标注后确认。</div>

    <div class="assignment-preview__toolbar">
      <el-radio-group v-model="tab" aria-label="查看排班结果">
        <el-radio-button value="assigned">拟派发（{{ rows.assigned.length }}）</el-radio-button>
        <el-radio-button value="unassigned">未分配（{{ rows.unassigned.length }}）</el-radio-button>
      </el-radio-group>
      <el-input v-model="search" clearable :placeholder="tab === 'assigned' ? '搜索课程、志愿者姓名或学号' : '搜索课程、日期或未分配原因'" aria-label="搜索排班计划" />
    </div>
    <p v-if="tab === 'unassigned'" class="assignment-preview__hint">下方列出每项任务的代表原因，不代表所有候选人都因同一条件被排除。</p>
    <div class="assignment-preview__table">
      <el-table :data="visible" row-key="taskId" empty-text="没有符合条件的任务" max-height="44vh">
        <el-table-column label="课程与教学班" min-width="230">
          <template #default="{ row }"><strong class="assignment-preview__primary">{{ row.courseName }}</strong><span class="assignment-preview__secondary">{{ row.teachingClassName }}</span></template>
        </el-table-column>
        <el-table-column label="查课时间与地点" min-width="195">
          <template #default="{ row }"><span class="assignment-preview__primary assignment-preview__date">{{ row.inspectionDate || '日期待核对' }}<span v-if="row.startPeriod"> · {{ formatPeriodText(row.startPeriod, row.endPeriod, row) }}</span></span><span class="assignment-preview__secondary">{{ row.classroom }}</span></template>
        </el-table-column>
        <el-table-column v-if="tab === 'assigned'" label="受派志愿者" min-width="195">
          <template #default="{ row }"><strong class="assignment-preview__primary">{{ row.volunteerName }}</strong><span class="assignment-preview__secondary">{{ [row.studentNo, row.volunteerClass].filter(Boolean).join(' · ') || '档案资料暂不可用' }}</span></template>
        </el-table-column>
        <el-table-column v-if="tab === 'assigned'" label="规则核对" min-width="180">
          <template #default="{ row }"><span v-if="row.warningCodes.length" class="assignment-preview__warning">{{ assignmentWarnings(row.warningCodes) }}</span><span v-else class="assignment-preview__passed">符合排班规则</span></template>
        </el-table-column>
        <el-table-column v-else label="未分配原因" min-width="320">
          <template #default="{ row }"><span class="assignment-preview__reason">{{ row.reason }}</span></template>
        </el-table-column>
      </el-table>
    </div>
    <AppPagination v-if="filtered.length > 50" v-model:current-page="page" :total="filtered.length" />
    <div v-else class="assignment-preview__row-count">共 {{ filtered.length }} 项<template v-if="search">匹配结果</template></div>

    <template #footer>
      <div class="assignment-preview__footer">
        <p v-if="rows.assigned.length">确认后派发 <b>{{ rows.assigned.length }}</b> 项；<template v-if="rows.unassigned.length">未分配的 {{ rows.unassigned.length }} 项保留待处理。</template><template v-else>请核对人员与时间。</template></p>
        <p v-else>暂无可派发任务，请根据原因调整范围或人员配置。</p>
        <div><el-button @click="finish(false)">返回调整</el-button><el-button v-if="rows.assigned.length" type="primary" @click="finish(true)">确认派发 {{ rows.assigned.length }} 项</el-button></div>
      </div>
    </template>
  </el-dialog>
</template>

<style>
.assignment-preview { --el-dialog-padding-primary: 0px; background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius-md); overflow: hidden; }
.assignment-preview .el-dialog__header { margin: 0; padding: 23px 28px 18px; border-bottom: 1px solid var(--line); }
.assignment-preview .el-dialog__headerbtn { top: 14px; right: 12px; }
.assignment-preview .el-dialog__body { padding: 0 28px; color: var(--ink); }
.assignment-preview .el-dialog__footer { padding: 17px 28px; border-top: 1px solid var(--line); background: var(--paper-deep); }
.assignment-preview__header h2 { margin: 0 0 7px; }
.assignment-preview__header p { margin: 0; font-size: var(--text-sm); color: var(--ink-mute); }
.assignment-preview__scope { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px 20px; padding: 16px 0; font-size: var(--text-xs); color: var(--ink-soft); }
.assignment-preview__summary { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--line); background: var(--paper); }
.assignment-preview__summary > div { padding: 15px 22px; border-right: 1px solid var(--line); }
.assignment-preview__summary > div:last-child { border: 0; }
.assignment-preview__summary span { display: block; font-size: var(--text-xs); color: var(--ink-mute); margin-bottom: 7px; }
.assignment-preview__summary strong { display: block; font-size: var(--text-hero); line-height: 1.15; font-variant-numeric: tabular-nums; }
.assignment-preview__summary small { font-size: var(--text-xs); margin-left: 8px; font-weight: 400; color: var(--ink-mute); }
.assignment-preview__ready strong { color: var(--green); }.assignment-preview__pending strong { color: var(--amber); }
.assignment-preview__notice { padding: 10px 13px; background: var(--amber-soft); color: var(--amber); border-left: 3px solid var(--amber); font-size: var(--text-xs); margin-top: 14px; }
.assignment-preview__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 21px 0 13px; }
.assignment-preview__toolbar .el-input { max-width: 265px; }
.assignment-preview__hint { margin: -1px 0 12px; font-size: var(--text-xs); color: var(--ink-mute); }
.assignment-preview__table { border: 1px solid var(--line); }
.assignment-preview__table .el-table { --el-table-header-bg-color: var(--paper-deep); --el-table-bg-color: white; --el-table-tr-bg-color: white; font-size: 13px; }
.assignment-preview__table .el-table td.el-table__cell { padding: 12px 0; }
.assignment-preview__primary { display: block; font-size: 13px; color: var(--ink); overflow-wrap: anywhere; font-weight: 550; }
.assignment-preview__secondary { display: block; font-size: 12px; color: var(--ink-mute); margin-top: 4px; overflow-wrap: anywhere; }
.assignment-preview__date { font-variant-numeric: tabular-nums; font-weight: 400; }
.assignment-preview__warning { color: var(--amber); font-size: 12px; }.assignment-preview__passed { color: var(--green); font-size: 12px; }
.assignment-preview__reason { color: var(--ink-soft); font-size: 13px; line-height: 1.65; }
.assignment-preview__row-count { padding: 12px 0 16px; color: var(--ink-mute); font-size: 12px; }
.assignment-preview__footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.assignment-preview__footer p { margin: 0; color: var(--ink-soft); font-size: 12px; }.assignment-preview__footer b { color: var(--green); }
.assignment-preview__footer > div { display: flex; gap: 9px; }.assignment-preview__footer .el-button + .el-button { margin: 0; }
@media(max-width: 650px) {
  .assignment-preview .el-dialog__header { padding: 20px 16px 15px; }.assignment-preview .el-dialog__body { padding: 0 16px; }
  .assignment-preview .el-dialog__footer { padding: 14px 16px; }.assignment-preview__summary > div { padding: 13px 11px; }
  .assignment-preview__toolbar { flex-wrap: wrap; }.assignment-preview__toolbar .el-input { max-width: none; }
  .assignment-preview__footer > div { width: 100%; justify-content: flex-end; }.assignment-preview__scope { font-size: 11px; }
}
</style>
