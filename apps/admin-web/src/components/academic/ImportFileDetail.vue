<script setup lang="ts">
import PaginatedTable from '../PaginatedTable.vue'
import AppPagination from '../../components/AppPagination.vue'
import { computed, ref, watch } from 'vue'
import { previewSummary } from './importLabels'
import { describeImportValue, groupIssues, personLinkNotice, type ReviewFile } from './importReviewPresentation'

const props = defineProps<{ file: ReviewFile | null }>()
const emit = defineEmits<{ close: [] }>()
const page = ref(1)
watch(() => props.file, () => { page.value = 1 })
const issues = computed(() => props.file ? groupIssues(props.file) : { errors: [], warnings: [], people: [] })
const changes = computed(() => props.file?.changes.slice((page.value - 1) * 50, page.value * 50) || [])
const labels = { CREATE: '新增', UPDATE: '修改', UNCHANGED: '无变化' }
</script>

<template>
  <el-dialog :model-value="!!file" :title="file?.filename || '文件内容'" width="min(980px, 94vw)" @close="emit('close')">
    <template v-if="file">
      <p class="file-summary">{{ previewSummary(file.target, file.summary) || `${file.changes.length} 项核对内容` }}</p>
      <section v-if="issues.errors.length" class="blocking-section">
        <h3>需先处理的问题（{{ issues.errors.length }}）</h3>
        <p class="section-note">处理后重新上传，或在本次导入中移除此文件。</p>
        <p v-for="(issue, index) in issues.errors" :key="index" class="problem">
          {{ issue.row ? `第 ${issue.row} 行 · ` : '' }}{{ issue.field || '' }} {{ issue.message }}
        </p>
      </section>
      <section v-if="issues.warnings.length" class="warning-section">
        <h3>其他核对提示（{{ issues.warnings.length }}）</h3>
        <p v-for="(issue, index) in issues.warnings" :key="index" class="warning">
          {{ issue.row ? `第 ${issue.row} 行 · ` : '' }}{{ issue.field || '' }} {{ issue.message }}
        </p>
      </section>
      <details v-if="issues.people.length" class="person-links disclosure">
        <summary>人员待关联 {{ issues.people.length }} 项 · 不影响课表保存</summary>
        <p class="section-note">{{ personLinkNotice(issues.people.length) }}</p>
        <p class="section-note">可先保存课表，再导入教职工档案并补齐关联。重名或工号不符时需核对，系统不会猜配。</p>
        <PaginatedTable :data="issues.people" max-height="320">
          <el-table-column prop="context" label="班级 / 课程" min-width="170" />
          <el-table-column prop="person" label="教师 / 责任人" min-width="100" />
          <el-table-column prop="reason" label="待处理原因" min-width="230" />
        </PaginatedTable>
      </details>
      <h3 class="detail-heading">资料核对明细</h3>
      <p class="section-note">“无变化”表示与已有资料一致，确认后不会重复新增。</p>
      <el-table :data="changes" empty-text="没有可导入的内容">
        <el-table-column label="处理" width="80"><template #default="{ row }">{{ labels[row.action as keyof typeof labels] }}</template></el-table-column>
        <el-table-column label="来源位置" width="145"><template #default="{ row }">
          {{ row.source.sheet || '表格' }}{{ row.source.row ? ` · 第${row.source.row}行` : '' }}{{ row.source.column ? ` · 第${row.source.column}列` : '' }}
        </template></el-table-column>
        <el-table-column label="资料内容" min-width="260"><template #default="{ row }">
          <pre class="business-fields">{{ describeImportValue(row.after) }}</pre>
          <details v-if="row.action === 'UPDATE'" class="before-values"><summary>查看修改前</summary><pre class="business-fields">{{ describeImportValue(row.before) }}</pre></details>
        </template></el-table-column>
      </el-table>
      <AppPagination v-model:current-page="page" :page-size="50" :total="file.changes.length" />
    </template>
  </el-dialog>
</template>

<style scoped>
.file-summary {
  margin-bottom: 16px;
}
.blocking-section,
.warning-section {
  margin: 16px 0;
}
.problem {
  color: var(--accent);
  margin: 8px 0;
}
.warning {
  color: var(--amber);
  margin: 8px 0;
}
.section-note {
  margin: 8px 0 12px;
  font-size: var(--text-sm);
  color: var(--ink-mute);
}
.person-links {
  margin: 16px 0;
}
.person-links > summary {
  font-weight: 600;
  line-height: 1.6;
}
.detail-heading {
  margin-top: 22px;
}
.business-fields {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: inherit;
  font-size: var(--text-sm);
  line-height: 1.8;
}
.before-values {
  margin-top: 8px;
}
.el-pagination {
  margin-top: 16px;
}
</style>
