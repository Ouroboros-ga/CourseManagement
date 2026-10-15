<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listTimeProfiles, saveTimeProfile, previewTimeProfile, publishTimeProfile, archiveTimeProfile, previewTimeBinding, bindTimeProfile, type TimeProfile } from '../../api/timeProfiles'
import { listScopedAcademic, type ScopedAcademicRow } from '../../api/scopedAcademic'
import type { CollegeTimeConfiguration } from '../../api/collegeTime'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import TimeTemplateImport from './TimeTemplateImport.vue'
const props = defineProps<{ collegeId: string; semesterId: string; defaultConfiguration: CollegeTimeConfiguration }>()
const session = useSessionStore()
const draftRoot = ref<HTMLElement | null>(null)
const rows = ref<TimeProfile[]>([]), classes = ref<ScopedAcademicRow[]>([])
const selected = ref(''), busy = ref(false), error = ref('')
const draft = reactive({ name: '', configuration: copyDefault() })
const bindingClassId = ref(''), bindingProfileId = ref('')
const current = computed(() => rows.value.find(row => row.id === selected.value) || null)
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.semesterId}`)
function copyDefault(): CollegeTimeConfiguration {
  return { ...JSON.parse(JSON.stringify(props.defaultConfiguration)), calendar: [], grid_slot_mapping: {}, confirm_existing_tasks: false }
}
function selectDraft() {
  const row = current.value
  draft.name = row?.name || ''
  draft.configuration = row ? { ...JSON.parse(JSON.stringify(row.draft_configuration)), confirm_existing_tasks: false } : copyDefault()
  draft.configuration.periods = draft.configuration.periods.map(period => ({ ...period, start_time: period.start_time.slice(0, 5), end_time: period.end_time.slice(0, 5) }))
}
async function load() {
  if (!props.semesterId) return
  const ticket = epoch.begin(), cid = props.collegeId, sid = props.semesterId
  try {
    const profiles = await listTimeProfiles(cid, sid)
    const teaching: ScopedAcademicRow[] = []
    for (let page = 1; ; page++) {
      const response = await listScopedAcademic(cid, 'teaching-classes', page, '')
      if (!ticket.isCurrent()) return
      teaching.push(...response.items.filter(row => String(row.semester_id) === sid && row.status === 'ACTIVE'))
      if (page * response.page_size >= response.total) break
      if (!response.items.length) throw new Error('教学班分页变化，请刷新')
    }
    if (!ticket.isCurrent()) return
    rows.value = profiles; classes.value = teaching
    selectDraft()
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '读取方案失败' }
}
async function execute(action: 'save' | 'publish' | 'archive') {
  const ticket = epoch.begin(), cid = props.collegeId, sid = props.semesterId, row = current.value
  busy.value = true; error.value = ''
  try {
    if (action === 'save') {
      const result = await saveTimeProfile(cid, sid, draft.name, draft.configuration, row)
      if (!ticket.isCurrent()) return
      selected.value = result.id
    } else if (row) {
      if (action === 'publish') {
        const preview = await previewTimeProfile(cid, sid, row.id)
        if (!ticket.isCurrent()) return
        await ElMessageBox.confirm(`发布已保存的“${row.name}”草稿？${preview.retained_future_task_ids.length} 个未来任务保留原快照，并加入影响处置清单。未保存的编辑不会发布。`, '发布作息方案')
        if (!ticket.isCurrent()) return
        await publishTimeProfile(cid, sid, row, preview.revision)
      } else {
        await ElMessageBox.confirm('归档后不可再编辑或绑定；仍有有效教学班绑定时会拒绝。', '归档作息方案')
        if (!ticket.isCurrent()) return
        await archiveTimeProfile(cid, sid, row)
      }
    }
    if (ticket.isCurrent()) await load(); markWorkspaceSaved(draftRoot.value)
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '操作失败' }
  finally { busy.value = false }
}
async function bind() {
  const ticket = epoch.begin(), cid = props.collegeId, sid = props.semesterId, tid = bindingClassId.value, pid = bindingProfileId.value || null
  busy.value = true; error.value = ''
  try {
    const preview = await previewTimeBinding(cid, sid, tid, pid)
    if (!ticket.isCurrent()) return
    await ElMessageBox.confirm(`为选中教学班切换作息？${preview.retained_future_task_ids.length} 个已有未来任务保留原快照；新课次与正式课程忙碌采用新方案。`, '确认教学班作息')
    if (!ticket.isCurrent()) return
    await bindTimeProfile(cid, sid, tid, pid, preview.revision)
    if (ticket.isCurrent()) await load(); markWorkspaceSaved(draftRoot.value)
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '绑定失败' }
  finally { busy.value = false }
}
function addPeriod() {
  const no = Math.max(0, ...draft.configuration.periods.map(row => row.period_no)) + 1
  if (no <= 60) draft.configuration.periods.push({ period_no: no, slot_id: `period-${no}`, name: '', start_time: '19:00', end_time: '19:40' })
}
function imported(profileId: string) {
  selected.value = profileId
  void load()
}
watch(selected, selectDraft)
watch(() => `${props.collegeId}:${props.semesterId}:${identityContext(session.currentUser)}`, () => { selected.value = ''; bindingClassId.value = ''; bindingProfileId.value = ''; error.value = ''; void load() }, { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <section ref="draftRoot" data-unsaved-form>
    <h3>教学班可选作息方案</h3>
    <p>默认跟随学院作息；同学院不同校区、年级可以选择独立时段。方案只管理上课时间，校历与教务小节映射保持学院统一。首版生效前使用学院默认时间。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <TimeTemplateImport :college-id="collegeId" :semester-id="semesterId" :effective-from="defaultConfiguration.effective_from" :disabled="busy" @imported="imported" />
    <el-select v-model="selected" :disabled="busy"><el-option value="" label="新建草稿（复制当前默认时段）" /><el-option v-for="row in rows" :key="row.id" :value="row.id" :label="`${row.name} · ${row.status}`" /></el-select>
    <p v-if="current?.source_template_version_id">来源学校模板版本 ID：{{ current.source_template_version_id }}；学院可独立调整，不随学校更新覆盖。</p>
    <el-form label-position="top" :disabled="busy || current?.status === 'ARCHIVED'">
      <el-form-item label="方案名称"><el-input v-model="draft.name" /></el-form-item>
      <el-form-item label="新版本生效日期"><el-date-picker v-model="draft.configuration.effective_from" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-table :data="draft.configuration.periods">
        <el-table-column label="节次" width="140"><template #default="{ row }"><el-input-number v-model="row.period_no" :min="1" :max="60" :disabled="busy || current?.status === 'ARCHIVED'" /></template></el-table-column>
        <el-table-column label="稳定标识"><template #default="{ row }">{{ row.slot_id || `period-${row.period_no}` }}</template></el-table-column>
        <el-table-column label="时段名称"><template #default="{ row }"><el-input v-model="row.name" placeholder="如早自习、第一节" :disabled="busy || current?.status === 'ARCHIVED'" /></template></el-table-column>
        <el-table-column label="开始"><template #default="{ row }"><el-time-select v-model="row.start_time" start="00:00" end="23:55" step="00:05" :disabled="busy || current?.status === 'ARCHIVED'" /></template></el-table-column>
        <el-table-column label="结束"><template #default="{ row }"><el-time-select v-model="row.end_time" start="00:00" end="23:55" step="00:05" :disabled="busy || current?.status === 'ARCHIVED'" /></template></el-table-column>
        <el-table-column label="操作"><template #default="{ $index }"><el-button :disabled="busy || current?.status === 'ARCHIVED' || draft.configuration.periods.length <= 1" @click="draft.configuration.periods.splice($index, 1)">移除</el-button></template></el-table-column>
      </el-table>
      <el-button @click="addPeriod">添加时段</el-button>
      <el-button :disabled="!draft.name || !semesterId" @click="execute('save')">保存草稿</el-button>
      <el-button v-if="current" @click="execute('publish')">预览并发布已保存草稿</el-button>
      <el-button v-if="current" @click="execute('archive')">归档</el-button>
    </el-form>
    <h4>教学班绑定</h4>
    <el-select v-model="bindingClassId" filterable :disabled="busy" placeholder="选择教学班"><el-option v-for="row in classes" :key="row.id" :value="row.id" :label="`${row.class_name}（当前方案 ${row.time_profile_id || '学院默认'}）`" /></el-select>
    <el-select v-model="bindingProfileId" :disabled="busy"><el-option value="" label="跟随学院默认作息" /><el-option v-for="row in rows.filter(row => row.status === 'ACTIVE')" :key="row.id" :value="row.id" :label="row.name" /></el-select>
    <el-button :disabled="busy || !bindingClassId" @click="bind">预览并确认绑定</el-button>
  </section>
</template>
<style scoped>
section { margin-top: 28px; border-top: 1px solid var(--el-border-color); padding-top: 12px; }
.el-select { min-width: 260px; margin: 8px 8px 8px 0; }
</style>
