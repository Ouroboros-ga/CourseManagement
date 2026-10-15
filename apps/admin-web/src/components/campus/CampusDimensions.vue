<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { campusDimensions } from '../../api/campusManagement'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { useSessionStore } from '../../stores/session'
import { identityContext } from '../../utils/contextEpoch'
const session = useSessionStore(), school = ref(false)
const canSchool = computed(() => session.hasAnyRole('SUPER_ADMIN') || session.hasPermission('statistics.school.read'))
watch([canSchool, () => session.workspaceCollegeId], () => { if (!canSchool.value) school.value = false; else if (!session.workspaceCollegeId) school.value = true }, { immediate: true })
const enabled = computed(() => !!session.campusRuntime?.business_scoped && !!session.currentSemesterId && ((school.value && canSchool.value) || (!!session.workspaceCollegeId && session.hasPermission('statistics.read'))))
const { data, error } = useWorkspaceRead(() => `${identityContext(session.currentUser)}:${session.workspaceCollegeId}:${session.currentSemesterId}:${school.value}`, () => enabled.value, () => campusDimensions(session.currentSemesterId, school.value && canSchool.value ? undefined : session.workspaceCollegeId))
</script>
<template>
  <el-card v-if="enabled" class="dimensions">
    <h3>检查责任与学生归属口径</h3><el-switch v-if="canSchool" v-model="school" active-text="全校汇总" inactive-text="当前负责学院" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="data"><p>任务 {{ data.task_count }} · 已形成正式结果的任务 {{ data.checked_task_count }} · 检查人次 {{ data.check_person_times }} · 去重学生 {{ data.distinct_student_count }} · 去重学生课次 {{ data.distinct_student_occurrence_count }}</p><p>{{ data.deduplication_note }}</p>
      <el-table :data="data.dimensions"><el-table-column prop="responsible_college_name" label="任务负责学院" /><el-table-column label="学生当时学院"><template #default="{ row }">{{ row.student_college_name || '历史归属未知' }}</template></el-table-column><el-table-column prop="check_person_times" label="检查人次" /><el-table-column prop="distinct_student_count" label="去重学生" /><el-table-column prop="distinct_student_occurrence_count" label="去重学生课次" /><el-table-column label="认定分布（人次）"><template #default="{ row }">正常 {{ row.result_distribution.NORMAL || 0 }} · 请假 {{ row.result_distribution.LEAVE || 0 }} · 迟到 {{ row.result_distribution.LATE || 0 }} · 旷课 {{ row.result_distribution.ABSENT || 0 }}</template></el-table-column></el-table>
    </template>
  </el-card>
</template>
<style scoped>.dimensions { margin: 16px 0; }</style>
