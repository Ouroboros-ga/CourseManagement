<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: 'NOT_STARTED' | 'ASSIGNED' | 'SUBMITTED' | 'REVIEWED' | 'CANCELLED' | string
  deadlineAssessment?: string | null
}>()

const statusMeta = computed(() => {
  switch (props.status) {
    case 'NOT_STARTED':
      return { label: '待执行', cls: 'tag-amber' }
    case 'ASSIGNED':
      return { label: '已排班', cls: 'tag-blue' }
    case 'SUBMITTED':
      return { label: '待审核', cls: 'tag-amber' }
    case 'REVIEWED':
      return { label: '已审核', cls: 'tag-green' }
    case 'CANCELLED':
      return { label: '已取消', cls: 'tag-gray' }
    default:
      return { label: props.status, cls: 'tag-gray' }
  }
})

const isOverdue = computed(() => {
  return props.deadlineAssessment === 'OVERDUE_UNEXECUTED'
})
</script>

<template>
  <span class="tag-group">
    <span class="tag" :class="statusMeta.cls">{{ statusMeta.label }}</span>
    <span v-if="isOverdue" class="tag tag-red" title="截止时刻未执行考核快照">逾期未执行</span>
  </span>
</template>

<style scoped>
.tag-group { display: inline-flex; align-items: center; gap: 6px; }
</style>
