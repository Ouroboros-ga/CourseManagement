<script setup lang="ts">
import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { listWorkspaces, type College } from '../api/campus'
import { useSessionStore } from '../stores/session'
import { ContextEpoch } from '../utils/contextEpoch'
import { usePageTabs } from '../composables/usePageTabs'
import { confirmWorkspaceChange } from '../composables/useWorkspaceChanges'
import CampusAdministration from '../components/campus/CampusAdministration.vue'
import OwnershipReconciliation from '../components/campus/OwnershipReconciliation.vue'
import SemesterArchive from '../components/campus/SemesterArchive.vue'
const session = useSessionStore()
const rows = shallowRef<College[]>([]), targetId = shallowRef(''), error = shallowRef('')
const college = computed(() => rows.value.find(row => row.id === targetId.value) || null)
const tab = usePageTabs(() => ['administration', 'ownership', 'archive'])
const epoch = new ContextEpoch(() => session.currentUser?.id || '')
async function load() {
  const ticket = epoch.begin()
  if (!session.hasAnyRole('SUPER_ADMIN')) return
  try {
    const result = await listWorkspaces()
    if (!ticket.isCurrent()) return
    rows.value = result
    if (!result.some(row => row.id === targetId.value)) targetId.value = result.find(row => row.id === session.workspaceCollegeId)?.id || result[0]?.id || ''
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '学院读取失败' }
}
watch(() => session.currentUser?.id, () => { void load() }, { immediate: true })
onUnmounted(() => epoch.invalidate())
function selectTarget(value: string) { if (confirmWorkspaceChange()) targetId.value = value }
async function changed() { await load(); await session.refreshWorkspaces() }
</script>
<template>
  <section v-if="session.hasAnyRole('SUPER_ADMIN')">
    <header class="page-head"><h1>学校与学院管理</h1><p class="sub">管理学院、教师任命、额外授权及存量归属；管理对象不改变当前业务工作区。</p></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-tabs v-model="tab"><el-tab-pane name="administration" label="学院、教师与授权" /><el-tab-pane name="ownership" label="存量归属核对" /><el-tab-pane name="archive" label="学期归档" /></el-tabs>
    <div class="tab-stage">
      <Transition name="tab-fade" mode="out-in">
        <div v-if="tab === 'administration'" key="administration">
          <el-select :model-value="targetId" @update:model-value="selectTarget" placeholder="管理对象学院" aria-label="管理对象学院"><el-option v-for="row in rows" :key="row.id" :value="row.id" :label="`${row.name}${row.status === 'INACTIVE' ? '（停用）' : ''}`" /></el-select>
          <CampusAdministration :key="targetId" :college="college" @changed="changed" />
        </div>
        <div v-else-if="tab === 'ownership'" key="ownership">
          <OwnershipReconciliation :colleges="rows" />
        </div>
        <SemesterArchive v-else-if="session.campusRuntime?.business_scoped" key="archive" />
        <el-alert v-else key="unavailable" title="学院业务启用后可进行全校学期归档。" type="info" :closable="false" />
      </Transition>
    </div>
  </section>
</template>
