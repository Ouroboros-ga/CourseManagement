<script setup lang="ts">
import { computed, reactive, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createGroup, publishGroup, updateGroup, type CourseType, type GroupConfiguration, type VolunteerGroup } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'
import { useConfigurationImpact } from '../../composables/useConfigurationImpact'
import { useOrganizationOverview } from '../../composables/useOrganizationOverview'
import { countEffectiveMembers, organizationReadiness } from '../../utils/organizationReadiness'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import { useSessionStore } from '../../stores/session'
import { deleteManagedResource } from '../../composables/useResourceDeletion'
import OrganizationDetail from '../organizations/OrganizationDetail.vue'
import GroupRuleEditor from './GroupRuleEditor.vue'
import GroupHandover from './GroupHandover.vue'
import GroupSemesterPreparation from './GroupSemesterPreparation.vue'
import DeletedResources from './DeletedResources.vue'

const props = defineProps<{ collegeId: string; rows: VolunteerGroup[]; types: CourseType[]; userId: string; canManage: boolean; canPublish: boolean; capabilities: string[] }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore(), route = useRoute(), router = useRouter()
const { saving, run } = useCampusMutation(() => props.collegeId, () => emit('changed'))
const confirmImpact = useConfigurationImpact(() => props.collegeId)
const selected = computed(() => props.rows.find(g => g.id === route.query.group_id) || null)
const editorRoot = shallowRef<HTMLElement | null>(null)
const active = shallowRef<VolunteerGroup | null>(null)
const editing = shallowRef(false), configuring = shallowRef(false), handingOver = shallowRef(false), copying = shallowRef(false)
const form = reactive({ name: '', starts_on: null as string | null, ends_on: null as string | null })
const referenceDate = computed(() => {
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
  return session.currentSemester ? [session.currentSemester.start_date, today, session.currentSemester.end_date].sort()[1]! : today
})
const overview = useOrganizationOverview(() => ({ key: `${props.userId}:${props.collegeId}:${session.currentSemesterId}:${session.workspace?.authorization_revision}`, collegeId: props.collegeId, semesterId: session.currentSemesterId, enabled: !!session.campusRuntime?.business_scoped, groups: props.rows }))
const typesById = computed(() => new Map(props.types.map(t => [t.id, t.name])))
function count(row: VolunteerGroup) {
  const term = overview.data.value?.[row.id]
  return term && !term.error ? countEffectiveMembers(term.members, session.currentSemesterId, referenceDate.value) : null
}
function readiness(row: VolunteerGroup) {
  const term = overview.data.value?.[row.id]
  return organizationReadiness({ group: row, configuration: term?.configuration || null, memberCount: count(row), loaded: !!term, error: term?.error || '', semesterOpen: session.currentSemester?.status === 'ACTIVE', schedulingEnabled: !!session.campusRuntime?.scheduling, businessEnabled: !!session.campusRuntime?.business_scoped, date: referenceDate.value })
}
function scopeName(row: VolunteerGroup) {
  const term = overview.data.value?.[row.id]
  if (!term) return overview.busy.value ? '读取本学期范围…' : '范围待核对'
  if (term.error) return '范围读取失败'
  return term.configuration?.course_type_ids.map(id => typesById.value.get(id) || '历史课程类型').join('、') || '尚未设置'
}
function open(row: VolunteerGroup, panel = 'members') {
  void router.push({ query: { ...route.query, tab: 'groups', group_id: row.id, panel } })
}
function back() { void router.push({ query: { ...route.query, tab: 'groups', group_id: undefined, panel: undefined } }) }
function edit(row: VolunteerGroup | null) {
  active.value = row
  Object.assign(form, row ? { name: row.name, starts_on: row.starts_on, ends_on: row.ends_on } : { name: '', starts_on: null, ends_on: null })
  editing.value = true
}
const updateExisting = (row: VolunteerGroup, body: Parameters<typeof updateGroup>[2]) => run(async cid => {
  const revision = await confirmImpact('groups', row.id)
  return updateGroup(cid, row, body, revision)
})
async function save() {
  const row = active.value, body = { ...form, name: form.name.trim() }
  const ok = row ? await updateExisting(row, body) : await run(async cid => {
    const created = await createGroup(cid, { ...body, owner_user_id: props.userId })
    if (cid === props.collegeId) { markWorkspaceSaved(editorRoot.value); await router.replace({ query: { ...route.query, tab: 'groups', group_id: created.id, panel: 'rules' } }) }
  })
  if (ok) editing.value = false
}
async function publish(row: VolunteerGroup, configuration: GroupConfiguration) {
  if (await run(async cid => {
    const revision = await confirmImpact('groups', row.id)
    const result = await publishGroup(cid, row, configuration, revision)
    if (!configuring.value && cid === props.collegeId && selected.value?.id === row.id) {
      await router.replace({ query: { ...route.query, panel: 'members' } })
    }
    return result
  })) configuring.value = false
}
function menu(command: string, row: VolunteerGroup) {
  active.value = row
  if (command === 'edit') edit(row)
  if (command === 'defaults') configuring.value = true
  if (command === 'handover') handingOver.value = true
  if (command === 'copy') copying.value = true
  if (command === 'toggle') void updateExisting(row, { status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' })
  if (command === 'delete') { const cid = props.collegeId; void run(async id => { await deleteManagedResource(id, 'groups', row, () => cid === props.collegeId); if (cid === props.collegeId) await router.replace({ query: { ...route.query, group_id: undefined, panel: undefined } }) }) }
}
function primary(row: VolunteerGroup) {
  const action = readiness(row).action
  open(row, action === 'rules' ? 'rules' : 'members')
}
const canCopy = computed(() => props.capabilities.includes('volunteer.member.manage') && props.canPublish && !!session.campusRuntime?.business_scoped && session.currentSemester?.status === 'ACTIVE')
</script>
<template>
  <OrganizationDetail v-if="selected" :key="`${selected.id}:${session.currentSemesterId}`" :college-id="collegeId" :group="selected" :types="types" :term="overview.data.value?.[selected.id] || null" :loading="overview.busy.value" :member-count="count(selected)" :readiness="readiness(selected)" :reference-date="referenceDate" :capabilities="capabilities" :saving="saving" @back="back" @refresh="overview.load" @command="menu($event, selected!)" @publish="publish(selected!, $event)" />
  <section v-else class="organization-list">
    <div class="organization-toolbar">
      <div><h2>本学院组织</h2><p>{{ session.currentSemesterName || '请先选择学期' }} · 组织跨学期保留，下面展示所选学期的成员与实际规则。</p></div>
      <div class="toolbar-actions"><el-button v-if="session.hasPermission('volunteer.read')" @click="router.push({ query: { ...route.query, tab: 'qualifications', group_id: undefined, panel: undefined } })">全部志愿者</el-button><el-button v-if="canManage" type="primary" @click="edit(null)">新建组织</el-button></div>
    </div>
    <el-alert v-if="route.query.group_id" title="该组织不存在、已删除或不在当前授权范围，请重新选择。" type="warning" :closable="false" />
    <el-alert v-if="['members', 'preparation', 'unavailability'].includes(String(route.query.tab || ''))" title="请先选择组织；成员、请假和复用上学期都在组织详情中维护。" type="info" :closable="false" />
    <el-empty v-if="!rows.length" description="先建立一个查课组织，例如“早晚自习查课组”或“普通课查课组”。"><el-button v-if="canManage" type="primary" @click="edit(null)">创建第一个组织</el-button></el-empty>
    <el-table v-else :data="rows" v-loading="overview.busy.value">
      <el-table-column label="组织名称" min-width="180"><template #default="{ row }"><el-button link class="organization-name" @click="open(row)">{{ row.name }}</el-button><small>{{ row.status === 'ACTIVE' ? '组织已启用' : row.status === 'DRAFT' ? '新组织，待设置' : '组织已停用' }}</small></template></el-table-column>
      <el-table-column label="本学期查课范围" min-width="170"><template #default="{ row }">{{ scopeName(row) }}</template></el-table-column>
      <el-table-column label="有效成员" width="110"><template #default="{ row }">{{ count(row) === null ? '待核对' : `${count(row)} 人` }}</template></el-table-column>
      <el-table-column label="下一步" min-width="220"><template #default="{ row }"><span :class="{ 'ready-label': readiness(row).ready }">{{ readiness(row).label }}</span><small v-if="overview.data.value?.[row.id]?.error">{{ overview.data.value?.[row.id]?.error }}</small></template></el-table-column>
      <el-table-column label="操作" width="190"><template #default="{ row }"><el-button type="primary" plain @click="primary(row)">{{ readiness(row).action === 'rules' && canPublish ? '设置查课范围' : readiness(row).action === 'members' && count(row) === 0 && capabilities.includes('volunteer.member.manage') ? '添加成员' : '管理组织' }}</el-button><el-dropdown v-if="canManage || canPublish || canCopy" trigger="click" @command="menu($event, row)"><el-button link :disabled="saving">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="canManage" command="edit">编辑名称与有效期</el-dropdown-item><el-dropdown-item v-if="canCopy" command="copy">复用上学期成员与规则</el-dropdown-item><el-dropdown-item v-if="canPublish" command="defaults">维护组织默认规则</el-dropdown-item><el-dropdown-item v-if="canManage" command="toggle">{{ row.status === 'ACTIVE' ? '停用组织' : '启用组织' }}</el-dropdown-item><el-dropdown-item v-if="canManage" command="delete" divided>删除组织</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
    </el-table>
    <footer><span>成员按 {{ referenceDate }} 的有效期统计；具体日期的资格、请假和冲突在排班时重新核对。</span><DeletedResources v-if="canManage" :college-id="collegeId" kind="groups" @changed="emit('changed')" /></footer>
  </section>
  <el-dialog v-model="editing" :title="active ? '编辑组织' : '新建查课组织'" width="520px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
    <div ref="editorRoot" data-unsaved-form><el-form label-position="top" :disabled="saving"><el-form-item label="组织名称"><el-input v-model="form.name" maxlength="128" placeholder="例如：早晚自习查课组" /></el-form-item><p>保存后设置查课范围，再添加成员。当前创建人为负责人，可通过负责人交接调整。</p><el-collapse><el-collapse-item title="设置组织有效期（选填）" name="dates"><el-form-item label="开始日期"><el-date-picker v-model="form.starts_on" value-format="YYYY-MM-DD" placeholder="不限" /></el-form-item><el-form-item label="结束日期"><el-date-picker v-model="form.ends_on" value-format="YYYY-MM-DD" placeholder="不限" /></el-form-item></el-collapse-item></el-collapse></el-form></div>
    <template #footer><el-button :disabled="saving" @click="editing = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">{{ active ? '保存修改' : '创建并设置查课范围' }}</el-button></template>
  </el-dialog>
  <el-dialog v-model="configuring" :title="`${active?.name || ''} · 组织默认规则`" width="760px" destroy-on-close :close-on-click-modal="false" :show-close="!saving" :close-on-press-escape="!saving"><el-alert title="默认规则供尚未确认专用规则的学期沿用；修改不会覆盖已经确认的学期规则或历史任务。" type="info" :closable="false" /><GroupRuleEditor v-if="active && configuring" :college-id="collegeId" :group-id="active.id" :initial="active.configuration" :types="types" :saving="saving" @publish="publish(active!, $event)" /></el-dialog>
  <el-dialog v-model="handingOver" :title="`${active?.name || ''} · 负责人交接`" width="680px" destroy-on-close :close-on-click-modal="false"><GroupHandover v-if="active && handingOver" :college-id="collegeId" :group-id="active.id" @changed="handingOver = false; emit('changed')" /></el-dialog>
  <el-dialog v-model="copying" :title="`${active?.name || ''} · 复用上学期`" width="780px" destroy-on-close :close-on-click-modal="false"><GroupSemesterPreparation v-if="active && copying" :key="`${active.id}:${session.currentSemesterId}`" :college-id="collegeId" :groups="[active]" :types="types" :fixed-group-id="active.id" @changed="copying = false; overview.load()" /></el-dialog>
</template>
<style scoped>
.organization-list { display: grid; gap: 20px; }
.organization-toolbar, .toolbar-actions, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h2 { font-size: 18px; margin: 0 0 6px; }
p, footer, small { color: var(--ink-mute); font-size: 13px; line-height: 1.7; }
small { display: block; }
.organization-name { font-size: 15px; font-weight: 600; }
.ready-label { color: var(--el-color-success); }
footer { padding-top: 8px; }
</style>
