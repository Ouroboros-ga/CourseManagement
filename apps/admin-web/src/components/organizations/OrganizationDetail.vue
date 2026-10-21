<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { CourseType, GroupConfiguration, VolunteerGroup } from '../../api/campus'
import type { OrganizationTerm } from '../../composables/useOrganizationOverview'
import { canPreviewOrganization, type organizationReadiness } from '../../utils/organizationReadiness'
import { useSessionStore } from '../../stores/session'
import GroupMembers from '../campus/GroupMembers.vue'
import GroupRuleEditor from '../campus/GroupRuleEditor.vue'

const props = defineProps<{
  collegeId: string; group: VolunteerGroup; types: CourseType[]; term: OrganizationTerm | null
  loading: boolean; memberCount: number | null; readiness: ReturnType<typeof organizationReadiness>
  referenceDate: string; capabilities: string[]; saving: boolean
}>()
const emit = defineEmits<{ back: []; refresh: []; command: [value: string]; publish: [configuration: GroupConfiguration] }>()
const session = useSessionStore(), route = useRoute(), router = useRouter()
const panel = computed({
  get: () => route.query.panel === 'rules' ? 'rules' : 'members',
  set: value => { void router.replace({ query: { ...route.query, panel: value } }) }
})
const openSemester = computed(() => session.currentSemester?.status === 'ACTIVE')
const canManage = computed(() => props.capabilities.includes('volunteer.group.manage'))
const canPublish = computed(() => props.capabilities.includes('volunteer.config.publish'))
const canMembers = computed(() => props.capabilities.includes('volunteer.member.manage') && openSemester.value)
const canCopy = computed(() => canMembers.value && canPublish.value && !!session.campusRuntime?.business_scoped)
const configuration = computed(() => props.term?.configuration)
const canPreview = computed(() => canPreviewOrganization({
  group: props.group, configuration: configuration.value || null, memberCount: props.memberCount,
  loaded: !!props.term && !props.loading, error: props.term?.error || '', semesterOpen: openSemester.value,
  businessEnabled: !!session.campusRuntime?.business_scoped, schedulingEnabled: !!session.campusRuntime?.scheduling,
  date: props.referenceDate
}))
const scopeLabel = computed(() => configuration.value?.course_type_ids.map(id => props.types.find(t => t.id === id)?.name || '历史课程类型').join('、') || '尚未设置')
function dispatch() {
  if (!canPreview.value || !session.hasPermission('inspection.generate')) return
  void router.push({ path: '/dashboard/inspections', query: { workspace_id: props.collegeId, semester_id: session.currentSemesterId, tab: 'sampling', group_id: props.group.id } })
}
</script>
<template>
  <section class="organization-detail">
    <el-button class="back" link @click="emit('back')">← 返回组织列表</el-button>
    <header class="detail-heading">
      <div><h2>{{ group.name }}</h2><p>{{ session.workspace?.name }} · {{ session.currentSemesterName }} <el-tag size="small" :type="group.status === 'ACTIVE' ? 'success' : 'info'">{{ group.status === 'ACTIVE' ? '已启用' : group.status === 'DRAFT' ? '待设置' : '已停用' }}</el-tag></p></div>
      <div class="heading-actions">
        <el-dropdown v-if="canManage || canPublish || canCopy" trigger="click" @command="emit('command', $event)"><el-button :disabled="saving">更多管理</el-button><template #dropdown><el-dropdown-menu>
          <el-dropdown-item v-if="canCopy" command="copy">复用上学期成员与规则</el-dropdown-item>
          <el-dropdown-item v-if="canManage" command="edit">编辑名称与有效期</el-dropdown-item>
          <el-dropdown-item v-if="canPublish" command="defaults">维护组织默认规则</el-dropdown-item>
          <el-dropdown-item v-if="canManage && session.hasAnyRole('SUPER_ADMIN', 'TEACHER_ADMIN') && session.campusRuntime?.business_scoped && group.status === 'ACTIVE'" command="handover">负责人交接</el-dropdown-item>
          <el-dropdown-item v-if="canManage" command="toggle">{{ group.status === 'ACTIVE' ? '停用组织' : '启用组织' }}</el-dropdown-item>
          <el-dropdown-item v-if="canManage" command="delete" divided>删除组织</el-dropdown-item>
        </el-dropdown-menu></template></el-dropdown>
        <el-button v-if="session.hasPermission('inspection.generate')" type="primary" :disabled="!canPreview" @click="dispatch">前往查课安排</el-button>
      </div>
    </header>
    <div class="preparation-summary" aria-label="组织使用准备情况">
      <div><span class="summary-label">本学期查课范围</span><strong>{{ loading ? '正在核对…' : term?.error ? '读取失败，请重试' : scopeLabel }}</strong><el-button v-if="panel !== 'rules'" link @click="panel = 'rules'">查看设置</el-button></div>
      <div><span class="summary-label">{{ referenceDate }} 有效成员</span><strong>{{ memberCount === null ? '待核对' : `${memberCount} 人` }}</strong><span class="muted">按成员有效期统计</span></div>
      <div><span class="summary-label">当前准备情况</span><strong :class="{ ready: readiness.ready }">{{ readiness.label }}</strong><el-button v-if="readiness.action === 'enable' && canManage" link :disabled="saving" @click="emit('command', 'toggle')">启用组织</el-button></div>
    </div>
    <el-alert v-if="term?.error" :title="term.error" type="error" :closable="false"><el-button link @click="emit('refresh')">重新核对</el-button></el-alert>
    <p class="boundary">人数按参考日期展示，可以前往预览其他日期的课次；实际排班仍核对学籍、资格、请假及跨组冲突。启用组织不会自动下发任务。</p>
    <el-alert v-if="!session.campusRuntime?.scheduling" title="系统组织排班尚未开放：可以先设置范围和准备成员。完成后联系系统管理员开放，无需重复建组。" type="info" :closable="false" />
    <el-tabs v-model="panel" class="tabs-embed">
      <el-tab-pane name="members" label="成员名单">
        <p v-if="!canMembers" class="boundary">{{ openSemester ? '你可以查看成员。添加或调整成员请联系有成员维护权限的负责人。' : '该学期未开放，成员仅供查看。' }}</p>
        <GroupMembers v-if="session.campusRuntime?.business_scoped && session.currentSemesterId" :key="`${collegeId}:${group.id}:${session.currentSemesterId}`" :college-id="collegeId" :group-id="group.id" :semester-id="session.currentSemesterId" :semester-name="session.currentSemesterName" :as-of="referenceDate" :can-manage="canMembers" :is-super="session.hasAnyRole('SUPER_ADMIN')" compact @changed="emit('refresh')" />
        <el-empty v-else description="学院成员业务尚未开放，请联系系统管理员。" />
      </el-tab-pane>
      <el-tab-pane name="rules" label="查课范围与排班规则">
        <div class="rule-content">
          <p v-if="term && !term.error" class="rule-source">{{ term.specific ? '本学期使用已确认的专用规则。以下为实际生效设置；修改组织默认规则不会覆盖它。' : '本学期沿用组织默认规则。保存前会检查未来任务影响，已有任务保留原快照。' }}</p>
          <GroupRuleEditor v-if="term && !term.error && !term.specific && canPublish && openSemester" :key="`${group.id}:${group.config_version}`" :college-id="collegeId" :group-id="group.id" :initial="term.configuration" :types="types" :saving="saving" @publish="emit('publish', $event)" />
          <el-descriptions v-else-if="configuration && !term?.error" :column="1" border>
            <el-descriptions-item label="课程类型">{{ scopeLabel }}</el-descriptions-item>
            <el-descriptions-item label="班级范围">{{ configuration.class_mode === 'SPECIFIC' ? `指定 ${configuration.class_ids?.length || 0} 个班级` : '全部授权班级' }}</el-descriptions-item>
            <el-descriptions-item label="本人有课">{{ configuration.default_effect === 'BLOCK' ? '禁止排班' : configuration.default_effect === 'WARN' ? '人工确认后允许' : '允许，仍检查其他冲突' }}</el-descriptions-item>
            <el-descriptions-item label="次数上限">每天 {{ configuration.daily_limit }} 次，每周 {{ configuration.weekly_limit }} 次；{{ configuration.count_scope === 'ALL_GROUPS' ? '跨全部组织累计' : '本组累计' }}</el-descriptions-item>
            <el-descriptions-item label="检查本人班级">{{ configuration.own_class_effect === 'BLOCK' ? '禁止' : configuration.own_class_effect === 'WARN' ? '人工确认后允许' : '允许' }}</el-descriptions-item>
            <el-descriptions-item label="移动缓冲">{{ configuration.buffer_minutes }} 分钟</el-descriptions-item>
            <el-descriptions-item label="按本人课程类型的例外"><span v-if="!Object.keys(configuration.type_overrides).length">全部沿用默认冲突处理</span><div v-for="(effect, id) in configuration.type_overrides" :key="id">{{ types.find(t => t.id === id)?.name || '历史课程类型' }}：{{ effect === 'BLOCK' ? '禁止' : effect === 'WARN' ? '人工确认后允许' : '允许' }}</div></el-descriptions-item>
            <el-descriptions-item label="具体课程例外">{{ Object.keys(configuration.teaching_class_overrides || {}).length }} 项；跨组织同时到场的任务始终禁止。</el-descriptions-item>
          </el-descriptions>
          <el-empty v-else-if="!loading && !term?.error" description="尚无可查看的本学期规则。" />
          <el-button v-if="term?.specific && canPublish" @click="emit('command', 'defaults')">维护供其他学期沿用的默认规则</el-button>
        </div>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
<style scoped>
.organization-detail { display: grid; gap: 16px; }
.back { justify-self: start; }
.detail-heading, .heading-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h2 { margin: 0 0 7px; }
p { margin: 0; color: var(--ink-mute); line-height: 1.7; font-size: var(--text-sm); }
.preparation-summary { display: grid; grid-template-columns: 1fr 1fr 1.4fr; border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--el-bg-color); }
.preparation-summary > div { padding: 18px 22px; display: flex; flex-direction: column; align-items: flex-start; gap: 7px; }
.preparation-summary > div + div { border-left: 1px solid var(--line); }
.summary-label, .muted { color: var(--ink-mute); font-size: var(--text-xs); }
strong { font-size: var(--text-lg); }
.ready { color: var(--el-color-success); }
.rule-content { max-width: 850px; display: grid; gap: 20px; }
.rule-source { padding: 12px 16px; background: var(--el-fill-color-light); border-left: 3px solid var(--el-color-primary); }
pre { white-space: pre-wrap; font-size: var(--text-xs); }
@media (max-width: 850px) { .preparation-summary { grid-template-columns: 1fr; } .preparation-summary > div + div { border-left: 0; border-top: 1px solid var(--line); } }
</style>
