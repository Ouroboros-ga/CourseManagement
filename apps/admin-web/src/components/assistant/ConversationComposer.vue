<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
const model = defineModel<string>({ required: true })
const form = ref<HTMLFormElement | null>(null)
watch(model, value => { if (!value) markWorkspaceSaved(form.value) }, { flush: 'sync' })
onUnmounted(() => markWorkspaceSaved(form.value))
defineProps<{ disabled: boolean; busy: boolean; retryPending: boolean }>()
const emit = defineEmits<{ send: []; retry: [] }>()
function shortcut(event: KeyboardEvent) {
  if (event.ctrlKey && event.key === 'Enter' && !event.isComposing) { event.preventDefault(); emit('send') }
}
</script>

<template>
  <form ref="form" data-unsaved-form class="conversation-composer" @submit.prevent="emit('send')">
    <label for="management-assistant-question" class="composer-label">告诉助手你想处理的事情</label>
    <textarea id="management-assistant-question" v-model="model" maxlength="4000" rows="3" placeholder="例如：导出第7周本学院的考勤统计表" :disabled="disabled || retryPending" @keydown="shortcut" />
    <div class="composer-footer"><span class="hint">{{ model.length }}/4000 · Ctrl + Enter 发送</span><el-button native-type="submit" type="primary" :loading="busy" :disabled="disabled || retryPending || !model.trim()">发送</el-button></div>
    <div v-if="retryPending" class="retry-notice"><p>发送回执未确认。先刷新核对，也可重试原请求；重试会沿用原标识。</p><el-button :disabled="busy" @click="emit('retry')">重试原请求</el-button></div>
  </form>
</template>

<style scoped>
.conversation-composer { border-top: 1px solid var(--line); padding-top: 16px; }
.composer-label { display: block; font-size: 12px; margin-bottom: 8px; color: var(--ink-mute); }
.conversation-composer textarea { display: block; box-sizing: border-box; width: 100%; resize: vertical; max-height: 220px; min-height: 86px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); padding: 12px; font: inherit; font-size: 14px; line-height: 1.7; }
.conversation-composer textarea:focus { outline: 2px solid var(--accent); outline-offset: 2px; }
.conversation-composer textarea:disabled { opacity: .65; }
.composer-footer { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 10px; }
.hint { font-size: 11px; color: var(--ink-mute); }
.retry-notice { font-size: 12px; color: var(--ink-mute); line-height: 1.7; }
</style>
