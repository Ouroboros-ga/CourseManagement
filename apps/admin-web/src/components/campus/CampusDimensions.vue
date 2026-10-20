<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { computed, ref, watch } from 'vue'
import { campusDimensions, type CampusDimension, type CampusDimensions } from '../../api/campusManagement'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { useSessionStore } from '../../stores/session'
import { identityContext } from '../../utils/contextEpoch'
const session = useSessionStore(), school = ref(false)
const canSchool = computed(() => session.hasAnyRole('SUPER_ADMIN') || session.hasPermission('statistics.school.read'))
watch([canSchool, () => session.workspaceCollegeId], () => { if (!canSchool.value) school.value = false; else if (!session.workspaceCollegeId) school.value = true }, { immediate: true })
const enabled = computed(() => !!session.campusRuntime?.business_scoped && !!session.currentSemesterId && ((school.value && canSchool.value) || (!!session.workspaceCollegeId && session.hasPermission('statistics.read'))))
const { data, error } = useWorkspaceRead(() => `${identityContext(session.currentUser)}:${session.workspaceCollegeId}:${session.currentSemesterId}:${school.value}`, () => enabled.value, () => campusDimensions(session.currentSemesterId, school.value && canSchool.value ? undefined : session.workspaceCollegeId))

type AxisView = 'owner' | 'student' | 'cross'
const view = ref<AxisView>(session.workspaceCollegeId ? 'owner' : 'cross')
watch(view, v => { if (v !== 'cross') school.value = school.value })
// 单轴视图把交叉行按选定维度合并；只有“查课记录 / 任务 / 结果分布”可直接相加，
// 去重类指标（涉及学生 / 涉及课次）跨组合并会重复计数，只在双轴交叉视图给出精确值。
function mergeAxis(d: CampusDimensions, axis: 'responsible' | 'student'): CampusDimension[] {
  const keyOf = (row: CampusDimension) => axis === 'responsible'
    ? (row.responsible_college_name || '任务负责学院未知')
    : (row.student_college_name || '历史归属未知')
  const buckets = new Map<string, CampusDimension>()
  for (const row of d.dimensions) {
    const key = keyOf(row)
    const merged = buckets.get(key) ?? {
      responsible_college_name: axis === 'responsible' ? key : null,
      student_college_name: axis === 'student' ? key : null,
      checked_task_count: 0, check_person_times: 0, distinct_student_count: 0,
      distinct_student_occurrence_count: 0, result_distribution: {}
    }
    merged.checked_task_count += row.checked_task_count
    merged.check_person_times += row.check_person_times
    for (const [type, count] of Object.entries(row.result_distribution)) merged.result_distribution[type] = (merged.result_distribution[type] ?? 0) + count
    buckets.set(key, merged)
  }
  return [...buckets.values()].sort((a, b) => (axis === 'responsible' ? (a.responsible_college_name ?? '') : (a.student_college_name ?? '')).localeCompare(axis === 'responsible' ? (b.responsible_college_name ?? '') : (b.student_college_name ?? '')))
}
const rows = computed(() => {
  if (!data.value) return []
  return view.value === 'cross' ? data.value.dimensions
    : view.value === 'owner' ? mergeAxis(data.value, 'responsible')
    : mergeAxis(data.value, 'student')
})
const distribution = (row: CampusDimension) => `正常 ${row.result_distribution.NORMAL || 0} · 请假 ${row.result_distribution.LEAVE || 0} · 迟到 ${row.result_distribution.LATE || 0} · 旷课 ${row.result_distribution.ABSENT || 0}`
</script>
<template>
  <el-card v-if="enabled" class="dimensions">
    <header class="head"><h3>查课数据怎么汇总</h3><el-switch v-if="canSchool" v-model="school" active-text="全校汇总" inactive-text="当前负责学院" /></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="data">
      <el-radio-group v-model="view" size="small" class="views">
        <el-radio-button value="owner">按任务负责学院</el-radio-button>
        <el-radio-button value="student">按学生学籍学院</el-radio-button>
        <el-radio-button value="cross">双轴交叉</el-radio-button>
      </el-radio-group>
      <p class="metrics">任务 {{ data.task_count }} · 已形成正式结果的任务 {{ data.checked_task_count }} · 查课记录 {{ data.check_person_times }}</p>
      <PaginatedTable v-if="view === 'cross'" :data="rows">
        <el-table-column prop="responsible_college_name" label="任务负责学院" min-width="160" show-overflow-tooltip />
        <el-table-column min-width="160" show-overflow-tooltip>
          <template #header>
            <span class="axis-head">学生学籍学院<el-tooltip content="查课时学生学籍所在的学院。" placement="top"><span class="hint">?</span></el-tooltip></span>
          </template>
          <template #default="{ row }">{{ row.student_college_name || '历史归属未知' }}</template>
        </el-table-column>
        <el-table-column prop="check_person_times" label="查课记录" />
        <el-table-column prop="distinct_student_count" label="涉及学生" />
        <el-table-column prop="distinct_student_occurrence_count" label="涉及课次" />
        <el-table-column label="结果分布（条数）"><template #default="{ row }">{{ distribution(row) }}</template></el-table-column>
      </PaginatedTable>
      <PaginatedTable v-else-if="view === 'owner'" :data="rows">
        <el-table-column prop="responsible_college_name" label="任务负责学院" min-width="180" show-overflow-tooltip />
        <el-table-column prop="checked_task_count" label="已有结果的任务" />
        <el-table-column prop="check_person_times" label="查课记录" />
        <el-table-column label="结果分布（条数）"><template #default="{ row }">{{ distribution(row) }}</template></el-table-column>
      </PaginatedTable>
      <PaginatedTable v-else :data="rows">
        <el-table-column min-width="180" show-overflow-tooltip>
          <template #header>
            <span class="axis-head">学生学籍学院<el-tooltip content="查课时学生学籍所在的学院。" placement="top"><span class="hint">?</span></el-tooltip></span>
          </template>
          <template #default="{ row }">{{ row.student_college_name || '历史归属未知' }}</template>
        </el-table-column>
        <el-table-column prop="check_person_times" label="查课记录" />
        <el-table-column label="结果分布（条数）"><template #default="{ row }">{{ distribution(row) }}</template></el-table-column>
      </PaginatedTable>
      <p v-if="view !== 'cross'" class="baseline">涉及学生 / 涉及课次等去重口径只在“双轴交叉”视图给出，避免跨行合并时重复计数。</p>
      <el-collapse class="how">
        <el-collapse-item title="这次统计怎么算？">
          <p class="example">例如：李明随“计科2601”班被查上午第3节，同一天他修的“高数A”教学班也被查了同一节——同一节课只记 <b>1 次</b>；关联不上课次的检查会单独列一行，绝不含混合并。</p>
          <p>两种角度分列：<b>任务负责学院</b> = 这次查课是哪个学院安排的（责任方）；<b>学生学籍学院</b> = 被查学生当时属于哪个学院。学生后来转学院，历史记录不变。</p>
          <p>{{ data.deduplication_note }}</p>
        </el-collapse-item>
      </el-collapse>
    </template>
  </el-card>
</template>
<style scoped>
.dimensions { margin: 16px 0; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.views { margin: 4px 0 12px; }
.metrics { color: var(--el-text-color-regular); margin: 0 0 10px; }
.example { color: var(--el-text-color-secondary); }
.baseline { font-size: 12px; color: var(--el-text-color-secondary); margin: 8px 0 0; }
.how { margin-top: 10px; border-top: none; }
.how :deep(.el-collapse-item__header) { color: var(--el-text-color-secondary); font-size: 13px; }
.hint { display: inline-block; margin-left: 4px; width: 14px; height: 14px; line-height: 14px; border-radius: 50%; background: var(--el-fill-color); color: var(--el-text-color-secondary); font-size: 11px; text-align: center; cursor: help; }
</style>
