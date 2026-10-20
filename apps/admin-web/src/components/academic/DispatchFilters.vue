<script setup lang="ts">
import type { CourseType, VolunteerGroup } from '../../api/campus'
defineProps<{ types: CourseType[]; groups: VolunteerGroup[]; courseTypeId: string; groupId: string; organizationMode: boolean; error: string; compact?: boolean }>()
const emit = defineEmits<{ 'update:courseTypeId': [value: string]; 'update:groupId': [value: string] }>()
</script>
<template>
  <section class="dispatch-filters" :class="{ compact }" aria-label="课程类型与执行组织">
    <label>课程类型
      <el-select :model-value="courseTypeId" clearable placeholder="全部课程类型" aria-label="查课课程类型" @update:model-value="(value: string) => emit('update:courseTypeId', value || '')">
        <el-option v-for="kind in types" :key="kind.id" :label="kind.name + (kind.status === 'ACTIVE' ? '' : '（停用）')" :value="kind.id" />
      </el-select>
    </label>
    <label>执行志愿者组
      <el-select :model-value="groupId" clearable :disabled="!organizationMode" placeholder="选择本次任务的执行组" aria-label="手选课次执行组" @update:model-value="(value: string) => emit('update:groupId', value || '')">
        <el-option v-for="group in groups" :key="group.id" :value="group.id"
          :label="group.name + (group.status !== 'ACTIVE' ? '（未启用）' : !group.config_version ? '（未发布范围）' : '')"
          :disabled="group.status !== 'ACTIVE' || !group.config_version || (!!courseTypeId && !group.configuration?.course_type_ids.includes(courseTypeId))" />
      </el-select>
    </label>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="!compact">
      <p v-if="!organizationMode">组织排班尚未启用。可先在“志愿者组织”维护资格、组成员及范围；系统不会忽略执行组并改用全院志愿者池。</p>
      <p v-else-if="!groupId">请选择执行组。系统先按该组已发布的类型、班级范围筛选，再抽查或排班。</p>
    </template>
  </section>
</template>
<style scoped>
.dispatch-filters { display:flex; flex-wrap:wrap; gap:12px 24px; padding:16px; border:1px solid var(--line); margin-bottom:16px; }
.dispatch-filters.compact { flex-wrap:nowrap; align-items:center; flex:1; min-width:0; padding:0; border:none; margin-bottom:0; }
.dispatch-filters.compact label { gap:8px; font-size:13px; white-space:nowrap; }
.dispatch-filters.compact .el-select { width:190px; }
.dispatch-filters.compact p { flex-basis:auto; font-size:12px; }
.dispatch-filters label { display:flex; gap:10px; align-items:center; font-size:14px; }
.dispatch-filters .el-select { width:240px; }
.dispatch-filters p { flex-basis:100%; margin:0; color:var(--ink-mute); font-size:13px; }
.dispatch-filters [role=alert] { color:var(--el-color-danger); }
</style>
