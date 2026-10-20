<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { importTemplateDraft, listCollegeTemplates, listTemplateUpdates, type SchoolTimeTemplate, type TemplateUpdate } from '../../api/schoolTimeTemplates'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'
const props = defineProps<{ collegeId: string; semesterId: string; effectiveFrom: string; disabled?: boolean }>()
const emit = defineEmits<{ imported: [profileId: string] }>()
const session = useSessionStore()
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.semesterId}`)
const rows = ref<SchoolTimeTemplate[]>([]), updates = ref<TemplateUpdate[]>([])
const selected = ref(''), name = ref(''), effective = ref(''), error = ref(''), busy = ref(false)
const available = computed(() => rows.value.filter(row => row.status === 'ACTIVE'))
const current = computed(() => available.value.find(row => row.id === selected.value))
async function load() {
  const ticket = epoch.begin(), cid = props.collegeId, sid = props.semesterId
  if (!cid || !sid) return
  error.value = ''
  try {
    const [templates, messages] = await Promise.all([listCollegeTemplates(cid), listTemplateUpdates(cid, sid)])
    if (ticket.isCurrent()) { rows.value = templates; updates.value = messages }
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '读取学校模板失败' }
}
async function importDraft() {
  const row = current.value
  if (!row || busy.value || props.disabled) return
  const ticket = epoch.begin(), cid = props.collegeId, sid = props.semesterId
  const versionId = row.latest.id, draftName = name.value, date = effective.value
  busy.value = true; error.value = ''
  try {
    await ElMessageBox.confirm(`引用“${row.name}”第 ${row.latest.version} 版为独立草稿？保存后可修改，须另行发布和绑定才参与业务。`, '引用学校作息')
    if (!ticket.isCurrent()) return
    const profile = await importTemplateDraft(cid, sid, versionId, draftName, date)
    if (!ticket.isCurrent()) return
    emit('imported', profile.id)
    name.value = ''; selected.value = ''
    await load()
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '引用失败' }
  finally { busy.value = false }
}
watch(selected, () => { name.value = current.value?.name || '' })
watch(() => props.effectiveFrom, value => { effective.value = value }, { immediate: true })
watch(() => `${props.collegeId}:${props.semesterId}:${identityContext(session.currentUser)}`, () => { rows.value = []; updates.value = []; selected.value = ''; name.value = ''; void load() }, { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <section>
    <h4>引用学校作息模板</h4>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-for="item in updates" :key="item.profile_id" :title="`${item.profile_name}：引用 v${item.source_version}，学校最新 v${item.latest_version}（${item.template_status === 'ACTIVE' ? '有效' : '停用'}）。${item.message}`" type="info" :closable="false" />
    <el-select v-model="selected" placeholder="选择学校模板" :disabled="busy || disabled"><el-option v-for="row in available" :key="row.id" :value="row.id" :label="`${row.name} · v${row.latest_version}`" /></el-select>
    <el-input v-model="name" placeholder="新草稿名称" maxlength="128" :disabled="busy || disabled" />
    <el-date-picker v-model="effective" type="date" value-format="YYYY-MM-DD" placeholder="本学期生效日期" :disabled="busy || disabled" />
    <el-button :disabled="busy || disabled || !current || !name.trim() || !effective" @click="importDraft">创建独立草稿</el-button>
    <el-button :disabled="busy || disabled" @click="load">刷新模板与提示</el-button>
    <PaginatedTable v-if="current" :data="current.latest.periods"><el-table-column prop="period_no" label="节次" /><el-table-column prop="slot_id" label="稳定标识" /><el-table-column prop="name" label="名称" /><el-table-column prop="start_time" label="开始" /><el-table-column prop="end_time" label="结束" /></PaginatedTable>
  </section>
</template>
<style scoped>
.el-input, .el-select { max-width: 280px; margin: 8px; }
.el-alert { margin-bottom: 8px; }
</style>
