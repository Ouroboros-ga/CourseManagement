<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ImportPreviewResult, ImportSetPlan } from '../../api/importer'
import { previewSummary } from './importLabels'
import ImportFileDetail from './ImportFileDetail.vue'
import { groupIssues, personLinkNotice } from './importReviewPresentation'
const props = defineProps<{ plan: ImportSetPlan | null; drafts: Array<ImportPreviewResult & { filename: string }>; uploadErrors: string[]; failuresExcluded: boolean; busy: boolean; canConfirm: boolean }>()
const emit = defineEmits<{ remove: [id: string]; retry: []; restart: []; confirm: []; 'exclude-failures': [] }>()
type ReviewFile = ImportSetPlan['files'][number]
const selected = ref<ReviewFile | null>(null)
const rows = computed(() => props.plan?.files || props.drafts.map(d => ({ id: d.id, filename: d.filename, target: d.target, summary: d.summary || {}, changes: [], issues: [...(d.errors || []), ...(d.warnings || [])] })))
const blocked = (file: ReviewFile) => file.issues.some(i => i.severity === 'error')
const blockedCount = computed(() => rows.value.filter(blocked).length)
const counts = computed(() => { const changes = rows.value.flatMap(row => row.changes); return { create: changes.filter(c => c.action === 'CREATE').length, update: changes.filter(c => c.action === 'UPDATE').length, unchanged: changes.filter(c => c.action === 'UNCHANGED').length } })
const people = computed(() => rows.value.reduce((total, row) => ({ create: total.create + Number(row.summary.person_links_create || 0), existing: total.existing + Number(row.summary.person_links_existing || 0), pending: total.pending + Number(row.summary.person_links_pending || 0) }), { create: 0, existing: 0, pending: 0 }))
const summary = (row: ReviewFile) => previewSummary(row.target, row.summary) || `${row.changes.length} 项核对内容`
const issueGroups = computed(() => new Map(rows.value.map(file => [file.id, groupIssues(file)])))
function detail(row: ReviewFile) { selected.value = row }
</script>

<template>
  <section class="review" aria-label="文件导入预览">
    <header class="review-head"><div><h2>先看结果，再确认导入</h2><p>已读取 {{ rows.length }} 个表格<template v-if="blockedCount">，{{ blockedCount }} 个需要处理</template><template v-else-if="plan">，未发现阻断问题</template>。正式资料尚未保存。</p></div><el-button :disabled="busy" @click="emit('restart')">重新选择文件</el-button></header>
    <div v-if="plan" class="change-summary"><span>新增 <strong>{{ counts.create }}</strong> 项</span><span>修改 <strong>{{ counts.update }}</strong> 项</span><span>无变化 <strong>{{ counts.unchanged }}</strong> 项</span></div>
    <details v-if="people.create || people.existing || people.pending" class="person-link-summary disclosure">
      <summary>人员关联 · {{ people.pending ? `${people.pending} 项待关联，不影响课表保存` : '查看关联结果' }}</summary>
      <p class="hint">可自动建立 {{ people.create }} 项，已有 {{ people.existing }} 项，待关联 {{ people.pending }} 项。同一关系涉及多个文件时只保存一次。</p>
      <p v-if="people.pending" class="hint">{{ personLinkNotice(people.pending) }} 可先保存课表，再导入教职工档案并补齐关联；具体原因见文件详情。</p>
    </details>
    <el-alert v-for="message in uploadErrors" :key="message" :title="`未读入：${message}`" type="error" :closable="false" /><el-alert v-if="uploadErrors.length && !failuresExcluded" title="失败文件不会被悄悄跳过。可重新选择文件，或明确排除失败文件后仅导入下列资料。" type="warning" :closable="false" /><el-button v-if="uploadErrors.length && !failuresExcluded" :disabled="busy" @click="emit('exclude-failures')">本次不导入以上失败文件</el-button><p v-if="uploadErrors.length && failuresExcluded" class="hint">已明确排除 {{ uploadErrors.length }} 个失败文件；本次只导入下表中的文件。</p>
    <div class="file-list"><article v-for="file in rows" :key="file.id" class="file-row"><div class="file-content"><strong class="filename">{{ file.filename }}</strong><p>{{ summary(file) }}</p><p v-if="blocked(file)" class="problem">需要处理：{{ file.issues.find(i => i.severity === 'error')?.message }}</p><p v-else-if="issueGroups.get(file.id)?.warnings.length" class="warning">有 {{ issueGroups.get(file.id)?.warnings.length }} 项其他提示，请核对后导入。</p><p v-else class="ready">{{ plan ? '可以导入' : '已读取，等待核对' }}<span v-if="issueGroups.get(file.id)?.people.length" class="hint"> · {{ issueGroups.get(file.id)?.people.length }} 项人员关联可稍后处理</span></p></div><div class="row-actions"><el-button v-if="plan" link @click="detail(file)">{{ blocked(file) || issueGroups.get(file.id)?.warnings.length ? '查看问题与内容' : issueGroups.get(file.id)?.people.length ? '查看内容与关联提示' : '查看内容' }}</el-button><el-button link :disabled="busy" @click="emit('remove', file.id)">暂不导入（保留待修正）</el-button></div></article></div>
    <p v-if="blockedCount" class="problem">请处理以上问题，或明确移除对应文件；处理完成前不会保存。</p><p class="hint">{{ plan?.impact_note || '请核对本批资料。' }} 未出现在文件中的已有学生名单不会因此删除。</p><footer class="confirm-actions"><el-button v-if="!plan" :disabled="busy || rows.length > 100" @click="emit('retry')">重新核对这批文件</el-button><el-button type="primary" size="large" :disabled="!canConfirm" @click="emit('confirm')">确认导入 {{ rows.length }} 个文件</el-button><span class="hint">点击后才保存上面的新增与修改。</span></footer>
    <ImportFileDetail :file="selected" @close="selected = null" />
  </section>
</template>

<style scoped>
.person-link-summary {
  margin: 14px 0;
}
.person-link-summary > summary {
  font-size: var(--text-sm);
  line-height: 1.6;
}
.person-link-summary p {
  margin-top: 8px;
}
.review {
  margin-top: 20px;
}
.review-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.review-head h2 {
  margin-bottom: 6px;
}
.review-head p,
.file-content p {
  font-size: var(--text-sm);
  color: var(--ink-mute);
}
.change-summary {
  display: flex;
  gap: 26px;
  margin: 20px 0;
  font-size: var(--text-md);
}
.change-summary strong {
  font-size: var(--text-hero);
  color: var(--ink);
}
.file-list {
  margin: 16px 0;
  border-top: 1px solid var(--line);
}
.file-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
}
.file-content {
  min-width: 0;
}
.filename {
  font-size: var(--text-md);
  overflow-wrap: anywhere;
}
.file-content p {
  margin-top: 5px;
}
.row-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-shrink: 0;
}
.problem {
  color: var(--accent);
}
.ready {
  color: var(--green);
}
.warning {
  color: var(--amber);
}
.confirm-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin: 22px 0;
}
.el-alert {
  margin: 12px 0;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: var(--text-xs);
}
.detail-heading {
  margin-top: 18px;
}
.el-pagination {
  margin-top: 12px;
}
@media (max-width: 700px) {
  .file-row {
    flex-direction: column;
    gap: 5px;
  }
  .row-actions {
    justify-content: flex-end;
  }
  .change-summary {
    gap: 16px;
  }
}
</style>
