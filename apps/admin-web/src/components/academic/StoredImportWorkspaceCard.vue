<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { assistantWorkspacesApi, parseWorkspace, type ImportWorkspace, type StoredSelection } from '../../api/assistantWorkspaces'
import { getImportCatalog, type ImportCatalogItem, type ImportSetResult } from '../../api/importer'
import { validAgentId } from '../../api/assistantReports'
import { targetLabels } from './importLabels'
import ImportWizard from './ImportWizard.vue'

const props = defineProps<{ workspaceId: string; collegeId: string; semesterId: string; contextKey: string; available: boolean }>()
const emit = defineEmits<{ saved: [result: ImportSetResult]; busy: [value: boolean] }>()
const source = ref<ImportWorkspace | null>(null), catalog = ref<ImportCatalogItem[]>([]), error = ref(''), busy = ref(false), wizardBusy = ref(false)
const choices = ref<Record<number, string>>({}), selected = ref<{ target: string; source: StoredSelection } | null>(null)
const context = () => JSON.stringify([props.contextKey, props.workspaceId, props.collegeId, props.semesterId, props.available])
let request = 0
const groups = computed(() => {
  const map = new Map<string, number[]>()
  for (const member of source.value?.inspection?.files || []) {
    const target = member.target || choices.value[member.member_no]
    if (!member.blocked && target) map.set(target, [...(map.get(target) || []), member.member_no])
  }
  return [...map].flatMap(([target, all]) => Array.from({ length: Math.ceil(all.length / 100) }, (_, index) => ({
    key: `${target}:${index}`, target, memberNos: all.slice(index * 100, (index + 1) * 100),
    label: `${targetLabels[target] || target}${all.length > 100 ? ` · 第${index + 1}组` : ''}`,
    allowed: catalog.value.some(item => item.target === target)
  })))
})
async function refresh() {
  const captured = context(), ticket = ++request
  source.value = null; error.value = ''; busy.value = true
  try {
    if (!props.available || ![props.workspaceId, props.collegeId, props.semesterId].every(validAgentId)) throw new Error('资料入口不可用，请核对当前学院、学期和导入权限。')
    const scope = { collegeId: props.collegeId, semesterId: props.semesterId }
    const [raw, types] = await Promise.all([assistantWorkspacesApi.read(props.workspaceId, scope), getImportCatalog(props.collegeId)])
    if (captured !== context() || ticket !== request) return
    source.value = parseWorkspace(raw, scope, props.workspaceId); catalog.value = types.types
  } catch (cause) { if (captured === context() && ticket === request) error.value = cause instanceof Error ? cause.message : '读取失败，请重试' }
  finally { if (captured === context() && ticket === request) busy.value = false }
}
watch(context, () => { selected.value = null; choices.value = {}; catalog.value = []; wizardBusy.value = false; void refresh() }, { immediate: true })
function choose(group: typeof groups.value[number]) {
  if (wizardBusy.value || !group.allowed || source.value?.state !== 'READY') return
  const memberNos = group.memberNos.slice(0, 100)
  selected.value = { target: group.target, source: { workspaceId: props.workspaceId, memberNos, filenames: memberNos.map(no => source.value!.inspection!.files.find(m => m.member_no === no)!.filename) } }
}
watch(wizardBusy, value => emit('busy', value))
function saved(result: ImportSetResult) { emit('saved', result) }
</script>

<template>
  <section class="stored-import" aria-label="已整理资料核对">
    <h2>核对已整理的资料</h2>
    <p>按资料类型分组处理。确认变化后才会保存正式数据；每组最多100份。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-button :loading="busy" :disabled="wizardBusy" @click="refresh">刷新资料状态</el-button>
    <template v-if="source">
      <p>{{ source.filename }} · {{ source.state === 'READY' ? '可以核对' : source.state === 'CANCELED' ? '已取消' : source.state === 'FAILED' ? '处理失败，请重新添加资料' : '后台正在处理，请稍后刷新' }}</p>
      <ul class="source-files"><li v-for="member in source.inspection?.files || []" :key="member.member_no">
        <span>{{ member.filename }}</span>
        <span v-if="member.blocked"> · {{ member.message || '此文件不可处理' }}</span>
        <span v-else-if="member.target"> · {{ targetLabels[member.target] || member.target }}</span>
        <el-select v-else v-model="choices[member.member_no]" :disabled="wizardBusy" :aria-label="`${member.filename}的资料类型`" placeholder="请选择资料类型">
          <el-option v-for="item in catalog" :key="item.target" :value="item.target" :label="item.label" />
        </el-select>
        <span v-if="member.duplicate_of"> · 内容与第{{ member.duplicate_of }}份相同，请核对是否重复</span>
      </li></ul>
      <div class="group-actions"><el-button v-for="group in groups" :key="group.key" :disabled="wizardBusy || !group.allowed || source.state !== 'READY'" @click="choose(group)">
        {{ group.label }}（{{ group.memberNos.length }}份）{{ !group.allowed ? '：当前权限不可处理' : '：开始核对' }}
      </el-button></div>
      <ImportWizard v-if="selected" :key="`${context()}:${selected.target}:${selected.source.memberNos.join(',')}`" :initial-target="selected.target" :stored-source="selected.source" embedded @saved="saved" @busy="wizardBusy = $event" />
    </template>
  </section>
</template>

<style scoped>
.stored-import { padding: 20px; border: 1px solid var(--line); background: var(--paper); }
.stored-import p { color: var(--ink-soft); margin: 12px 0; }
.source-files { max-height: 280px; overflow: auto; padding-left: 20px; }
.source-files li { margin: 8px 0; overflow-wrap: anywhere; }
.source-files .el-select { width: 240px; max-width: 100%; }
.group-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
</style>
