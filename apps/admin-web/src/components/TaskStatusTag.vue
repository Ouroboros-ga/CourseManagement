<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: 'NOT_STARTED' | 'ASSIGNED' | 'SUBMITTED' | 'REVIEWED' | 'CANCELLED' | 'OVERDUE' | string
  deadlineAssessment?: any
}>()

const statusMeta = computed(() => {
  switch (props.status) {
    case 'NOT_STARTED':
    case '待执行':
      return { label: '待执行', cls: 'tag-blue' }
    case 'ASSIGNED':
    case '已排班':
      return { label: '已排班', cls: 'tag-blue' }
    case 'SUBMITTED':
    case '待审核':
      return { label: '待审核', cls: 'tag-amber' }
    case 'REVIEWED':
    case '已完成':
    case '已审核':
      return { label: '已完成', cls: 'tag-green' }
    case 'OVERDUE':
    case '已逾期':
      return { label: '已逾期', cls: 'tag-red' }
    case 'CANCELLED':
    case '已取消':
      return { label: '已取消', cls: 'tag-gray' }
    default:
      return { label: props.status || '未知', cls: 'tag-gray' }
  }
})

const isOverdueSnapshot = computed(() => {
  // 当前态已经是“已逾期”时，主标签已明确标红，无需重复显示“逾期未执行”副标
  if (statusMeta.value.label === '已逾期') return false
  if (!props.deadlineAssessment) return false
  if (typeof props.deadlineAssessment === 'string') {
    return props.deadlineAssessment === 'OVERDUE_UNEXECUTED'
  }
  return props.deadlineAssessment.result === 'OVERDUE_UNEXECUTED'
})
</script>

<template>
  <span class="tag-group">
    <span class="tag" :class="statusMeta.cls">{{ statusMeta.label }}</span>
    <span v-if="isOverdueSnapshot" class="tag tag-red" title="截止时刻未执行考核快照">逾期未执行</span>
  </span>
</template>

<style scoped>
.tag-group { display: inline-flex; align-items: center; gap: 6px; }
</style>
