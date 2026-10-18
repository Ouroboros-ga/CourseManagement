<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import { useImportWizard } from '../../composables/useImportWizard'
import { listCourseTypes, type CourseType } from '../../api/campus'
import { listScopedAcademic, type ScopedAcademicRow } from '../../api/scopedAcademic'
import { downloadImportTemplateFile, type ImportPreviewResult, type ImportUploadSource, type ImportSetResult } from '../../api/importer'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import ImportIdentityReview from './ImportIdentityReview.vue'
import ImportReview from './ImportReview.vue'
import ImportConflictHelp from './ImportConflictHelp.vue'
import { savedSummary } from './importLabels'

const props = withDefaults(defineProps<{ initialTarget?: string; resumeBatch?: (ImportPreviewResult & { filename: string }) | null; sources?: ImportUploadSource[]; embedded?: boolean }>(), { initialTarget: 'grid_timetable', resumeBatch: null, embedded: false })
const emit = defineEmits<{ saved: [result: ImportSetResult]; busy: [value: boolean] }>()
const router = useRouter(), session = useSessionStore(), state = useImportWizard()
const { target, teachingClassId, courseTypeId, files, drafts, plan, result, busy, error, uploadErrors, failuresExcluded, canUpload, canConfirm, upload, review, confirm, removeDraft, reset, resume } = state
const options = computed(() => [
  ...(session.hasPermission('staff.manage') ? [{ id: 'faculty_staff', label: '教职工档案（首次准备）' }, { id: 'class_responsibility', label: '班级责任关系（工号模板／明确交接）' }, { id: 'teaching_assignment', label: '授课关系补充表（特殊情况）' }] : []),
  ...(session.hasPermission('course_schedule.import') ? [{ id: 'grid_timetable', label: '教务系统导出的班级课表' }, { id: 'timetable', label: '标准长表课表' }, { id: 'elective_course', label: '选修／分层补充资料' }] : []),
  ...(session.hasPermission('student.manage') ? [{ id: 'admin_roster', label: '行政班与学生名单' }, { id: 'class_duty', label: '班主任与责任区辅导员' }, { id: 'roster', label: '教学班补充名单' }] : []),
  ...(session.hasPermission('volunteer.manage') ? [{ id: 'volunteer', label: '志愿者资格名单' }] : [])
])
target.value = options.value.some(row => row.id === props.initialTarget) ? props.initialTarget : options.value[0]?.id || ''
const kind = computed({ get: () => target.value === 'timetable' ? 'grid_timetable' : target.value, set: value => { target.value = value } })
const isTimetable = computed(() => ['grid_timetable', 'timetable'].includes(target.value))
const templateKey = computed(() => target.value === 'grid_timetable' ? 'timetable' : target.value)
const hasPreview = computed(() => !!drafts.value.length || !!plan.value)
const form = ref<HTMLElement | null>(null), folderInput = ref<HTMLInputElement | null>(null), fileInput = ref<HTMLInputElement | null>(null), zipInput = ref<HTMLInputElement | null>(null)
const skippedFiles = ref<string[]>([]), selectingError = ref(''), templateBusy = ref(false)
const courseTypes = ref<CourseType[]>([]), courseTypeError = ref('')
let typeRequest = 0
watch(() => session.workspaceCollegeId, async cid => {
  const request = ++typeRequest
  courseTypes.value = []; courseTypeError.value = ''
  courseTypeId.value = ''
  if (!cid) return
  try {
    const rows = await listCourseTypes(cid)
    if (request !== typeRequest || cid !== session.workspaceCollegeId) return
    courseTypes.value = rows.filter(row => row.status === 'ACTIVE')
    const regular = courseTypes.value.find(row => row.code === 'builtin_regular')
    if (regular && !files.value.length && !drafts.value.length && !props.resumeBatch) courseTypeId.value = regular.id
  } catch { if (request === typeRequest) courseTypeError.value = '课程类型读取失败，请在更多设置中检查。' }
}, { immediate: true })
watch(() => [session.currentUser?.id, session.workspaceCollegeId, session.currentSemesterId, target.value].join(':'), () => {
  selectingError.value = ''; skippedFiles.value = []
})
watch(busy, value => emit('busy', value), { immediate: true })
watch(result, value => { if (value) { markWorkspaceSaved(form.value); emit('saved', value) } })
watch(() => props.sources, sources => { if (sources) files.value = sources.map(source => source.file) }, { immediate: true })
watch(() => props.resumeBatch, async batch => {
  if (!batch || busy.value) return
  if ((files.value.length || drafts.value.length) && !result.value) {
    try { await ElMessageBox.confirm('当前尚未导入的文件将被替换，是否继续核对这条记录？', '继续未完成导入', { confirmButtonText: '继续核对', cancelButtonText: '保留当前文件' }) }
    catch { return }
  }
  selectingError.value = ''; skippedFiles.value = []
  await resume(batch)
})
function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement, chosen = Array.from(input.files || [])
  input.value = ''
  if (!chosen.length) return
  const accepted = chosen.filter(file => !file.name.startsWith('.') && !file.name.startsWith('~$') && /\.(xlsx?|csv|zip)$/i.test(file.name))
  skippedFiles.value = chosen.filter(file => !accepted.includes(file)).map(file => file.webkitRelativePath || file.name)
  selectingError.value = accepted.length > 20 ? `选中了 ${accepted.length} 个表格/压缩包，每次最多 20 个。请分批选择。` : !accepted.length ? '没有找到 Excel、CSV 或 ZIP 文件，请重新选择。' : ''
  files.value = accepted
}
async function uploadAndReview() { await upload(props.sources); if (drafts.value.length) await review() }
async function removeFile(id: string) { removeDraft(id); if (drafts.value.length) await review() }
async function template() {
  templateBusy.value = true
  try { await downloadImportTemplateFile(templateKey.value) }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : '模板下载失败') }
  finally { templateBusy.value = false }
}
function restart() {
  reset(); skippedFiles.value = []; selectingError.value = ''
  if (props.sources) files.value = props.sources.map(source => source.file)
}
const teachingClasses = ref<ScopedAcademicRow[]>([]), classBusy = ref(false), classError = ref('')
let classRequest = 0
async function searchClasses(keyword: string) {
  const request = ++classRequest, cid = session.workspaceCollegeId, sid = session.currentSemesterId
  if (!cid || !sid) return
  classBusy.value = true; classError.value = ''
  try {
    const response = await listScopedAcademic(cid, 'teaching-classes', 1, keyword, sid)
    if (request === classRequest && cid === session.workspaceCollegeId && sid === session.currentSemesterId) teachingClasses.value = response.items
  } catch { if (request === classRequest) classError.value = '教学班读取失败，请重新搜索。' }
  finally { if (request === classRequest) classBusy.value = false }
}
function classesOpened(value: boolean) { if (value) void searchClasses('') }
</script>

