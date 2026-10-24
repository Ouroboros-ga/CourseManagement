<script setup lang="ts">
import type { ConversationTurn, ConversationAction } from '../../api/assistantConversations'
defineProps<{ turns: ConversationTurn[]; beforeCursor: string | null; loadingOlder: boolean; locked: boolean }>()
const emit = defineEmits<{ older: []; open: [action: ConversationAction] }>()
const labels: Record<string, string> = { QUEUED: '正在排队', SENDING: '正在处理', SUCCEEDED: '已回复', FAILED: '本次未完成', UNCERTAIN: '结果待核对' }
const taskLabels: Record<string, string> = { QUEUED: '等待处理', RUNNING: '处理中', SUCCEEDED: '可以查看', FAILED: '未完成', CANCELED: '已取消' }
</script>

<template>
  <div class="conversation-messages" aria-label="助手对话记录">
    <el-button v-if="beforeCursor" text :loading="loadingOlder" :disabled="locked" @click="emit('older')">查看更早的对话</el-button>
    <article v-for="turn in turns" :key="turn.id" class="conversation-turn">
      <div class="question"><span class="speaker">我</span><p class="message-text">{{ turn.user_text }}</p></div>
      <div class="answer">
        <div class="answer-label"><span class="speaker">教学助手</span><span class="state" :class="{ pending: ['QUEUED', 'SENDING'].includes(turn.state) }">{{ labels[turn.state] }}</span></div>
        <p v-if="turn.reply !== null" class="message-text">{{ turn.reply }}</p>
        <p v-else-if="turn.state === 'QUEUED'" class="hint">问题已收到，轮到后会自动处理。</p>
        <p v-else-if="turn.state === 'SENDING'" class="hint">正在核对当前资料，请稍候。</p>
        <p v-else-if="turn.state === 'UNCERTAIN'" class="hint">尚未确认处理结果。请先核对下面的任务，避免重复发起。</p>
        <p v-else-if="turn.error_code === 'CHAT_QUEUE_EXPIRED'" class="hint">等待时间较长，本次未开始处理。可以稍后重新提问。</p>
        <p v-else class="hint">本次未能完成，请刷新核对已登记的任务。</p>
        <div v-if="turn.actions.length" class="task-actions">
          <el-button v-for="action in turn.actions" :key="action.task_id" plain :disabled="locked" @click="emit('open', action)">
            {{ action.title }} · {{ taskLabels[action.task_status] }}
          </el-button>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.conversation-messages { display: flex; flex-direction: column; gap: 24px; }
.conversation-turn { display: grid; gap: 14px; }
.question { margin-left: 36px; padding: 14px 16px; background: var(--surface-alt, #f3f5f3); border-radius: 12px 12px 2px 12px; }
.answer { padding: 0 2px; }
.speaker { font-size: 12px; font-weight: 600; color: var(--ink-mute); }
.answer-label { display: flex; align-items: center; gap: 10px; }
.state { color: var(--ink-mute); font-size: 11px; }
.state.pending { color: var(--accent); }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 8px 0 0; font-size: 14px; line-height: 1.8; }
.hint { color: var(--ink-mute); font-size: 13px; line-height: 1.7; }
.task-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.task-actions :deep(.el-button) { margin: 0; white-space: normal; height: auto; min-height: 34px; text-align: left; }
</style>
