<script setup lang="ts">
import { computed } from 'vue'
import { useAssistantImportReview } from '../../composables/useAssistantImportReview'
import type { ResumableImport } from '../../api/assistantImports'
import { targetLabels } from './importLabels'

const props = defineProps<{ taskId: string; collegeId: string; semesterId: string; contextKey: string; available: boolean; locked: boolean }>()
const emit = defineEmits<{ resume: [drafts: ResumableImport[]] }>()
const { summary, groups, taskStatus, loading, opening, error, refresh, open } = useAssistantImportReview(
  () => ({ key: props.contextKey, taskId: props.taskId, collegeId: props.collegeId, semesterId: props.semesterId, available: props.available }),
  drafts => emit('resume', drafts)
)
const statusLabel = computed(() => ({ QUEUED: '助手正在等待核对资料，请稍后刷新', RUNNING: '助手正在核对资料，请稍后刷新', FAILED: '该核对任务未能完成，请返回助手重新发起', CANCELED: '该核对任务已取消' }[taskStatus.value] || ''))
const total = (files: Array<{ error_count: number }>) => files.reduce((sum, file) => sum + file.error_count, 0)
</script>

<template>
  <section class="assistant-import-card" aria-label="助手核对的资料">
    <header class="heading"><div><h2>助手核对的资料</h2><p>按资料类型继续核对，确认后才保存正式资料。</p></div><el-button :loading="loading" :disabled="opening || locked" @click="refresh">刷新核对结果</el-button></header>
    <p v-if="loading" role="status">正在读取核对任务…</p>
    <p v-else-if="error" class="problem" role="alert">{{ error }}</p>
    <p v-else-if="statusLabel" role="status">{{ statusLabel }}</p>
    <template v-else-if="summary">
      <p>{{ summary.files.length }} 份资料已完成助手核对。{{ summary.can_confirm ? '当前未发现阻断问题，请查看具体变化。' : '有待处理的问题，请进入核对页面查看具体原因。' }}</p>
      <div v-for="group in groups" :key="group.target" class="group">
        <div><strong>{{ targetLabels[group.target] || '资料' }}</strong><p>{{ group.files.length }} 份预览 · {{ total(group.files) }} 项待处理问题</p></div>
        <el-button type="primary" plain :loading="opening" :disabled="loading || opening || locked" @click="open(group.target)">核对这一组</el-button>
      </div>
      <p class="hint">助手汇总反映任务执行时的情况。进入核对页面会按当前权限与资料重新检查；问题明细、移除文件和确认保存沿用原流程。</p>
    </template>
  </section>
</template>

<style scoped>
.assistant-import-card { border: 1px solid var(--line); background: var(--surface); border-radius: 12px; padding: 22px; margin-bottom: 20px; }
.heading, .group { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.heading h2 { font-size: 18px; margin: 0; }
.assistant-import-card p { font-size: 13px; line-height: 1.7; }
.group { padding: 12px 0; border-bottom: 1px solid var(--line); }
.group p { margin: 4px 0 0; }
.hint, .heading p { color: var(--ink-soft); }
.problem { color: var(--red); }
@media (max-width: 640px) { .assistant-import-card { padding: 16px; } .heading { align-items: flex-start; flex-direction: column; } .group { align-items: flex-start; } }
</style>
