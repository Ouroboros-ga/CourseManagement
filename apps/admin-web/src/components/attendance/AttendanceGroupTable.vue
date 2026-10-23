<script setup lang="ts">
import type { AttendanceGroup, AttendanceGroupBy } from '../../api/attendance'
import { formatPeriodText } from '../../utils/period'
defineProps<{ rows: AttendanceGroup[]; groupBy: AttendanceGroupBy; busy: boolean }>()
defineEmits<{ open: [row: AttendanceGroup] }>()
const rowKey = (row: AttendanceGroup) => row.task_id || row.administrative_class_id || 'unknown'
</script>
<template>
  <el-table :data="rows" v-loading="busy" empty-text="当前范围暂无符合条件的查课结果" :row-key="rowKey">
    <el-table-column v-if="groupBy === 'task'" label="课程与教学班" min-width="240"><template #default="{ row }"><strong>{{ row.course_name || '课程资料待核对' }}</strong><div class="muted">{{ row.teaching_class_name || '教学班待核对' }}</div></template></el-table-column>
    <el-table-column v-else label="查课时行政班" min-width="200"><template #default="{ row }"><strong>{{ row.class_name }}</strong><div class="muted">{{ row.task_count }} 次查课</div></template></el-table-column>
    <el-table-column v-if="groupBy === 'task'" label="时间与地点" min-width="200"><template #default="{ row }">{{ row.inspection_date }} · {{ formatPeriodText(row.start_period, row.end_period, row) }}<div class="muted">{{ row.classroom || '地点未填写' }}</div></template></el-table-column>
    <el-table-column v-if="groupBy === 'task'" label="查课志愿者" min-width="120"><template #default="{ row }">{{ row.volunteer_name || '历史执行人待核对' }}</template></el-table-column>
    <el-table-column label="考勤记录" width="100"><template #default="{ row }">{{ row.record_count }} 条</template></el-table-column>
    <el-table-column label="当前结果" min-width="260"><template #default="{ row }"><div class="results"><span>正常 <b>{{ row.normal_count }}</b></span><span :class="{ late: row.late_count }">迟到 <b>{{ row.late_count }}</b></span><span :class="{ absent: row.absent_count }">旷课 <b>{{ row.absent_count }}</b></span><span>请假 <b>{{ row.leave_count }}</b></span></div></template></el-table-column>
    <el-table-column label="操作" width="120"><template #default="{ row }"><el-button link @click="$emit('open', row)">{{ groupBy === 'task' ? '查看名单与照片' : '查看各次查课' }}</el-button></template></el-table-column>
  </el-table>
</template>
<style scoped>.muted { color:var(--ink-mute);font-size:12px;margin-top:5px; }.results { display:flex;gap:8px 16px;flex-wrap:wrap;font-size:12px;color:var(--ink-mute); }.results b { font-variant-numeric:tabular-nums; }.results .late { color:var(--amber); }.results .absent { color:var(--red); }</style>
