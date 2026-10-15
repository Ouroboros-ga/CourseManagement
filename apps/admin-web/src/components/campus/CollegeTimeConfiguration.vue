<script setup lang="ts">
import TimeProfiles from './TimeProfiles.vue'
import SchoolTimeDefaults from './SchoolTimeDefaults.vue'
import type { CollegePeriodTime } from '../../api/collegeTime'
import { computed, shallowRef, watch } from 'vue'
import { useCollegeTimeConfiguration } from '../../composables/useCollegeTimeConfiguration'
import { useSessionStore } from '../../stores/session'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'

const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()
const draftRoot = shallowRef<HTMLElement | null>(null)
const state = useCollegeTimeConfiguration(() => props.collegeId)
const { semesterId, form, previewResult, versions, busy, error, message, preview, publish } = state
watch(message, value => { if (value) markWorkspaceSaved(draftRoot.value) })
const formMethods = computed(() => form.value)
function fillTemplatePeriods(periods: CollegePeriodTime[]) { form.value = { ...form.value, periods } }
const hasRetainedTasks = computed(() => (previewResult.value?.retained_future_task_ids.length || 0) > 0)
const mappingError = shallowRef('')
const mappingText = computed(() => Object.entries(form.value.grid_slot_mapping || {})
  .sort(([a], [b]) => Number(a) - Number(b)).map(([raw, period]) => `${raw}=${period}`).join(', '))
function updateMapping(value: string) {
  const mapping: Record<string, number> = {}
  for (const segment of value.split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean)) {
    const match = /^(\d{1,2})\s*=\s*(\d{1,2})$/.exec(segment)
    if (!match || Object.prototype.hasOwnProperty.call(mapping, match[1]!)) {
      mappingError.value = '每项填写 教务小节=本院节次，以逗号分隔，教务小节不能重复'
      return
    }
    mapping[match[1]!] = Number(match[2])
  }
  mappingError.value = ''
  form.value = { ...form.value, grid_slot_mapping: mapping }
}

watch(() => session.currentSemesterId, value => { semesterId.value = value }, { immediate: true })

function updateEffectiveFrom(value: string) {
  form.value = { ...form.value, effective_from: value || '' }
}
function updatePeriod(index: number, field: 'period_no' | 'start_time' | 'end_time' | 'name', value: string | number) {
  const periods = form.value.periods.map((period, row) => row === index
    ? { ...period, [field]: field === 'period_no' ? Number(value) : String(value) }
    : period)
  form.value = { ...form.value, periods }
}
function addPeriod() {
  if (form.value.periods.length >= 60) return
  const used = new Set(form.value.periods.map(period => period.period_no))
  let periodNo = 1
  while (used.has(periodNo) && periodNo <= 60) periodNo += 1
  if (periodNo <= 60) form.value = {
    ...form.value,
    periods: [...form.value.periods, { period_no: periodNo, start_time: '08:00', end_time: '08:45' }]
  }
}
function removePeriod(index: number) {
  if (form.value.periods.length <= 1) return
  form.value = { ...form.value, periods: form.value.periods.filter((_, row) => row !== index) }
}
function addCalendar() {
  form.value = {
    ...form.value,
    calendar: [...form.value.calendar, { date: '', override_type: 'STOP' }]
  }
}
function updateCalendar(index: number, field: 'date' | 'override_type' | 'source_teaching_week' | 'source_teaching_weekday', value: string | number) {
  const calendar = form.value.calendar.map((item, row) => {
    if (row !== index) return item
    const next = { ...item, [field]: field.startsWith('source_') ? (value === '' ? null : Number(value)) : value }
    if (field === 'override_type' && value === 'STOP') {
      next.source_teaching_week = null
      next.source_teaching_weekday = null
    }
    return next
  })
  form.value = { ...form.value, calendar }
}
function removeCalendar(index: number) {
  form.value = { ...form.value, calendar: form.value.calendar.filter((_, row) => row !== index) }
}
function updateConfirmation(value: boolean | string | number) {
  form.value = { ...form.value, confirm_existing_tasks: Boolean(value) }
}
</script>

