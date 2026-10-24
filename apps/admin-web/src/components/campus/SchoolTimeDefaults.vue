<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import type { CollegePeriodTime, CollegeTimeConfiguration } from '../../api/collegeTime'
import { listCollegeTemplates } from '../../api/schoolTimeTemplates'
import { adoptSchoolDefaults, listSchoolDefaults, previewSchoolDefaults, publishSchoolDefaults, type TemplateAdoptionPreview } from '../../api/schoolTime'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'

const props = defineProps<{ collegeId: string; semesterId: string; configuration: CollegeTimeConfiguration }>()
const emit = defineEmits<{ changed: []; fillPeriods: [periods: CollegePeriodTime[]] }>()
const session = useSessionStore()
const root = ref<HTMLElement | null>(null)
const selected = ref(''), effective = ref(''), name = ref('')
const preview = shallowRef<TemplateAdoptionPreview | null>(null), error = ref(''), message = ref(''), saving = ref(false)
const context = computed(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.semesterId}`)
const enabled = computed(() => !!props.collegeId && !!props.semesterId && session.currentSemester?.status !== 'ARCHIVED' && !!session.campusRuntime?.scheduling && !!session.campusRuntime?.business_scoped)
const read = useWorkspaceRead(() => context.value, () => enabled.value, () => listSchoolDefaults(props.collegeId, props.semesterId))
const { data: templates } = read
const nativeId = ref('')
const { data: nativeTemplates } = useWorkspaceRead(() => context.value, () => enabled.value && session.hasAnyRole('SUPER_ADMIN'), () => listCollegeTemplates(props.collegeId))
const native = computed(() => nativeTemplates.value?.find(t => t.id === nativeId.value)?.latest)
const normalizedPeriods = (periods: CollegePeriodTime[]) => JSON.stringify(periods.map(p => ({ slot: p.slot_id || `period-${p.period_no}`, name: p.name || '', no: p.period_no, start: p.start_time.slice(0, 5), end: p.end_time.slice(0, 5) })))
const sourceVersionId = computed(() => native.value && normalizedPeriods(native.value.periods) === normalizedPeriods(props.configuration.periods) ? native.value.id : undefined)
const epoch = new ContextEpoch(() => `${context.value}:${selected.value}:${effective.value}`)
watch(context, () => { selected.value = ''; effective.value = ''; preview.value = null; error.value = ''; message.value = ''; saving.value = false; epoch.invalidate() })
watch([selected, effective], () => { preview.value = null; epoch.invalidate() })
onUnmounted(() => epoch.invalidate())
const selection = () => ({ template_id: selected.value, effective_from: effective.value, confirm_existing_tasks: true })
async function run(action: 'preview' | 'adopt' | 'publish') {
  if (saving.value || !enabled.value) return
  const ticket = epoch.begin(), cid = props.collegeId, sid = props.semesterId
  saving.value = true; error.value = ''; message.value = ''
  try {
    if (action === 'preview') {
      const result = await previewSchoolDefaults(cid, sid, selection())
      if (ticket.isCurrent()) preview.value = result
    } else if (action === 'adopt' && preview.value) {
      await adoptSchoolDefaults(cid, sid, selection(), preview.value.revision)
      if (ticket.isCurrent()) { preview.value = null; message.value = '已采用学校默认版本，学院例外与已有任务快照保留。'; markWorkspaceSaved(root.value); emit('changed') }
    } else if (action === 'publish') {
      await publishSchoolDefaults(sid, name.value, JSON.parse(JSON.stringify(props.configuration)), sourceVersionId.value)
      if (ticket.isCurrent()) { message.value = '已发布学校默认版本；学院需预览并明确采用。'; markWorkspaceSaved(root.value); await read.load() }
    }
  } catch (e) { if (ticket.isCurrent()) { preview.value = null; error.value = e instanceof Error ? e.message : '操作失败，请重新预览' } }
  finally { if (ticket.isLatest()) saving.value = false }
}
</script>
<template>
  <section v-if="enabled" ref="root" class="school-defaults" data-unsaved-form>
    <h3>采用学校默认作息与校历</h3>
    <p>学校发布后不会自动覆盖本院配置。先查看影响，再选择采用；已发布的学院例外保留。</p>
    <el-alert v-if="error || read.error.value" :title="error || read.error.value" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <el-select v-model="selected" placeholder="选择学校版本" :disabled="saving"><el-option v-for="row in templates || []" :key="row.id" :value="row.id" :label="`${row.name} · v${row.version}`" /></el-select>
    <el-date-picker v-model="effective" value-format="YYYY-MM-DD" placeholder="本院生效日期" :disabled="saving" />
    <el-button :disabled="!selected || !effective || saving" @click="run('preview')">预览采用影响</el-button>
    <template v-if="preview">
      <p>保留 {{ preview.retained_college_exceptions.length }} 项学院例外；{{ preview.retained_future_task_ids.length }} 个未来任务保留原时间快照。</p>
      <PaginatedTable :data="preview.configuration.periods"><el-table-column prop="period_no" label="节次" /><el-table-column prop="name" label="名称" /><el-table-column prop="start_time" label="开始" /><el-table-column prop="end_time" label="结束" /></PaginatedTable>
      <PaginatedTable :data="preview.configuration.calendar"><el-table-column prop="date" label="日期" /><el-table-column prop="override_type" label="停课/补课" /><el-table-column prop="source_teaching_week" label="来源周" /><el-table-column prop="source_teaching_weekday" label="来源星期" /></PaginatedTable>
      <el-button type="primary" :loading="saving"  @click="run('adopt')">确认采用以上作息（已有任务保留原快照）</el-button>
    </template>
    <div v-if="session.hasAnyRole('SUPER_ADMIN')">
      <el-select v-model="nativeId" placeholder="复用已有学校节次模板" :disabled="saving"><el-option v-for="t in nativeTemplates || []" :key="t.id" :value="t.id" :label="`${t.name} · v${t.latest_version}`" :disabled="t.status !== 'ACTIVE'" /></el-select><el-button :disabled="!native || saving" @click="native && emit('fillPeriods', JSON.parse(JSON.stringify(native.periods)))">填入下方节次表单</el-button>
      <p v-if="sourceVersionId">本次发布将保留所选学校节次模板的版本来源，同时冻结本学期校历与教务映射。</p>
      <p>校级发布：使用下方正在编辑的完整节次、校历和教务映射创建不可变默认版本。</p>
      <el-input v-model="name" placeholder="学校默认版本名称" maxlength="128" :disabled="saving" />
      <el-button :disabled="!name.trim() || !configuration.effective_from || saving" @click="run('publish')">将下方配置发布为学校默认</el-button>
    </div>
  </section>
</template>
<style scoped>
.school-defaults { margin: 16px 0; padding: 16px; border: 1px solid var(--el-border-color); border-radius: var(--radius-md); }
.school-defaults :deep(.el-select), .school-defaults :deep(.el-input) { max-width: 320px; margin: 8px; }
</style>
