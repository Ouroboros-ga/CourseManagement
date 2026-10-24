<script setup lang="ts">
import PaginatedTable from '../PaginatedTable.vue'
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import type { CourseType, VolunteerGroup } from '../../api/campus'
import { confirmPreparation, preparationSource, previewPreparation, type PreparationPreview } from '../../api/organizationManagement'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
const props = defineProps<{ collegeId: string; groups: VolunteerGroup[]; types: CourseType[]; fixedGroupId?: string }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore(), gid = ref(props.fixedGroupId || ''), sourceSid = ref(''), from = ref(''), to = ref('')
const root = ref<HTMLElement | null>(null)
const memberIds = ref<string[]>([])
const preview = shallowRef<PreparationPreview | null>(null), error = ref(''), message = ref(''), saving = ref(false)
const context = computed(() => `${identityContext(session.currentUser)}:${props.collegeId}:${session.currentSemesterId}:${gid.value}:${sourceSid.value}`)
const currentState = useWorkspaceRead(() => `${identityContext(session.currentUser)}:${props.collegeId}:${session.currentSemesterId}:${gid.value}`, () => !!gid.value && !!session.currentSemesterId, () => preparationSource(props.collegeId, gid.value, session.currentSemesterId, session.currentSemesterId))
const { data: currentRules } = currentState
const { data: source, error: sourceError, load } = useWorkspaceRead(() => context.value, () => !!gid.value && !!sourceSid.value && !!session.currentSemesterId, () => preparationSource(props.collegeId, gid.value, session.currentSemesterId, sourceSid.value))
const body = () => ({ source_semester_id: sourceSid.value, member_ids: memberIds.value, effective_from: from.value, effective_to: to.value, teaching_class_mapping: {} })
function dayAfter(value?: string) { if (!value) return ''; const [y, m, d] = value.split('-').map(Number); return new Date(Date.UTC(y!, m! - 1, d! + 1)).toISOString().slice(0, 10) }
const epoch = new ContextEpoch(() => `${context.value}:${JSON.stringify(body())}`)
watch(context, () => { from.value = session.currentSemester?.start_date || ''; to.value = dayAfter(session.currentSemester?.end_date); memberIds.value = []; message.value = '' }, { immediate: true })
watch(() => `${context.value}:${JSON.stringify(body())}`, () => { epoch.invalidate(); preview.value = null; saving.value = false; error.value = '' })
onUnmounted(() => epoch.invalidate())
async function run(confirm = false) {
  if (saving.value || !source.value) return
  const ticket = epoch.begin(), cid = props.collegeId, group = gid.value, sid = session.currentSemesterId
  const payload = JSON.parse(JSON.stringify(body())) as ReturnType<typeof body>
  saving.value = true; error.value = ''; message.value = ''
  try {
    if (confirm && preview.value) {
      await confirmPreparation(cid, group, sid, payload, preview.value.revision)
      if (ticket.isCurrent()) { preview.value = null; memberIds.value = []; message.value = '已复用所选成员与规则；请核对目标学期的本院学籍与资格。'; emit('changed'); markWorkspaceSaved(root.value); await Promise.all([load(), currentState.load()]) }
    } else {
      const result = await previewPreparation(cid, group, sid, payload)
      if (ticket.isCurrent()) preview.value = result
    }
  } catch (e) { if (ticket.isCurrent()) { preview.value = null; error.value = e instanceof Error ? e.message : '学期准备失败' } }
  finally { if (ticket.isLatest()) saving.value = false }
}
</script>
<template>
  <section ref="root" data-unsaved-form>
    <h3>复用上学期成员与规则</h3><p>当前学期：{{ session.currentSemesterName }}。只复制你勾选的成员与规则；仅复用本学院成员，并核对目标学期资格。</p>
    <p>请在生成目标学期任务前准备；已有任务时，请返回“成员名单”添加学生；规则变更先处理未来任务影响。</p>
    <el-alert v-if="error || sourceError" :title="error || sourceError" type="error" :closable="false" /><el-alert v-if="message" :title="message" type="success" :closable="false" />
    <el-select v-if="!fixedGroupId" v-model="gid" placeholder="选择组织" :disabled="saving"><el-option v-for="g in groups" :key="g.id" :value="g.id" :label="g.name" /></el-select>
    <el-alert v-if="session.semesters.filter(s => s.id !== session.currentSemesterId).length === 0" title="没有可复用的其他学期。首次使用直接在成员名单添加学生或导入 Excel，无需完成此步骤。" type="info" :closable="false" />
    <el-select v-model="sourceSid" placeholder="选择从哪个学期复制" :disabled="saving"><el-option v-for="s in session.semesters.filter(s => s.id !== session.currentSemesterId)" :key="s.id" :value="s.id" :label="s.name" /></el-select>
    <el-alert v-if="currentState.error.value" :title="currentState.error.value" type="error" :closable="false" />
    <p v-if="currentRules">目标学期现况：{{ currentRules.uses_semester_specific_rules ? '已确认学期专用规则' : '尚未准备，当前采用组织默认规则' }}；本学期成员记录 {{ currentRules.members.length }} 条（排班按日期复核）。课程类型：{{ currentRules.configuration.course_type_ids?.map(id => types.find(t => t.id === id)?.name || '类型待核对').join('、') }}。</p>
    <el-date-picker v-model="from" value-format="YYYY-MM-DD" placeholder="目标成员生效日（包含）" :disabled="saving" /><el-date-picker v-model="to" value-format="YYYY-MM-DD" placeholder="目标成员结束日（不包含）" :disabled="saving" />
    <template v-if="source">
      <p>{{ source.uses_semester_specific_rules ? '复用来源学期专用规则' : '来源学期无专用规则，复用本组当前默认规则' }}；可以只准备规则，不勾选成员。</p>
      <p>新学期统一采用来源的默认课程冲突处理，不复制旧的课程类型或教学班例外；来源规则和历史任务保持不变。</p>
      <el-checkbox-group v-model="memberIds" :disabled="saving"><el-checkbox v-for="m in source.members.filter(m => m.status === 'ACTIVE')" :key="m.id" :value="m.id">{{ m.name }} · {{ m.student_no }}</el-checkbox></el-checkbox-group>
      <el-button :disabled="saving || !from || !to" @click="run()">核对将要复制的成员与规则</el-button>
    </template>
    <template v-if="preview">
      <p>本学期规则：课程类型 {{ preview.configuration.course_type_ids?.map(id => types.find(t => t.id === id)?.name || '类型待核对').join('、') }}；{{ preview.configuration.class_mode === 'SPECIFIC' ? `指定 ${preview.configuration.class_ids?.length || 0} 个行政班` : '本院授权班级范围' }}。</p>
      <p>每日上限 {{ preview.configuration.daily_limit }} 次，每周 {{ preview.configuration.weekly_limit }} 次；{{ preview.configuration.count_scope === 'ALL_GROUPS' ? '跨全部组累计' : '本组累计' }}。默认课程冲突处理：{{ preview.configuration.default_effect === 'BLOCK' ? '禁止' : preview.configuration.default_effect === 'WARN' ? '人工确认后允许' : '允许' }}；与本班回避规则随本次规则版本冻结。</p>
      <PaginatedTable :data="preview.items"><el-table-column label="成员"><template #default="{ row }">{{ source?.members.find(m => m.id === row.source_member_id)?.name || row.student_id }}</template></el-table-column><el-table-column label="准备情况"><template #default="{ row }">{{ row.ready ? '可创建目标学期成员' : row.reason }}</template></el-table-column></PaginatedTable><p>准备检查不代表已排班；实际排班仍按执行日期复核本院学籍、资格和冲突。</p><el-button :disabled="!preview.can_confirm" :loading="saving" type="primary" @click="run(true)">确认复制到本学期</el-button></template>
  </section>
</template>

<style scoped>
section { display: grid; gap: 14px; }
h3 { margin: 0; }
p { margin: 0; color: var(--ink-mute); line-height: 1.7; font-size: var(--text-sm); }
</style>
