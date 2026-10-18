<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useSessionStore } from '../../stores/session'
import { useImportIntake } from '../../composables/useImportIntake'
import { downloadImportTemplatePack, getImportCatalog, type ImportCatalogItem, type ImportSetResult } from '../../api/importer'
import ImportWizard from './ImportWizard.vue'
import ImportIdentityReview from './ImportIdentityReview.vue'
import ImportConflictHelp from './ImportConflictHelp.vue'
import { savedSummary } from './importLabels'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'

const emit = defineEmits<{ saved: []; busy: [value: boolean] }>()
const session = useSessionStore(), intake = useImportIntake()
const { entries, groups, receipts, busy, error, revision } = intake
const catalog = ref<ImportCatalogItem[]>([]), catalogError = ref(''), templateError = ref('')
const target = ref(''), groupBusy = ref(false), templateBusy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null), folderInput = ref<HTMLInputElement | null>(null)
const zipInput = ref<HTMLInputElement | null>(null), omitted = ref<string[]>([])
const container = ref<HTMLElement | null>(null)
const context = () => JSON.stringify([session.currentUser?.id, session.workspaceCollegeId, session.currentSemesterId, session.workspace?.authorization_revision])
let catalogRequest = 0
watch(context, async () => {
  const ticket = ++catalogRequest, cid = session.workspaceCollegeId
  catalog.value = []; target.value = ''; groupBusy.value = false; omitted.value = []; catalogError.value = ''
  if (!cid) return
  try { const response = await getImportCatalog(cid); if (ticket === catalogRequest) catalog.value = response.types }
  catch (e) { if (ticket === catalogRequest) catalogError.value = e instanceof Error ? e.message : '资料目录读取失败，请刷新重试' }
}, { immediate: true })
const working = computed(() => busy.value || groupBusy.value)
watch(working, value => emit('busy', value), { immediate: true })
watch(() => entries.value.every(e => e.saved || e.excluded), complete => {
  if (complete) markWorkspaceSaved(container.value)
})
const label = (value: string) => catalog.value.find(c => c.target === value)?.label || value
const active = computed(() => groups.value.find(g => g.target === target.value))
const pending = computed(() => active.value?.entries.filter(e => !e.saved) || [])
const blockReason = computed(() => {
  if (pending.value.some(e => e.blocked)) return '本组有无法读取的文件，请修正并重新添加，或明确排除。'
  if (new Set(pending.value.map(e => e.filename)).size !== pending.value.length) return '本组有同路径文件，无法区分来源；请保留一份或改名后重新添加。'
  if (!catalog.value.some(c => c.target === target.value)) return '当前账号无权导入此类型，请交由有权管理员处理。'
  return ''
})
const canPreview = computed(() => !!pending.value.length && !blockReason.value)
// 缓存到依赖变化为止，避免父组件重渲染重置子向导的核对状态。
const sources = computed(() => intake.sources(target.value))
watch(groups, rows => { if (!rows.some(row => row.target === target.value)) target.value = rows[0]?.target || '' })
async function choose(event: Event) {
  const input = event.target as HTMLInputElement, files = Array.from(input.files || [])
  input.value = ''
  if (working.value) return
  omitted.value = files.filter(f => f.name.startsWith('.') || f.name.startsWith('~$') || !/\.(xlsx?|csv|zip)$/i.test(f.name)).map(f => f.webkitRelativePath || f.name)
  await intake.addFiles(files.filter(f => !omitted.value.includes(f.webkitRelativePath || f.name)))
  if (!receipts.value.length) target.value = groups.value[0]?.target || ''
}
async function templates() {
  templateBusy.value = true; templateError.value = ''
  try { await downloadImportTemplatePack(session.workspaceCollegeId) }
  catch (e) { templateError.value = e instanceof Error ? e.message : '模板下载失败' }
  finally { templateBusy.value = false }
}
function saved(result: ImportSetResult) { groupBusy.value = false; intake.markSaved(target.value, result); emit('saved') }
function switchGroup(value: string) { if (!working.value) target.value = value }
</script>

