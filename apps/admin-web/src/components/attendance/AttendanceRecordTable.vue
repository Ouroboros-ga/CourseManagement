<script setup lang="ts">
import { attendanceLabels, type AttendanceRecord } from '../../api/attendance'
import { formatPeriodText } from '../../utils/period'
defineProps<{ rows: AttendanceRecord[]; busy?: boolean; maxHeight?: string }>()
defineEmits<{ open: [row: AttendanceRecord] }>()
</script>
<template>
  <el-table :data="rows" :max-height="maxHeight" v-loading="busy" empty-text="当前范围暂无符合条件的考勤记录">
    <el-table-column label="学生" min-width="170"><template #default="{ row }"><strong>{{ row.name || '姓名待核对' }}</strong><div class="muted">{{ row.student_no || '学号待核对' }}</div></template></el-table-column>
    <el-table-column label="查课时行政班" min-width="160"><template #default="{ row }">{{ row.administrative_class_name || '历史班级待核对' }}</template></el-table-column>
    <el-table-column label="课程与教学班" min-width="200"><template #default="{ row }">{{ row.task?.course_name_snapshot || '课程资料待核对' }}<div class="muted">{{ row.task?.class_name_snapshot }}</div></template></el-table-column>
    <el-table-column label="查课时间" min-width="180"><template #default="{ row }">{{ row.task?.inspection_date }}<div class="muted">{{ formatPeriodText(row.task?.start_period, row.task?.end_period) }}</div></template></el-table-column>
    <el-table-column label="当前认定" min-width="100"><template #default="{ row }"><span :class="`attendance-${row.effective_type.toLowerCase()}`">{{ attendanceLabels[row.effective_type as keyof typeof attendanceLabels] }}</span></template></el-table-column>
    <el-table-column label="操作" width="130"><template #default="{ row }"><el-button link @click="$emit('open', row)">记录与照片</el-button></template></el-table-column>
  </el-table>
</template>
<style scoped>.muted { color: var(--ink-mute); font-size: 12px; margin-top: 5px; }.attendance-normal { color: var(--green); }.attendance-late { color: var(--amber); }.attendance-absent { color: var(--red); }</style>
