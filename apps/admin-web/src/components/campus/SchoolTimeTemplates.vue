<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listSchoolTimeTemplates, listTemplateVersions, saveSchoolTimeTemplate, setSchoolTemplateStatus, type SchoolTimeTemplate, type TemplateVersion } from '../../api/schoolTimeTemplates'
import type { CollegePeriodTime } from '../../api/collegeTime'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import TimePeriodEditor from './TimePeriodEditor.vue'
const props = defineProps<{ schoolId: string }>()
const session = useSessionStore()
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.schoolId}`)
const rows = ref<SchoolTimeTemplate[]>([]), history = ref<TemplateVersion[]>([])
const selected = ref(''), name = ref(''), error = ref(''), busy = ref(false)
const periods = ref<CollegePeriodTime[]>([])
const current = computed(() => rows.value.find(row => row.id === selected.value) || null)
function resetForm() {
  name.value = current.value?.name || ''
  periods.value = current.value ? current.value.latest.periods.map(p => ({ ...p, start_time: p.start_time.slice(0, 5), end_time: p.end_time.slice(0, 5) })) : [{ period_no: 1, slot_id: 'period-1', name: '第一节', start_time: '08:00', end_time: '08:45' }]
  history.value = []
}
async function load() {
  const ticket = epoch.begin()
  error.value = ''
  try {
    const result = await listSchoolTimeTemplates(props.schoolId)
    if (ticket.isCurrent()) { rows.value = result; resetForm() }
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '读取失败' }
}
async function execute(action: 'save' | 'status' | 'history') {
  if (busy.value) return
  const ticket = epoch.begin(), sid = props.schoolId, row = current.value
  busy.value = true; error.value = ''
  try {
    if (action === 'history' && row) {
      const result = await listTemplateVersions(sid, row.id)
      if (ticket.isCurrent()) history.value = result
      return
    }
    await ElMessageBox.confirm(action === 'status' ? '变更模板状态？学院已引用的草稿和正式作息继续保留。' : '保存为学校模板的新版本？学院只收到提示，现有作息不会改变。', '学校作息模板')
    if (!ticket.isCurrent()) return
    if (action === 'status' && row) await setSchoolTemplateStatus(sid, row)
    else await saveSchoolTimeTemplate(sid, name.value, periods.value, row)
    if (ticket.isCurrent()) await load()
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '保存失败' }
  finally { busy.value = false }
}
watch(selected, resetForm)
watch(() => `${props.schoolId}:${identityContext(session.currentUser)}`, () => { selected.value = ''; rows.value = []; resetForm(); void load() }, { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <section>
    <h3>学校作息模板</h3>
    <p>学院引用后独立维护。调整相同节次时保留稳定标识；保存新增不可变版本，不自动下发或覆盖。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-select v-model="selected" :disabled="busy"><el-option value="" label="新建学校模板" /><el-option v-for="row in rows" :key="row.id" :value="row.id" :label="`${row.name} · v${row.latest_version} · ${row.status}`" /></el-select>
    <el-input v-model="name" :disabled="busy || current?.status === 'INACTIVE'" placeholder="模板名称" maxlength="128" />
    <TimePeriodEditor v-model="periods" :disabled="busy || current?.status === 'INACTIVE'" />
    <el-button type="primary" :disabled="busy || !name.trim() || current?.status === 'INACTIVE'" @click="execute('save')">{{ current ? '保存为新版本' : '创建模板' }}</el-button>
    <el-button v-if="current" :disabled="busy" @click="execute('status')">{{ current.status === 'ACTIVE' ? '停用模板' : '恢复模板' }}</el-button>
    <el-button v-if="current" :disabled="busy" @click="execute('history')">查看历史版本</el-button>
    <el-collapse v-if="history.length"><el-collapse-item v-for="version in history" :key="version.id" :title="`${version.name} · v${version.version}`"><el-table :data="version.periods"><el-table-column prop="period_no" label="节次" /><el-table-column prop="slot_id" label="稳定标识" /><el-table-column prop="name" label="名称" /><el-table-column prop="start_time" label="开始" /><el-table-column prop="end_time" label="结束" /></el-table></el-collapse-item></el-collapse>
  </section>
</template>
<style scoped>
.el-select, .el-input { max-width: 360px; margin: 8px 12px 8px 0; }
section { margin-top: 24px; }
</style>
