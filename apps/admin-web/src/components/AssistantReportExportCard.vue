<script setup lang="ts">
import { computed } from 'vue'
import { useAssistantReportExport } from '../composables/useAssistantReportExport'
import type { DownloadResponse } from '../api/http'

const props = defineProps<{ taskId: string; collegeId: string; collegeName: string; semesterId: string; contextKey: string; available: boolean }>()
function saveFile(file: DownloadResponse) {
  const url = URL.createObjectURL(file.blob), anchor = document.createElement('a')
  anchor.href = url; anchor.download = file.filename || 'attendance_report.xlsx'
  document.body.appendChild(anchor)
  try { anchor.click() } finally { anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000) }
}
const { plan, taskStatus, loading, downloading, error, notice, refresh, download } = useAssistantReportExport(
  () => ({ key: props.contextKey, taskId: props.taskId, collegeId: props.collegeId, semesterId: props.semesterId, available: props.available }), saveFile
)
const windowLabel = computed(() => plan.value?.window.week_no
  ? `第 ${plan.value.window.week_no} 周`
  : `${plan.value?.window.date_from || ''} 至 ${plan.value?.window.date_to || ''}`)
const statusLabel = computed(() => ({ QUEUED: '助手正在等待准备报表，请稍后刷新', RUNNING: '助手正在准备报表，请稍后刷新',
  FAILED: '该导出任务未能完成，请返回助手重新发起', CANCELED: '该导出任务已取消' }[taskStatus.value] || ''))
</script>

<template>
  <section class="assistant-export-card" aria-label="助手准备的报表">
    <div class="export-heading">
      <div><h3>助手准备的报表</h3><p>{{ collegeName }} · {{ plan ? windowLabel : '核对导出任务' }}</p></div>
      <button class="btn btn-sm btn-ghost" :disabled="loading || downloading" @click="refresh">{{ loading ? '读取任务中…' : '刷新导出任务' }}</button>
    </div>
    <p v-if="error" class="export-error" role="alert">{{ error }}</p>
    <template v-else-if="plan">
      <strong>{{ plan.title }}</strong>
      <p>导出范围以本卡所示时间为准。准备时命中 {{ plan.matching_task_count }} 个查课任务。文件尚未生成，点击后按当前权限和最新数据生成下载。</p>
      <button class="btn btn-dark" :disabled="loading || downloading" @click="download">{{ downloading ? '正在生成并下载…' : '生成并下载报表' }}</button>
    </template>
    <p v-else-if="statusLabel">{{ statusLabel }}</p>
    <p v-if="notice" class="export-success" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.assistant-export-card { margin: 18px 0; padding: 20px; border: 1px solid var(--line); border-radius: 8px; background: var(--paper); overflow-wrap: anywhere; }
.export-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.export-heading h3 { margin: 0; font-size: 16px; }
.export-heading p { color: var(--ink-mute); font-size: 12px; margin: 6px 0 0; }
.assistant-export-card p { line-height: 1.7; font-size: 13px; }
.export-error { color: var(--red); }
.export-success { color: var(--green); }
@media (max-width: 640px) { .assistant-export-card { padding: 16px; } }
</style>
