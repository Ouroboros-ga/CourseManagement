<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { useCollegeDeadlines } from '../../composables/useCollegeDeadlines'
import { formatBeijingTime } from '../../utils/datetime'

const props = defineProps<{ collegeId: string; canManage: boolean }>()
const state = useCollegeDeadlines(() => props.collegeId, () => props.canManage)
</script>

<template>
  <section>
    <h2>本院查课提交截止</h2>
    <p>生成任务后自动建立本院日期记录。新建默认截止不早于当日活动结束，并预留最多 30 分钟提交；同一天最迟为 23:59。改期保留原截止时已形成的考核事实。</p>
    <p>升级前任务继续使用学校历史截止，由超级管理员处理，修改本院记录不会影响这些任务。</p>
    <el-alert v-if="state.error.value" :title="state.error.value" type="error" :closable="false" />
    <el-button :disabled="state.busy.value || state.writing.value" @click="state.load">刷新</el-button>
    <PaginatedTable :data="state.rows.value" v-loading="state.busy.value" empty-text="当前学期尚无本院截止记录，请先生成任务">
      <el-table-column prop="inspection_date" label="查课日期" />
      <el-table-column label="当前截止（北京时间）" min-width="190">
        <template #default="{ row }">{{ formatBeijingTime(row.deadline_at, 'minute') }}</template>
      </el-table-column>
      <el-table-column prop="task_count" label="有效任务数" />
      <el-table-column prop="version" label="版本" />
      <el-table-column v-if="props.canManage" label="调整时刻" width="125">
        <template #default="{ row }"><input v-model="state.drafts[row.inspection_date]" type="time" :disabled="state.writing.value" aria-label="提交截止时刻"></template>
      </el-table-column>
      <el-table-column label="操作" min-width="155">
        <template #default="{ row }">
          <el-button v-if="props.canManage" :disabled="state.writing.value || state.busy.value" @click="state.save(row)">保存</el-button>
          <el-button :disabled="state.busy.value" @click="state.showHistory(row.inspection_date)">历史</el-button>
        </template>
      </el-table-column>
    </PaginatedTable>
    <template v-if="state.historyDate.value">
      <h3>{{ state.historyDate.value }} 的截止历史</h3>
      <PaginatedTable :data="state.history.value">
        <el-table-column prop="version_no" label="版本" />
        <el-table-column label="截止"><template #default="{ row }">{{ formatBeijingTime(row.deadline_at, 'minute') }}</template></el-table-column>
        <el-table-column label="修改时间"><template #default="{ row }">{{ formatBeijingTime(row.created_at, 'minute') }}</template></el-table-column>
        <el-table-column label="办理账号"><template #default="{ row }">{{ row.changed_by ? `账号 #${row.changed_by}` : '系统默认' }}</template></el-table-column>
        <el-table-column prop="reason" label="说明" />
      </PaginatedTable>
    </template>
  </section>
</template>

<style scoped>
p { color: var(--el-text-color-secondary); line-height: 1.6; }
input { padding: 6px; border: 1px solid var(--el-border-color); border-radius: var(--radius-md); color: inherit; background: var(--el-bg-color); }
.el-button { margin: 8px 4px 8px 0; }
</style>
