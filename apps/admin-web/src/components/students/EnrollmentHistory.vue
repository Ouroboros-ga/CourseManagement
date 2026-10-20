<script setup lang="ts">
import AppPagination from '../../components/AppPagination.vue'
import { computed, ref, watch } from 'vue'
import { useSessionStore } from '../../stores/session'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { request } from '../../api/http'
interface EnrollmentRow {
  id: string; student_no: string; name: string; enrollment_status: string; as_of: string
  enrollment_snapshot: { class_name?: string; college_name?: string; grade_year?: number } | null
}
interface HistoryPage { items: EnrollmentRow[]; total: number }
const session = useSessionStore()
const day = ref(new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date()))
const keyword = ref(''), query = ref(''), page = ref(1)
const enabled = computed(() => !!session.campusRuntime?.academic_scoped && !!session.workspaceCollegeId && !!day.value)
const { data, busy, error, load } = useWorkspaceRead(
  () => JSON.stringify([session.currentUser?.id, session.workspaceCollegeId, session.workspace?.authorization_revision, day.value, query.value, page.value]),
  () => enabled.value,
  () => {
    const params = new URLSearchParams({ as_of: day.value, keyword: query.value, page: String(page.value), page_size: '20' })
    return request<HistoryPage>(`/api/v1/colleges/${encodeURIComponent(session.workspaceCollegeId)}/academic/students?${params}`)
  })
watch(day, () => { page.value = 1 })
function search() { query.value = keyword.value.trim(); page.value = 1; void load() }
const statusLabel: Record<string, string> = { ENROLLED: '在籍', SUSPENDED: '休学', GRADUATED: '毕业', WITHDRAWN: '退学' }
</script>
<template>
  <section aria-label="按日期查看学籍" v-loading="busy">
    <el-alert title="按指定日期的学籍事实查看，当日归属本院的人员才显示。缺少该日期事实的人员不会用当前档案补造历史；姓名、学号为当前身份标识，班级与学院为当时快照。此页面只读，不改变任务考勤。" type="info" :closable="false" />
    <el-alert v-if="!session.campusRuntime?.academic_scoped" title="学院学籍查询尚未启用；当前档案仍可从前一页查看。" type="warning" :closable="false" />
    <div class="filters">
      <el-date-picker v-model="day" type="date" value-format="YYYY-MM-DD" :clearable="false" aria-label="学籍查询日期" />
      <el-input v-model="keyword" placeholder="姓名或学号" clearable @keyup.enter="search" />
      <el-button :disabled="!enabled" @click="search">查询</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="data?.items || []" empty-text="该日期没有可见的已确认学籍资料">
      <el-table-column prop="student_no" label="学号（当前标识）" min-width="150" />
      <el-table-column prop="name" label="姓名（当前标识）" min-width="140" />
      <el-table-column label="当时学院" min-width="150"><template #default="{ row }">{{ row.enrollment_snapshot?.college_name || '未记录' }}</template></el-table-column>
      <el-table-column label="当时行政班" min-width="150"><template #default="{ row }">{{ row.enrollment_snapshot?.class_name || '未记录' }}</template></el-table-column>
      <el-table-column label="当时学籍状态" min-width="120"><template #default="{ row }">{{ statusLabel[row.enrollment_status] || row.enrollment_status }}</template></el-table-column>
    </el-table>
    <AppPagination v-model:current-page="page" :page-size="50" :total="data?.total || 0" />
  </section>
</template>
<style scoped>.filters { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }.filters .el-input { max-width: 260px; }.el-pagination { margin-top: 18px; }</style>
