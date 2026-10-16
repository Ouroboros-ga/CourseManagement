<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspaceContext } from '../../composables/useWorkspaceContext'
import { confirmWorkspaceChange } from '../../composables/useWorkspaceChanges'
const { session, mode, page } = useWorkspaceContext()
const route = useRoute(), router = useRouter()
const showsWeek = computed(() => mode.value === 'semester' && (
  ['home', 'inspections', 'reports'].includes(page.value) ||
  (page.value === 'academic' && ['timetable', 'imports', ''].includes(String(route.query.tab || '')))
))
function collegeChanged(event: Event) {
  const select = event.target as HTMLSelectElement
  if (confirmWorkspaceChange()) {
    session.selectWorkspace(select.value)
    void router.replace({ query: { ...route.query, workspace_id: session.workspaceCollegeId } })
  }
  select.value = session.workspaceCollegeId
}
function semesterChanged(event: Event) {
  const select = event.target as HTMLSelectElement
  if (confirmWorkspaceChange()) {
    session.setSemester(select.value)
    void router.replace({ query: { ...route.query, semester_id: session.currentSemesterId } })
  }
  select.value = session.currentSemesterId
}
function weekChanged(event: Event) {
  const select = event.target as HTMLSelectElement
  if (confirmWorkspaceChange()) {
    session.setWeekNo(Number(select.value))
    void router.replace({ query: { ...route.query, week: String(session.currentWeekNo) } })
  }
  select.value = String(session.currentWeekNo)
}
</script>
<template>
  <div class="workspace-context">
    <select
      v-if="session.workspaces.length > 1"
      aria-label="业务学院工作区"
      :value="session.workspaceCollegeId"
      :title="session.workspace?.name || '业务学院工作区'"
      class="workspace-select"
      @change="collegeChanged"
    >
      <option v-for="row in session.workspaces" :key="row.id" :value="row.id">{{ row.name }}</option>
    </select>
    <strong
      v-else
      class="current-workspace-name"
      :title="session.workspace?.name || (session.workspaceMode ? '暂无授权学院' : '学校工作区')"
    >
      {{ session.workspace?.name || (session.workspaceMode ? '暂无授权学院' : '学校工作区') }}
    </strong>
    <span class="divider">｜</span>
    <template v-if="mode === 'semester'">
      <select aria-label="业务学期" :value="session.currentSemesterId" @change="semesterChanged">
        <option v-if="!session.activeSemesters.length" value="">暂无有效学期</option>
        <option v-for="row in session.activeSemesters" :key="row.id" :value="row.id">{{ row.name }}</option>
      </select>
      <template v-if="showsWeek && session.currentSemesterId">
        <select aria-label="教学周" :value="session.currentWeekNo" @change="weekChanged">
          <option v-for="week in session.totalWeeks" :key="week" :value="week">第 {{ week }} 周</option>
        </select>
        <span class="range">{{ session.weekDateRange.text }}</span>
      </template>
    </template>
    <span v-else class="current-label">{{ page === 'attendance' ? '当前学院 · 全部学期异议' : page === 'organizations' ? '组织长期资料 · 跨学期保留' : '当前档案与配置 · 跨学期保留' }}</span>
    <button class="refresh" @click="session.refreshWorkspaces">刷新学院权限</button>
  </div>
</template>
<style scoped>
.workspace-context {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: 0;
}
select {
  max-width: 300px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  background: var(--paper);
  border-radius: 5px;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
}
.current-workspace-name {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
}
.divider, .range, .current-label { color: var(--ink-mute); font-size: 12px; }
.refresh { margin-left: auto; border: 0; background: transparent; color: var(--blue); cursor: pointer; flex-shrink: 0; }
</style>
