<script setup lang="ts">
import { computed } from 'vue'
import { useManagementConversation } from '../../composables/useManagementConversation'
import type { ConversationAction } from '../../api/assistantConversations'
import ConversationMessages from './ConversationMessages.vue'
import ConversationComposer from './ConversationComposer.vue'

const props = defineProps<{ contextKey: string; collegeId: string; semesterId: string; available: boolean; active: boolean; weekNo: number }>()
const emit = defineEmits<{ open: [action: ConversationAction] }>()
const { conversation, turns, draft, error, busy, loadingOlder, beforeCursor, retryPending, waiting, canSend,
  send, retrySend, refresh, loadOlder, newConversation } = useManagementConversation(() => ({ key: props.contextKey,
  collegeId: props.collegeId, semesterId: props.semesterId, available: props.available, active: props.active }))
const examples = computed(() => [`导出第${props.weekNo}周本学院的考勤统计表`, `汇总第${props.weekNo}周的考勤情况`])
function openAction(action: ConversationAction) {
  if (!props.available || error.value || !turns.value.some(t => t.actions.some(a => a.task_id === action.task_id && a.open_path === action.open_path))) return
  emit('open', action)
}
</script>

<template>
  <section class="management-conversation" aria-label="教学助手工作区">
    <div class="conversation-toolbar"><p>围绕当前学院和学期提问</p><div><el-button text :disabled="busy || loadingOlder" @click="refresh()">刷新状态</el-button><el-button text :disabled="busy || loadingOlder" @click="newConversation">新对话</el-button></div></div>
    <div class="conversation-body">
      <div v-if="!turns.length && !error && !busy" class="conversation-empty"><span class="eyebrow">日常教务，少些琐碎</span><h3>从一件具体的事开始</h3><p>查询考勤、准备报表，或继续核对已有资料。任务会留在这里，方便你随时查看。</p><button v-for="example in examples" :key="example" class="example" :disabled="!canSend" @click="draft = example">{{ example }} <span aria-hidden="true">↗</span></button></div>
      <p v-if="busy && !turns.length" class="hint" role="status">正在核对会话状态…</p>
      <p v-if="error" class="conversation-error" role="alert">{{ error }}</p>
      <ConversationMessages :turns="turns" :before-cursor="beforeCursor" :loading-older="loadingOlder" :locked="!!error || busy || loadingOlder" @older="loadOlder" @open="openAction" />
      <p v-if="waiting" class="hint" role="status">处理完成后会自动更新。关闭侧栏后，可再次打开继续查看。</p>
      <p v-if="conversation && conversation.state !== 'OPEN'" class="hint" role="status">这次对话暂时无法继续。请先核对已有任务，再按需开始新对话。</p>
    </div>
    <ConversationComposer v-model="draft" :disabled="!canSend" :busy="busy" :retry-pending="retryPending" @send="send" @retry="retrySend" />
    <p class="confirmation-note">报表下载和资料保存仍由你核对确认。</p>
  </section>
</template>

<style scoped>
.management-conversation { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.conversation-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 4px; border-bottom: 1px solid var(--line); padding-bottom: 12px; }
.conversation-toolbar p { font-size: 12px; color: var(--ink-mute); margin: 0; }
.conversation-body { flex: 1; min-height: 0; overflow-y: auto; padding: 24px 2px; }
.conversation-empty { padding: 16px 0 32px; }
.eyebrow { color: var(--accent); font-size: 12px; letter-spacing: .06em; }
.conversation-empty h3 { margin: 12px 0; font-size: 23px; font-weight: 500; }
.conversation-empty p, .hint { color: var(--ink-mute); font-size: 13px; line-height: 1.8; }
.example { display: flex; justify-content: space-between; align-items: center; gap: 10px; width: 100%; padding: 14px; margin-top: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
.example:hover { border-color: var(--accent); }
.conversation-error { padding: 12px; border-left: 3px solid var(--el-color-danger); background: var(--surface-alt, #f6f5f3); font-size: 13px; overflow-wrap: anywhere; }
.confirmation-note { margin: 12px 0 0; font-size: 11px; color: var(--ink-mute); }
</style>
