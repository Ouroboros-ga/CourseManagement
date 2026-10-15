<script setup lang="ts">
import type { CollegePeriodTime } from '../../api/collegeTime'
const props = defineProps<{ modelValue: CollegePeriodTime[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: CollegePeriodTime[]] }>()
function update(index: number, field: keyof CollegePeriodTime, value: string | number) {
  emit('update:modelValue', props.modelValue.map((row, i) => i === index ? { ...row, [field]: value } : row))
}
function add() {
  const no = Math.max(0, ...props.modelValue.map(row => row.period_no)) + 1
  if (no <= 60) emit('update:modelValue', [...props.modelValue, { period_no: no, slot_id: `period-${no}`, name: '', start_time: '19:00', end_time: '19:45' }])
}
</script>
<template>
  <el-table :data="modelValue">
    <el-table-column label="节次号" width="150"><template #default="{ row, $index }"><el-input-number :model-value="row.period_no" :disabled="disabled" :min="1" :max="60" @update:model-value="update($index, 'period_no', $event ?? 1)" /></template></el-table-column>
    <el-table-column label="稳定标识"><template #default="{ row, $index }"><el-input :model-value="row.slot_id" :disabled="disabled" @update:model-value="update($index, 'slot_id', $event)" /></template></el-table-column>
    <el-table-column label="名称"><template #default="{ row, $index }"><el-input :model-value="row.name" :disabled="disabled" @update:model-value="update($index, 'name', $event)" /></template></el-table-column>
    <el-table-column label="开始"><template #default="{ row, $index }"><el-time-picker :model-value="row.start_time" :disabled="disabled" format="HH:mm" value-format="HH:mm" :clearable="false" @update:model-value="update($index, 'start_time', $event)" /></template></el-table-column>
    <el-table-column label="结束"><template #default="{ row, $index }"><el-time-picker :model-value="row.end_time" :disabled="disabled" format="HH:mm" value-format="HH:mm" :clearable="false" @update:model-value="update($index, 'end_time', $event)" /></template></el-table-column>
    <el-table-column label="操作" width="90"><template #default="{ $index }"><el-button :disabled="disabled || modelValue.length <= 1" @click="emit('update:modelValue', modelValue.filter((_, i) => i !== $index))">移除</el-button></template></el-table-column>
  </el-table>
  <el-button :disabled="disabled || modelValue.length >= 60" @click="add">添加节次</el-button>
</template>
