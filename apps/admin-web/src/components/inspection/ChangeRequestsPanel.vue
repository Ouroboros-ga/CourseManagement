<script setup lang="ts">
import { ref, watch } from 'vue'
import { useChangeRequests } from '../../composables/useChangeRequests'
import { useSessionStore } from '../../stores/session'
import { type ChangeRequestItem } from '../../api/tasks'
import { formatBeijingTime } from '../../utils/datetime'
import { formatPeriodText } from '../../utils/period'
import AppPagination from '../AppPagination.vue'
import ChangeRequestReviewDialog from './ChangeRequestReviewDialog.vue'
const session = useSessionStore()
const { rows, status, page, total, loading, error, reload } = useChangeRequests()
const selected = ref<ChangeRequestItem | null>(null)
watch(() => [session.currentUser?.id, session.workspaceCollegeId, session.currentSemesterId,
  session.workspace?.authorization_revision], () => { selected.value = null })
const labels = { PENDING: '待处理', APPROVED: '已通过', REJECTED: '已驳回' }
</script>
<template>
  <section class="change-requests">
    <header class="requests-heading"><div><h2>换班申请</h2><p>当前学期的全部周次申请。选择顶班人员后同意，或驳回并保留原受派。</p></div><el-button :loading="loading" @click="reload">刷新</el-button></header>
    <el-radio-group v-model="status" class="status-filter" aria-label="申请状态">
      <el-radio-button value="PENDING">待处理</el-radio-button><el-radio-button value="APPROVED">已通过</el-radio-button>
      <el-radio-button value="REJECTED">已驳回</el-radio-button><el-radio-button value="">全部记录</el-radio-button>
    </el-radio-group>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-else-if="!session.currentSemesterId" title="请先选择学期" type="info" :closable="false" />
    <div v-else v-loading="loading" class="requests-table">
      <el-table :data="rows" empty-text="当前筛选没有换班申请" row-key="id">
        <el-table-column label="申请人" min-width="140"><template #default="{ row }"><strong>{{ row.requester_name || '姓名未登记' }}</strong><p class="secondary">{{ row.requester_student_no || '学号未登记' }}</p></template></el-table-column>
        <el-table-column label="查课任务" min-width="240"><template #default="{ row }"><strong>{{ row.course_name || '未命名课程' }}</strong><p>{{ row.class_name || '班级未指定' }}</p><p class="secondary">{{ row.inspection_date }} · {{ formatPeriodText(row.start_period, row.end_period, row) }} · {{ row.classroom || '教室未指定' }}</p></template></el-table-column>
        <el-table-column label="申请说明" min-width="180"><template #default="{ row }"><p>{{ row.reason || '未填写说明' }}</p><p class="secondary">{{ formatBeijingTime(row.created_at, 'minute') }}</p></template></el-table-column>
        <el-table-column label="处理结果" min-width="210"><template #default="{ row }: { row: ChangeRequestItem }"><el-tag :type="row.status === 'APPROVED' ? 'success' : row.status === 'REJECTED' ? 'info' : 'warning'">{{ labels[row.status] }}</el-tag><p v-if="row.blocked_reason" class="secondary">{{ row.blocked_reason }}</p><template v-if="row.processed_at"><p class="secondary">{{ row.processor_name || '管理员' }} · {{ formatBeijingTime(row.processed_at, 'minute') }}</p><p>{{ row.comment || '未填写处理说明' }}</p></template></template></el-table-column>
        <el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="row.status === 'PENDING'" type="primary" link :disabled="!row.can_process" @click="selected = row">处理申请</el-button><span v-else class="secondary">已处理</span></template></el-table-column>
      </el-table>
      <AppPagination v-model:current-page="page" :total="total" :page-size="50" />
    </div>
    <ChangeRequestReviewDialog :request="selected" @close="selected = null" @processed="reload" />
  </section>
</template>
<style scoped>
.requests-heading { display:flex;justify-content:space-between;gap:16px;align-items:center;margin:18px 0; }
.requests-heading h2 { margin:0 0 8px;font-size:22px; }.requests-heading p { margin:0;color:var(--ink-mute); }
.status-filter { margin-bottom:20px; }.requests-table { border:1px solid var(--line); }
p { margin:5px 0;overflow-wrap:anywhere; }.secondary { color:var(--ink-mute);font-size:12px; }
</style>
