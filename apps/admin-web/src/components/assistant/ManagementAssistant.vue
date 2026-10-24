<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../../stores/session'
import { canAccessPage } from '../../navigation/workspaceNavigation'
import type { ConversationAction } from '../../api/assistantConversations'
import ManagementConversationPanel from './ManagementConversationPanel.vue'
import AssistantImportPanel from './AssistantImportPanel.vue'
import { validAgentId } from '../../api/assistantReports'

const session = useSessionStore(), router = useRouter(), opened = shallowRef(false)
const enabled = import.meta.env.VITE_AGENT_CHAT_ENABLED === 'true'
const importsEnabled = import.meta.env.VITE_AGENT_IMPORT_ENABLED === 'true'
const tab = shallowRef(enabled ? 'chat' : 'imports')
const canChat = computed(() => enabled && ['statistics.read', 'import.execute', 'inspection.read'].some(code => session.hasPermission(code)))
const canImport = computed(() => importsEnabled && session.hasPermission('import.execute'))
const available = computed(() => (canChat.value || canImport.value) && !!session.currentUser && !!session.campusRuntime?.business_scoped
  && !!session.workspaceCollegeId && !!session.currentSemesterId && !session.workspaceError
)
const contextKey = computed(() => JSON.stringify([session.currentUser?.id, session.currentUser?.roles,
  session.currentUser?.permissions, session.workspaceCollegeId, session.currentSemesterId,
  session.currentSemester?.status, session.workspace?.authorization_revision,
  session.workspace?.configuration_revision, session.workspace?.capabilities, available.value]))
watch(contextKey, () => {
  opened.value = false
  try { window.sessionStorage.removeItem('management-assistant-conversation'); window.sessionStorage.removeItem('management-assistant-imports') } catch { /* Optional recovery only. */ }
  if (!canChat.value) tab.value = 'imports'
  else if (!canImport.value) tab.value = 'chat'
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
async function openWorkspace(id: string) {
  if (!available.value || !canImport.value || !validAgentId(id) || !canAccessPage('academic', session)) return
  const key = contextKey.value
  const failure = await router.push(`/dashboard/academic?tab=imports&assistant_workspace_id=${id}`)
  if (!failure && key === contextKey.value) opened.value = false
}
</script>

<template>
  <div v-if="available" class="management-assistant-entry">
    <el-button plain class="assistant-trigger" @click="opened = true">教学助手</el-button>
    <el-drawer v-model="opened" title="教学助手" size="min(560px, 100vw)" append-to-body class="management-assistant-drawer">
      <template #header><div class="assistant-heading"><h2>教学助手</h2><p>{{ session.workspace?.name }} · {{ session.currentSemesterName }}</p></div></template>
      <div class="assistant-content"><nav v-if="canChat && canImport" class="assistant-tabs" aria-label="助手功能"><button :class="{selected: tab === 'chat'}" @click="tab = 'chat'">对话</button><button :class="{selected: tab === 'imports'}" @click="tab = 'imports'">资料工作区</button></nav>
        <ManagementConversationPanel v-if="canChat" v-show="tab === 'chat'" :context-key="contextKey" :college-id="session.workspaceCollegeId" :semester-id="session.currentSemesterId" :week-no="session.currentWeekNo" :available="available && canChat" :active="opened && tab === 'chat'" @open="openAction" />
        <AssistantImportPanel v-if="canImport" v-show="tab === 'imports'" :context-key="contextKey" :college-id="session.workspaceCollegeId" :semester-id="session.currentSemesterId" :available="available && canImport" :active="opened && tab === 'imports'" @open="openWorkspace" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.management-assistant-entry { margin-left: auto; flex-shrink: 0; }
.assistant-content { height: 100%; display: flex; flex-direction: column; min-height: 0; }.assistant-content > :not(nav) { flex: 1; min-height: 0; }
.assistant-tabs { display: flex; gap: 16px; border-bottom: 1px solid var(--line); margin-bottom: 12px; }.assistant-tabs button { border: 0; padding: 10px 2px; background: transparent; color: var(--ink-mute); cursor: pointer; }.assistant-tabs button.selected { color: var(--accent); border-bottom: 2px solid var(--accent); }
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
