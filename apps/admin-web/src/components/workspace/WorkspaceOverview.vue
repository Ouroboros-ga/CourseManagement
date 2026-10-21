<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../../stores/session'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { getWorkspaceOverview, type OverviewItem } from '../../api/overview'
const session = useSessionStore()
const { data, busy, error, load } = useWorkspaceRead(
  () => JSON.stringify([session.currentUser?.id, session.workspaceCollegeId, session.currentSemesterId, session.workspace?.authorization_revision]),
  () => !!session.currentUser && !!session.workspaceCollegeId && !!session.currentSemesterId,
  () => getWorkspaceOverview(session.workspaceCollegeId, session.currentSemesterId))
const pending = computed(() => data.value?.items.filter(item => item.status === 'ACTION_REQUIRED') || [])
const empty = computed(() => data.value?.items.filter(item => item.status === 'EMPTY') || [])
function destination(item: OverviewItem) {
  return { path: item.destination.path, query: { ...item.destination.query, workspace_id: data.value!.college_id, semester_id: data.value!.semester_id } }
}
const statusLabel = { ACTION_REQUIRED: '待处理', COMPLETE: '当前无待办', AVAILABLE: '已有资料', EMPTY: '暂无资料' }
</script>
<template>
  <section v-loading="busy" class="overview" aria-label="学期准备与待办">
    <div class="heading"><h2>学期准备与待办</h2><el-button size="small" :loading="busy" @click="load">刷新状态</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="data">
      <p>{{ data.as_of }} 核对 · {{ data.semester_status === 'ARCHIVED' ? '已归档学期，查阅历史资料；更正需按授权流程处理' : '当前所选学期' }} · {{ pending.length }} 类事项待处理 · {{ empty.length }} 类尚无资料（按需准备）</p>
      <el-alert v-if="!data.runtime.business_scoped || !data.runtime.scheduling" title="正式学院业务或组织排班尚未启用；这里展示已有资料，是否可操作仍以入口能力为准。" type="info" :closable="false" />
      <div class="metrics">
        <router-link v-for="item in data.items" :key="item.id" :to="destination(item)" class="metric" :class="{ pending: item.status === 'ACTION_REQUIRED' }">
          <span>{{ item.label }}</span><strong>{{ item.count }}</strong><small>{{ item.scope_label }} · {{ statusLabel[item.status] }}</small>
        </router-link>
      </div>
      <p class="hint">{{ data.scheduling_note }}</p>
      <p v-if="!data.items.length">当前没有可展示的统计权限，请从下方已授权入口进入。</p>
    </template>
    <p v-else-if="!busy && !error">选择已授权学院和学期后显示真实准备状态。</p>
  </section>
</template>
<style scoped>
.overview { margin-top: 24px; }.heading { display: flex; align-items: center; justify-content: space-between; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 16px; }
.metric { display: flex; flex-direction: column; gap: 8px; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 18px; color: var(--ink); text-decoration: none; }
.metric strong { font-size: var(--text-hero); }.metric small,p { color: var(--ink-mute); font-size: var(--text-xs); }.pending { border-color: var(--gold); }
</style>