<template>
  <section ref="form" class="import-workspace" aria-label="批量导入资料" data-unsaved-form v-loading="busy">
    <template v-if="!result">
      <div v-if="!embedded" class="import-context"><label for="import-kind">导入什么</label><el-select id="import-kind" v-model="kind" aria-label="导入资料类型" :disabled="busy || hasPreview" style="width:290px"><el-option v-for="row in options" :key="row.id" :label="row.label" :value="row.id" /></el-select><span class="hint">{{ session.workspace?.name }}<template v-if="!['admin_roster', 'class_duty', 'faculty_staff', 'class_responsibility'].includes(target)"> · {{ session.currentSemesterName }}</template></span><el-button link :loading="templateBusy" @click="template">下载填写模板</el-button></div>
      <div v-if="!hasPreview && !embedded" class="upload-area"><h2>把要导入的文件选进来</h2><p>{{ isTimetable ? '直接使用教务系统导出的班级课表，不用逐班上传。' : '同一种资料可以一次选择多个文件。' }}</p><div class="pick-actions"><el-button type="primary" size="large" @click="folderInput?.click()">选择文件夹</el-button><el-button size="large" @click="zipInput?.click()">选择 ZIP 压缩包</el-button><el-button size="large" @click="fileInput?.click()">选择多个文件</el-button></div>
        <input ref="folderInput" class="native-file" type="file" webkitdirectory multiple aria-label="选择导入文件夹" @change="selectFiles" /><input ref="zipInput" class="native-file" type="file" accept=".zip" multiple aria-label="选择 ZIP 压缩包" @change="selectFiles" /><input ref="fileInput" class="native-file" type="file" accept=".xlsx,.xls,.csv" multiple aria-label="选择多个表格" @change="selectFiles" />
        <p class="hint">支持子文件夹；ZIP 内请放同一种资料。每批最多 20 个表格，单文件或压缩包不超过 10 MiB。</p>
      </div>
      <el-alert v-if="selectingError" :title="selectingError" type="warning" :closable="false" /><details v-if="skippedFiles.length" class="hint"><summary>{{ skippedFiles.length }} 个非表格或临时文件未选入</summary><p v-for="name in skippedFiles" :key="name">{{ name }}</p></details>
      <div v-if="files.length && !hasPreview" class="selected-files"><strong>已选择 {{ files.length }} 个文件{{ files.some(f => /\.zip$/i.test(f.name)) ? '（压缩包将在下一步展开）' : '' }}</strong><ul><li v-for="(file, index) in files" :key="index">{{ file.webkitRelativePath || file.name }}</li></ul></div>
      <div v-if="target === 'roster' && !hasPreview" class="setting-row"><label>对应教学班</label><el-select v-model="teachingClassId" filterable remote :remote-method="searchClasses" :loading="classBusy" placeholder="搜索本学期教学班" @visible-change="classesOpened"><el-option v-for="row in teachingClasses" :key="row.id" :value="row.id" :label="String(row.class_name || row.class_code || row.id)" /></el-select><p v-if="classError" role="alert">{{ classError }}</p></div>
      <details v-if="isTimetable && !hasPreview" class="advanced"><summary>其他格式与课程类型</summary><div v-if="!embedded" class="setting-row"><span>文件格式</span><el-radio-group v-model="target"><el-radio value="grid_timetable">教务系统原表</el-radio><el-radio value="timetable">按平台模板填写的表格</el-radio></el-radio-group></div><div class="setting-row"><span>课程类型</span><el-select v-model="courseTypeId" placeholder="普通课（系统默认）" clearable><el-option v-for="row in courseTypes" :key="row.id" :value="row.id" :label="row.name" /></el-select></div><p v-if="courseTypeError" role="alert">{{ courseTypeError }}</p></details>
      <el-alert v-if="error" :title="error" type="error" :closable="false" /><div v-if="!hasPreview" class="parse-action"><el-button type="primary" size="large" :disabled="!canUpload || busy || !!selectingError" @click="uploadAndReview">读取文件并预览</el-button><span class="hint">这一步只读取文件，不会保存正式资料。</span></div>
      <ImportReview v-if="hasPreview" :plan="plan" :drafts="drafts" :upload-errors="uploadErrors" :failures-excluded="failuresExcluded" :busy="busy" :can-confirm="canConfirm" @remove="removeFile" @retry="review" @restart="restart" @confirm="confirm" @exclude-failures="state.excludeUploadFailures" /><el-alert v-for="message in !hasPreview ? uploadErrors : []" :key="message" :title="message" type="error" :closable="false" />
    </template>
    <el-result v-else icon="success" title="导入完成" sub-title="下列文件已保存。课表发布给学生仍需单独确认。"><template #extra><p v-for="file in result.files" :key="file.id">{{ file.filename }}：{{ savedSummary(file.summary) }}</p><el-button v-if="isTimetable" type="primary" @click="router.push('/dashboard/academic?tab=timetable')">查看课表</el-button><el-button @click="restart">继续导入其他文件</el-button></template></el-result>
    <ImportIdentityReview v-if="result && isTimetable && session.hasPermission('academic.manage') && session.campusRuntime?.scheduling" />
    <ImportConflictHelp v-if="!embedded" />
  </section>
</template>

<style scoped>
.import-context,.pick-actions,.parse-action,.setting-row { display:flex;align-items:center;gap:12px;flex-wrap:wrap; }.import-context { margin:12px 0 20px; }.import-context label { font-weight:600; }.hint { color:var(--ink-mute);font-size:12px; }.upload-area { background:var(--paper);border:1px dashed var(--line-strong);padding:26px; }.upload-area h2 { font-size:18px;margin-bottom:6px; }.upload-area p { color:var(--ink-soft); }.pick-actions { margin:18px 0 12px; }.native-file { display:none; }.selected-files { margin:16px 0; }.selected-files ul { max-height:150px;overflow:auto;list-style:disc;padding-left:22px;margin-top:8px; }.selected-files li { font-size:13px;line-height:1.8;overflow-wrap:anywhere; }.advanced { margin:18px 0;color:var(--ink-soft);font-size:13px; }.advanced summary { cursor:pointer; }.setting-row { margin:14px 0; }.parse-action { margin:20px 0; }.el-alert { margin:12px 0; }@media(max-width:700px) { .upload-area { padding:18px; }.pick-actions { align-items:stretch; }.pick-actions .el-button { margin-left:0; } }
</style>
