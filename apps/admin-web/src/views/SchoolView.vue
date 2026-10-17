<script setup lang="ts">
import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listWorkspaces, updateCollege, type College } from '../api/campus'
import { useSessionStore } from '../stores/session'
import { ContextEpoch } from '../utils/contextEpoch'
import { usePageTabs } from '../composables/usePageTabs'
import { useCampusMutation } from '../composables/useCampusMutation'
import { confirmWorkspaceChange } from '../composables/useWorkspaceChanges'
import CampusAdministration from '../components/campus/CampusAdministration.vue'
import OwnershipReconciliation from '../components/campus/OwnershipReconciliation.vue'
import SemesterArchive from '../components/campus/SemesterArchive.vue'
const session = useSessionStore()
const rows = shallowRef<College[]>([]), targetId = shallowRef(''), error = shallowRef('')
const college = computed(() => rows.value.find(row => row.id === targetId.value) || null)
const tab = usePageTabs(() => ['administration', 'ownership', 'archive'])
const epoch = new ContextEpoch(() => session.currentUser?.id || '')
const { saving, run } = useCampusMutation(() => targetId.value, () => { void changed() })
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
async function renameCollege() {
  const row = college.value
  if (!row) return
  try {
    const { value } = await ElMessageBox.prompt('学院名称用于课表、任务与报表展示；已生成的历史数据保留当时的名称快照。', '重命名管理对象', {
      inputValue: row.name, inputPattern: /\S/, inputErrorMessage: '学院名称不能为空', confirmButtonText: '保存名称'
    })
    await run(cid => updateCollege(cid, { name: String(value).trim(), lock_version: row.lock_version }))
  } catch { /* 用户取消 */ }
}
async function toggleCollegeStatus() {
  const row = college.value
  if (!row) return
  const stopping = row.status === 'ACTIVE'
  try {
    await ElMessageBox.confirm(
      stopping ? '停用后本学院停止新的配置写入，已有配置与历史数据完整保留。' : '恢复本学院的配置写入权限？',
      stopping ? '停用管理对象' : '恢复管理对象'
    )
    await run(cid => updateCollege(cid, { status: stopping ? 'INACTIVE' : 'ACTIVE', lock_version: row.lock_version }))
  } catch { /* 用户取消 */ }
}
</script>
<template>
  <section v-if="session.hasAnyRole('SUPER_ADMIN')">
    <header class="page-head"><h1>学校与学院管理</h1><p class="sub">设立学院、任命教师归属、配置跨范围授权并核对存量归属。</p></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-tabs v-model="tab"><el-tab-pane name="administration" label="学院、教师与授权" /><el-tab-pane name="ownership" label="存量归属核对" /><el-tab-pane name="archive" label="学期归档" /></el-tabs>
    <div v-if="tab === 'administration'" class="context-bar">
      <span class="context-label">管理对象</span>
      <el-select class="context-select" :model-value="targetId" @update:model-value="selectTarget" placeholder="选择被管理的学院" aria-label="管理对象学院">
        <el-option v-for="row in rows" :key="row.id" :value="row.id" :label="`${row.name}${row.status === 'INACTIVE' ? '（停用）' : ''}`" />
      </el-select>
      <template v-if="college">
        <el-tag :type="college.status === 'ACTIVE' ? 'success' : 'info'" disable-transitions>{{ college.status === 'ACTIVE' ? '在用' : '已停用' }}</el-tag>
        <el-button :disabled="saving" @click="renameCollege">重命名</el-button>
        <el-button :disabled="saving" @click="toggleCollegeStatus">{{ college.status === 'ACTIVE' ? '停用' : '恢复' }}</el-button>
      </template>
      <p class="context-note">这里选择的是“被管理的学院”，不会切换你当前办理业务的学院；顶部工作区保持原样。</p>
    </div>
    <div class="tab-stage">
      <Transition name="tab-fade" mode="out-in">
        <div v-if="tab === 'administration'" key="administration">
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
<style scoped>
.context-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 16px 0 4px; padding: 12px 16px; background: var(--paper-deep); border: 1px solid var(--line); border-radius: var(--radius); }
.context-label { font-weight: 600; color: var(--ink); }
.context-select { width: 280px; }
.context-note { flex-basis: 100%; margin: 0; font-size: 12px; color: var(--ink-mute); }
</style>
