<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, watch } from 'vue'
import { listSemesters, type SemesterItem } from '../../api/academic'
import type { VolunteerGroup } from '../../api/campus'
import GroupMembers from './GroupMembers.vue'
import GroupSampling from './GroupSampling.vue'

const props = defineProps<{ collegeId: string; groups: VolunteerGroup[]; capabilities: string[]; isSuper: boolean }>()
const semesterId = shallowRef('')
const groupId = shallowRef('')
const semesters = shallowRef<SemesterItem[]>([])
const error = shallowRef('')
const group = computed(() => props.groups.find(row => row.id === groupId.value))
const canManage = computed(() => props.capabilities.includes('volunteer.member.manage'))
const canGenerate = computed(() => props.capabilities.includes('inspection.generate'))
const canAssign = computed(() => props.capabilities.includes('assignment.manage'))
const canSample = computed(() => group.value?.status === 'ACTIVE' && (group.value?.config_version || 0) > 0)
const semesterName = computed(() => semesters.value.find(row => row.id === semesterId.value)?.name || '当前学期')
let disposed = false
onUnmounted(() => { disposed = true })
onMounted(async () => {
  try {
    const result = await listSemesters('ACTIVE')
    if (disposed) return
    semesters.value = result.items
    semesterId.value = result.items[0]?.id || ''
  } catch (caught) { if (!disposed) error.value = caught instanceof Error ? caught.message : '学期读取失败' }
})
watch(() => [props.collegeId, props.groups] as const, () => {
  if (!props.groups.some(row => row.id === groupId.value)) groupId.value = props.groups[0]?.id || ''
}, { immediate: true })
</script>

<template>
  <section class="group-operations">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="selectors">
      <el-select v-model="semesterId" placeholder="选择学期" aria-label="组织业务学期">
        <el-option v-for="row in semesters" :key="row.id" :value="row.id" :label="row.name" />
      </el-select>
      <el-select v-model="groupId" placeholder="选择志愿者组" aria-label="当前志愿者组">
        <el-option v-for="row in groups" :key="row.id" :value="row.id" :label="row.name" />
      </el-select>
    </div>
    <el-empty v-if="!groupId || !semesterId" description="请先选择学期并创建志愿者组" />
    <el-tabs v-else>
      <el-tab-pane label="成员与支援">
        <GroupMembers :college-id="collegeId" :group-id="groupId" :semester-id="semesterId"
          :semester-name="semesterName" :can-manage="canManage" :is-super="isSuper" />
      </el-tab-pane>
      <el-tab-pane v-if="canGenerate || canAssign" label="范围抽查与排班" lazy>
        <GroupSampling v-if="canSample" :college-id="collegeId" :group-id="groupId" :semester-id="semesterId"
          :can-generate="canGenerate" :can-assign="canAssign" />
        <el-alert v-else title="请先发布组范围与规则，并启用该组，再进行抽查和排班。" type="info" :closable="false" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.group-operations { display: grid; gap: 16px; }
.selectors { display: flex; gap: 12px; flex-wrap: wrap; }
</style>