<template>
  <section ref="draftRoot" class="college-time" data-unsaved-form>
    <p>本院作息说明：新生成课次使用生效版本；已有任务保留原作息快照。</p>
    <SchoolTimeDefaults :college-id="collegeId" :semester-id="semesterId" :configuration="formMethods" @changed="state.loadVersions" @fill-periods="fillTemplatePeriods" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />

    <div class="field-row">
      <label for="college-time-semester">学期</label>
      <span>业务学期：{{ session.currentSemesterName }}</span>
      <label for="college-time-effective-date">生效日期</label>
      <el-date-picker
        id="college-time-effective-date" :model-value="formMethods.effective_from" type="date"
        value-format="YYYY-MM-DD" placeholder="选择生效日期" @update:model-value="updateEffectiveFrom"
      />
    </div>

    <h3>节次时间</h3>
    <el-table :data="formMethods.periods" row-key="period_no">
      <el-table-column label="节次" width="130">
        <template #default="scope">
          <el-input-number :model-value="scope.row.period_no" :min="1" :max="60" @update:model-value="updatePeriod(scope.$index, 'period_no', $event ?? 1)" />
        </template>
      </el-table-column>
      <el-table-column label="时段名称">
        <template #default="scope"><el-input :model-value="scope.row.name || ''" @update:model-value="updatePeriod(scope.$index, 'name', $event)" /></template>
      </el-table-column>
      <el-table-column label="开始时间">
        <template #default="scope">
          <el-time-select :model-value="scope.row.start_time" start="00:00" step="00:05" end="23:55" @update:model-value="updatePeriod(scope.$index, 'start_time', $event || '')" />
        </template>
      </el-table-column>
      <el-table-column label="结束时间">
        <template #default="scope">
          <el-time-select :model-value="scope.row.end_time" start="00:00" step="00:05" end="23:55" @update:model-value="updatePeriod(scope.$index, 'end_time', $event || '')" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="scope"><el-button text type="danger" :disabled="formMethods.periods.length <= 1" @click="removePeriod(scope.$index)">删除</el-button></template>
      </el-table-column>
    </el-table>
    <el-button class="section-action" :disabled="formMethods.periods.length >= 60" @click="addPeriod">增加节次</el-button>

    <h3>教务网格课表小节映射</h3>
    <p>例如本院节次 1 为早自习、节次 2 为第一大节时，填写 1=2, 2=2。留空时不能导入网格课表。</p>
    <el-input :model-value="mappingText" placeholder="1=2, 2=2, 3=3, 4=3" @change="updateMapping" />
    <el-alert v-if="mappingError" :title="mappingError" type="error" :closable="false" />

    <h3>校历覆盖</h3>
    <el-table :data="formMethods.calendar">
      <el-table-column label="日期">
        <template #default="scope">
          <el-date-picker :model-value="scope.row.date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" @update:model-value="updateCalendar(scope.$index, 'date', $event || '')" />
        </template>
      </el-table-column>
      <el-table-column label="类型" width="150">
        <template #default="scope">
          <el-select :model-value="scope.row.override_type" @update:model-value="updateCalendar(scope.$index, 'override_type', $event || 'STOP')">
            <el-option label="停课" value="STOP" /><el-option label="补课" value="MAKEUP" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="来源教学周">
        <template #default="scope">
          <el-input-number v-if="scope.row.override_type === 'MAKEUP'" :model-value="scope.row.source_teaching_week ?? undefined" :min="1" :max="60" placeholder="可选" @update:model-value="updateCalendar(scope.$index, 'source_teaching_week', $event ?? '')" />
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="来源星期">
        <template #default="scope">
          <el-select v-if="scope.row.override_type === 'MAKEUP'" :model-value="scope.row.source_teaching_weekday ?? undefined" placeholder="选择星期" @update:model-value="updateCalendar(scope.$index, 'source_teaching_weekday', $event ?? '')">
            <el-option v-for="day in 7" :key="day" :label="`星期${day}`" :value="day" />
          </el-select>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="scope"><el-button text type="danger" @click="removeCalendar(scope.$index)">删除</el-button></template>
      </el-table-column>
    </el-table>
    <el-button class="section-action" @click="addCalendar">增加校历日期</el-button>

    <div class="actions">
      <el-button :disabled="!semesterId || !formMethods.effective_from || busy || !!mappingError" :loading="busy" @click="preview">预览作息</el-button>
    </div>
    <div v-if="previewResult" class="preview-result">
      <p>预览为第 {{ previewResult.next_version }} 版；{{ previewResult.retained_future_task_ids.length }} 个未来任务保留原作息快照。</p>
      <el-checkbox
        v-if="hasRetainedTasks" :model-value="formMethods.confirm_existing_tasks"
        @update:model-value="updateConfirmation"
      >确认未来已有任务保留原作息快照</el-checkbox>
      <el-button type="primary" :disabled="busy || !!mappingError || (hasRetainedTasks && !formMethods.confirm_existing_tasks)" :loading="busy" @click="publish">确认发布</el-button>
    </div>

    <h3>历史作息版本</h3>
    <el-empty v-if="!versions.length && !busy" description="暂无作息版本" />
    <el-table v-else :data="versions" row-key="id" v-loading="busy">
      <el-table-column prop="version" label="版本" width="100" />
      <el-table-column prop="effective_from" label="生效日期" width="140" />
      <el-table-column label="节次数">
        <template #default="scope">{{ scope.row.configuration.periods.length }}</template>
      </el-table-column>
      <el-table-column label="校历覆盖">
        <template #default="scope">{{ scope.row.configuration.calendar.length }}</template>
      </el-table-column>
      <el-table-column prop="id" label="版本 ID" />
    </el-table>
    <TimeProfiles v-if="semesterId" :key="`${collegeId}:${semesterId}`" :college-id="collegeId" :semester-id="semesterId" :default-configuration="form" />
  </section>
</template>

<style scoped>
.college-time { display: grid; gap: 12px; }
.field-row, .actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.section-action { justify-self: start; }
.preview-result { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
</style>