<template>
  <section ref="container" class="center" aria-label="统一资料导入中心" data-unsaved-form>
    <header class="intro"><div><h2>添加资料，按类核对与保存</h2><p>{{ session.workspace?.name }} · {{ session.currentSemesterName }}。基础档案跨学期沿用，已有资料不必重导。</p></div><el-button :loading="templateBusy" :disabled="!catalog.length" @click="templates">下载标准模板包</el-button></header>
    <el-alert v-if="catalogError || templateError" :title="catalogError || templateError" type="error" :closable="false" />
    <div class="intake"><div class="pick-actions"><el-button type="primary" :disabled="working" @click="folderInput?.click()">选择文件夹</el-button><el-button :disabled="working" @click="zipInput?.click()">选择 ZIP 压缩包</el-button><el-button :disabled="working" @click="fileInput?.click()">选择文件／补充修正文件</el-button><span v-if="busy">正在识别资料…</span></div><p>可以混放教师档案、学生名单、责任表和课表。每次最多 20 个待处理表格，单文件／ZIP 不超过 10 MiB。</p><input ref="folderInput" type="file" webkitdirectory multiple class="native-file" @change="choose" /><input ref="zipInput" type="file" accept=".zip" multiple class="native-file" @change="choose" /><input ref="fileInput" type="file" accept=".xls,.xlsx,.csv" multiple class="native-file" @change="choose" /></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <details v-if="omitted.length"><summary>{{ omitted.length }} 个临时或非表格文件未选入</summary><p v-for="name in omitted" :key="name">{{ name }}</p></details>
    <template v-if="entries.length">
      <details class="file-types" :open="entries.some(e => (!e.target || e.blocked) && !e.excluded)"><summary>文件与资料类型（{{ entries.length }}）</summary><div v-for="entry in entries" :key="entry.id" class="source-row"><div><strong>{{ entry.filename }}</strong><p v-if="entry.archive_member">来自 {{ entry.source.name }}</p><p v-if="entry.message" :class="entry.blocked ? 'problem' : 'hint'">{{ entry.message }}</p></div><el-tag v-if="entry.saved" type="success">已保存</el-tag><template v-else><el-select :model-value="entry.target" placeholder="请选择资料类型" :disabled="working || entry.blocked || entry.excluded" @update:model-value="intake.changeType(entry.id, String($event))"><el-option v-for="kind in catalog" :key="kind.target" :label="kind.label" :value="kind.target" /></el-select><el-button link :disabled="working" @click="intake.exclude(entry.id)">{{ entry.excluded ? '重新纳入' : '本次不导入' }}</el-button></template></div></details>
      <p class="sequence">首次准备建议：① 教职工档案、学生名单 → ② 班级责任关系、课表 → ③ 补充名单、志愿者资格。已有档案可以直接复用。</p>
      <div class="groups" role="group" aria-label="资料分组"><button v-for="group in groups" :key="group.target" type="button" :disabled="working" :class="{ active: target === group.target }" @click="switchGroup(group.target)">{{ label(group.target) }}<span>{{ group.entries.filter(e => e.saved).length }}/{{ group.entries.length }} 文件已保存</span></button></div>
      <section v-if="active" class="group-workspace"><h3>{{ label(target) }}</h3><p class="hint">本组单独保存；其他组保存成功的资料会保留。若引用本次新增的教师、班级或学生，请先保存对应档案，再读取本组预览。</p><el-alert v-if="!pending.length" title="本组所选文件已保存，可切换下一组继续处理。" type="success" :closable="false" /><el-alert v-else-if="!canPreview" :title="blockReason" type="warning" :closable="false" />
        <ImportWizard v-else :key="`${context()}:${target}:${revision}`" :initial-target="target" :sources="sources" embedded @saved="saved" @busy="groupBusy = $event" />
      </section>
    </template>
    <ImportConflictHelp />
    <section v-if="receipts.length" class="saved"><h3>本次已保存的资料</h3><p v-for="file in receipts" :key="file.id">✓ {{ file.filename }}：{{ savedSummary(file.summary) }}</p><p class="hint">这些资料不会因后续组失败而撤销。课表发布给学生仍需单独确认。</p></section>
    <ImportIdentityReview v-if="receipts.length && session.hasPermission('academic.manage') && session.campusRuntime?.scheduling" />
  </section>
</template>

<style scoped>
.intro { display:flex;justify-content:space-between;align-items:flex-start;gap:20px; }.intro h2 { font-size:20px;margin-bottom:8px; }.intro p,.intake p,.hint,.sequence { font-size:13px;color:var(--ink-mute);line-height:1.8; }.intake { border:1px dashed var(--line-strong);padding:22px;margin:20px 0;background:var(--paper); }.pick-actions { display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px; }.native-file { display:none; }.source-row { display:flex;gap:16px;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--line); }.source-row > div:first-child { flex:1;min-width:0;overflow-wrap:anywhere; }.source-row strong { font-size:13px; }.source-row p { font-size:12px; }.source-row .el-select { width:240px; }.file-types summary { cursor:pointer;font-weight:600; }.sequence { margin:20px 0 12px; }.groups { display:flex;gap:8px;flex-wrap:wrap; }.groups button { background:var(--paper);border:1px solid var(--line);padding:12px 16px;cursor:pointer;text-align:left;color:var(--ink-soft); }.groups button.active { border-color:var(--ink);color:var(--ink);font-weight:600; }.groups button span { display:block;font-size:12px;font-weight:400;margin-top:5px;color:var(--ink-mute); }.group-workspace { border-top:1px solid var(--line);margin-top:20px;padding-top:20px; }.group-workspace h3,.saved h3 { font-size:16px;margin-bottom:8px; }.problem { color:var(--red,#b42318); }.saved { border-top:1px solid var(--line);padding-top:20px; }.saved p { font-size:13px;line-height:1.8; }.el-alert { margin:12px 0; }@media(max-width:700px) { .intro,.source-row { flex-direction:column;align-items:stretch; }.source-row .el-select { width:100%; }.pick-actions .el-button { margin-left:0; } }
</style>
