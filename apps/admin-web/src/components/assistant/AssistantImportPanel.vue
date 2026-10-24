<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAssistantWorkspaces } from '../../composables/useAssistantWorkspaces'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import { targetLabels } from '../academic/importLabels'
const props = defineProps<{ contextKey: string; collegeId: string; semesterId: string; active: boolean; available: boolean }>()
const emit = defineEmits<{ open: [workspaceId: string] }>()
const { sources, busy, error, notice, retryPending, upload, retryUpload, refresh, cancel } = useAssistantWorkspaces(() => ({ key: props.contextKey, collegeId: props.collegeId, semesterId: props.semesterId, active: props.active, available: props.available }))
const input = ref<HTMLInputElement | null>(null), form = ref<HTMLElement | null>(null)
watch([busy, retryPending], () => { if (!busy.value && !retryPending.value) markWorkspaceSaved(form.value) })
function choose(event: Event) { const el = event.target as HTMLInputElement, file = el.files?.[0]; el.value = ''; if (file) void upload(file) }
const labels: Record<string, string> = { QUEUED: '等待整理', PROCESSING: '正在整理', READY: '已整理', FAILED: '整理未完成', CANCELED: '已取消', PREVIEW_QUEUED: '等待生成预览', PREVIEW_PROCESSING: '正在生成预览' }
</script>
<template>
  <section ref="form" class="attachment-panel" aria-label="助手资料工作区" data-unsaved-form>
    <div class="attachment-heading"><h3>把资料交给助手整理</h3><p>支持 ZIP、Excel 和 CSV。先整理分类，再核对变化，确认后才保存。</p></div>
    <div class="attachment-controls"><input ref="input" type="file" accept=".zip,.xlsx,.xls,.csv" class="file-input" aria-label="添加助手资料" @change="choose"><el-button type="primary" :disabled="busy" @click="input?.click()">{{ retryPending ? '重新选择原文件' : '添加 ZIP 或表格' }}</el-button><el-button :disabled="busy" @click="refresh()">刷新状态</el-button></div>
    <p v-if="busy" role="status">正在核对资料状态…</p><p v-if="error" role="alert" class="problem">{{ error }}</p>
    <p v-if="notice" role="status" class="hint">{{ notice }}</p>
    <p v-if="retryPending" class="hint">上次上传回执待确认。刷新或重试会沿用原标识。<el-button link :disabled="busy" @click="retryUpload">核对／重试原请求</el-button></p>
    <p v-if="!sources.length && !busy" class="empty">整理任务会保存在这里，关闭侧栏后仍可继续查看。</p>
    <article v-for="source in sources" :key="source.workspace_id" class="source-card">
      <div class="source-title"><strong>{{ source.filename }}</strong><span>{{ labels[source.state] }}</span></div>
      <p v-if="source.inspection" class="hint">共 {{ source.inspection.files.length }} 项资料 · {{ source.inspection.files.filter(f => f.blocked || !f.target).length }} 项待处理问题</p>
      <p v-if="source.inspection" class="types">{{ [...new Set(source.inspection.files.map(f => f.target ? targetLabels[f.target] || f.target : '待选择类型'))].join(' · ') }}</p>
      <p v-if="source.state === 'FAILED'" class="problem">本次整理未完成，请核对原文件后重新添加。</p>
      <div class="source-actions"><el-button v-if="source.inspection" :disabled="busy || !!error" @click="emit('open', source.workspace_id)">继续核对资料</el-button><el-button v-if="['QUEUED','PROCESSING','PREVIEW_QUEUED','PREVIEW_PROCESSING'].includes(source.state)" text :disabled="busy" @click="cancel(source.workspace_id)">取消任务</el-button></div>
    </article>
  </section>
</template>
<style scoped>
.attachment-panel { height: 100%; overflow-y: auto; padding: 12px 0; box-sizing: border-box; }
.attachment-heading h3 { margin: 8px 0; font-size: 20px; font-weight: 500; }
.attachment-heading p,.hint,.empty,.types { color: var(--ink-mute); font-size: 13px; line-height: 1.7; }
.attachment-controls,.source-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
.file-input { display: none; }
.source-card { border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin-top: 12px; }
.source-title { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.source-title strong { overflow-wrap: anywhere; min-width: 0; }.source-title span { color: var(--accent); flex-shrink: 0; }
.problem { color: var(--el-color-danger); font-size: 13px; overflow-wrap: anywhere; }.source-actions { margin-bottom: 0; }
</style>
