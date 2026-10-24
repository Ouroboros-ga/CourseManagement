<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../../stores/session'
import { canAccessPage } from '../../navigation/workspaceNavigation'
import type { ConversationAction } from '../../api/assistantConversations'
import ManagementConversationPanel from './ManagementConversationPanel.vue'

const session = useSessionStore(), router = useRouter(), opened = shallowRef(false)
const enabled = import.meta.env.VITE_AGENT_CHAT_ENABLED === 'true'
const available = computed(() => enabled && !!session.currentUser && !!session.campusRuntime?.business_scoped
  && !!session.workspaceCollegeId && !!session.currentSemesterId && !session.workspaceError
  && ['statistics.read', 'import.execute', 'inspection.read'].some(code => session.hasPermission(code)))
const contextKey = computed(() => JSON.stringify([session.currentUser?.id, session.currentUser?.roles,
  session.currentUser?.permissions, session.workspaceCollegeId, session.currentSemesterId,
  session.currentSemester?.status, session.workspace?.authorization_revision,
  session.workspace?.configuration_revision, session.workspace?.capabilities, available.value]))
watch(contextKey, () => {
  opened.value = false
  try { window.sessionStorage.removeItem('management-assistant-conversation') } catch { /* Optional recovery only. */ }
}, { flush: 'sync' })
async function openAction(action: ConversationAction) {
  const report = `/dashboard/reports?assistant_task_id=${action.task_id}`
  const imports = `/dashboard/academic?tab=imports&assistant_task_id=${action.task_id}`
  const page = action.open_path === report ? 'reports' : action.open_path === imports ? 'academic' : ''
  if (!available.value || !page || !canAccessPage(page, session)) return
  const key = contextKey.value
  const failure = await router.push(action.open_path)
  if (!failure && key === contextKey.value) opened.value = false
}
</script>

<template>
  <div v-if="available" class="management-assistant-entry">
    <el-button plain class="assistant-trigger" @click="opened = true">教学助手</el-button>
    <el-drawer v-model="opened" title="教学助手" size="min(560px, 100vw)" append-to-body class="management-assistant-drawer">
      <template #header><div class="assistant-heading"><h2>教学助手</h2><p>{{ session.workspace?.name }} · {{ session.currentSemesterName }}</p></div></template>
      <ManagementConversationPanel :context-key="contextKey" :college-id="session.workspaceCollegeId" :semester-id="session.currentSemesterId" :week-no="session.currentWeekNo" :available="available" :active="opened" @open="openAction" />
    </el-drawer>
  </div>
</template>

<style scoped>
.management-assistant-entry { margin-left: auto; flex-shrink: 0; }
.assistant-trigger { border-color: var(--accent); color: var(--accent); }
.assistant-heading h2 { margin: 0; font-size: 20px; font-weight: 500; color: var(--ink); }
.assistant-heading p { margin: 8px 0 0; font-size: 12px; color: var(--ink-mute); }
:global(.management-assistant-drawer .el-drawer__header) { margin-bottom: 0; padding: 24px 24px 16px; }
:global(.management-assistant-drawer .el-drawer__body) { padding: 0 24px 20px; overflow: hidden; }
@media (max-width: 480px) {
  :global(.management-assistant-drawer .el-drawer__header) { padding: 20px 16px 16px; }
  :global(.management-assistant-drawer .el-drawer__body) { padding: 0 16px 16px; }
}
</style>
