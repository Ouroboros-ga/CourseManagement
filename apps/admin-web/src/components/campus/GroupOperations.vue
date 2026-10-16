<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useSessionStore } from '../../stores/session'
import type { VolunteerGroup } from '../../api/campus'
import GroupMembers from './GroupMembers.vue'
import GroupSampling from './GroupSampling.vue'

const props = withDefaults(defineProps<{ collegeId: string; groups: VolunteerGroup[]; capabilities: string[]; isSuper: boolean; mode?: 'all' | 'members' | 'sampling' }>(), { mode: 'all' })
const session = useSessionStore()
const semesterId = computed(() => session.currentSemesterId)
const groupId = shallowRef('')
const group = computed(() => props.groups.find(row => row.id === groupId.value))
const canManage = computed(() => props.capabilities.includes('volunteer.member.manage'))
const canGenerate = computed(() => props.capabilities.includes('inspection.generate'))
const canAssign = computed(() => props.capabilities.includes('assignment.manage'))
const canSample = computed(() => group.value?.status === 'ACTIVE' && (group.value?.config_version || 0) > 0)
const semesterName = computed(() => session.currentSemesterName)
watch(() => [props.collegeId, props.groups] as const, () => {
  if (!props.groups.some(row => row.id === groupId.value)) groupId.value = props.groups[0]?.id || ''
}, { immediate: true })
</script>

<template>
  <section class="group-operations">
    <div class="selectors">
      <span>业务学期：{{ semesterName }}</span>
      <el-select v-model="groupId" placeholder="选择志愿者组" aria-label="当前志愿者组">
        <el-option v-for="row in groups" :key="row.id" :value="row.id" :label="row.name" />
      </el-select>
    </div>
    <el-empty v-if="!groupId || !semesterId" description="请先选择学期并创建志愿者组" />
    <el-tabs v-else class="tabs-embed">
      <el-tab-pane v-if="mode !== 'sampling'" label="成员、支援与请假">
        <GroupMembers :college-id="collegeId" :group-id="groupId" :semester-id="semesterId"
          :semester-name="semesterName" :can-manage="canManage" :is-super="isSuper" />
      </el-tab-pane>
      <el-tab-pane v-if="mode !== 'members' && (canGenerate || canAssign)" label="范围抽查与排班" lazy>
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
