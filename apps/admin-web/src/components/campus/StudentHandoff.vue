<script setup lang="ts">
import { ref, reactive, watch, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ContextEpoch } from '../../utils/contextEpoch'
import { listScopedData } from '../../api/campus'
import { enrollmentHistory, previewEnrollment, applyEnrollment, cancelEnrollment, previewStudentFile, confirmStudentFile, exportStudentFile, pendingHandoffTasks, reviewHandoffTask, type HandoffTask, type EnrollmentCommand, type EnrollmentHistory, type DataPlan } from '../../api/enrollment'
import { listWorkspaces, type College } from '../../api/campus'
import TaskDrawer from '../TaskDrawer.vue'
import { getTask, type InspectionTaskItem } from '../../api/tasks'
const viewedTask = ref<InspectionTaskItem | null>(null), drawerVisible = ref(false)
async function viewTask(id: string) {
  try { viewedTask.value = await getTask(id); drawerVisible.value = true }
  catch (e) { error.value = e instanceof Error ? e.message : '任务读取失败' }
}
const props = defineProps<{ collegeId: string }>()
const epoch = new ContextEpoch(() => props.collegeId)
const busy = ref(false), error = ref(''), includeArchive = ref(false)
const students = ref<{ id: string; name: string; student_no: string }[]>([]), classes = ref<{ id: string; class_name: string }[]>([])
const selected = ref(''), history = ref<EnrollmentHistory | null>(null), preview = ref<Record<string, unknown> | null>(null)
const purpose = ref('INCREMENTAL'), plan = ref<DataPlan | null>(null)
const form = reactive({ kind: 'TRANSFER' as EnrollmentCommand['kind'], effective_date: '', target_class_id: '', reason: '', correct_existing: false })
const targetCollege = ref(props.collegeId), targetColleges = ref<College[]>([]), pendingTasks = ref<HandoffTask[]>([])
const actionLabels: Record<string, string> = { CREATE: '新建学生', UPDATE_NAME: '更新姓名', UNCHANGED: '保持现状', ENROLLMENT_CHANGE: '办理学籍异动', STALE_SOURCE: '旧版本，保持现状', TRANSFER_REQUIRES_CHANGE: '须办理转班', LIFECYCLE_REQUIRES_CHANGE: '须办理学籍变更' }
const statusLabels: Record<string, string> = { ENROLLED: '在读', SUSPENDED: '休学', GRADUATED: '毕业', WITHDRAWN: '退学', TRANSFER: '转班 / 转专业', RETURN: '复学', SUSPEND: '休学', GRADUATE: '毕业', WITHDRAW: '退学', SCHEDULED: '待生效', APPLIED: '已生效', CANCELED: '已撤销' }
function impactText(value: Record<string, unknown>) {
  const labels: Record<string, string> = { existing_roster_task_ids: '涉及任务', refreshed_task_ids: '未来名单已更新', protected_task_ids: '冻结历史保留', withdrawn_assignment_task_ids: '原受派已撤销', manual_roster_review_task_ids: '需教师复核' }
  return Object.entries(labels).filter(([key]) => Array.isArray(value[key])).map(([key, label]) => `${label}：${(value[key] as unknown[]).length} 项`).join('；') || '身份绑定与历史事实保留；选修课按明确退课清单处理。'
}
async function loadPending() {
  const cid = props.collegeId
  try { const response = await pendingHandoffTasks(); if (props.collegeId === cid) pendingTasks.value = response.items.filter(t => t.college_id === cid) }
  catch (e) { error.value = e instanceof Error ? e.message : '复核列表加载失败' }
}
async function loadTargetClasses() {
  const cid = targetCollege.value
  try { const result = await listScopedData(cid, 'administrative-classes', { page_size: 100 }); if (cid === targetCollege.value) classes.value = result.items as typeof classes.value }
  catch (e) { error.value = e instanceof Error ? e.message : '目标班级加载失败' }
}
async function review(task: HandoffTask) {
  try { await ElMessageBox.confirm('请先在任务详情核对冻结名单和当前应到人数。确认后沿用现有名单与人数，并解除提交等待；不会改写历史快照。', '确认任务交接'); await reviewHandoffTask(task); await loadPending() }
  catch (e) { if (e instanceof Error) error.value = e.message }
}
let command: EnrollmentCommand | null = null
let previewRevision = 0
async function load(query = '') {
  const ticket = epoch.begin()
  try {
    const [s, c] = await Promise.all([listScopedData(props.collegeId, 'students', { query, page_size: 100 }), listScopedData(props.collegeId, 'administrative-classes', { page_size: 100 })])
    if (ticket.isCurrent()) { students.value = s.items as typeof students.value; classes.value = c.items as typeof classes.value; error.value = '' }
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '加载失败' }
}
async function loadHistory() {
  const id = selected.value, cid = props.collegeId
  history.value = null; preview.value = null; command = null
  if (!id) return
  try { const result = await enrollmentHistory(id); if (selected.value === id && props.collegeId === cid) history.value = result }
  catch (e) { error.value = e instanceof Error ? e.message : '历史加载失败' }
}
async function prepare() {
  if (!history.value || !form.effective_date) { ElMessage.warning('请选择学生与生效日期'); return }
  command = { kind: form.kind, effective_date: form.effective_date, target_class_id: ['TRANSFER', 'RETURN'].includes(form.kind) ? form.target_class_id || null : null, lock_version: history.value.lock_version, idempotency_key: crypto.randomUUID(), reason: form.reason || null, correct_existing: form.correct_existing }
  busy.value = true
  const revision = ++previewRevision, prepared = command
  const id = selected.value, cid = props.collegeId
  try { const result = await previewEnrollment(id, prepared); if (id === selected.value && cid === props.collegeId && revision === previewRevision && command === prepared) preview.value = result }
  catch (e) { error.value = e instanceof Error ? e.message : '预览失败' }
  finally { busy.value = false }
}
async function commit() {
  if (!command || !preview.value) return
  busy.value = true
  try { await applyEnrollment(selected.value, command); ElMessage.success('异动已记录，具体交接结果见历史'); await loadHistory(); await load() }
  catch (e) { preview.value = null; command = null; error.value = e instanceof Error ? e.message : '保存失败，请重新预览' }
  finally { busy.value = false }
}
async function cancel(id: string) {
  if (!history.value) return
  try { await ElMessageBox.confirm('撤销尚未生效的计划，并恢复未来名单？', '撤销计划'); await cancelEnrollment(selected.value, id, history.value.lock_version); await loadHistory() }
  catch (e) { if (e instanceof Error) error.value = e.message }
}
async function fileSelected(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  busy.value = true; plan.value = null
  const cid = props.collegeId
  try { const result = await previewStudentFile(cid, file, purpose.value); if (props.collegeId === cid) plan.value = result }
  catch (e) { error.value = e instanceof Error ? e.message : '文件预览失败' }
  finally { busy.value = false; input.value = '' }
}
async function confirm() {
  if (!plan.value) return
  busy.value = true
  try { await confirmStudentFile(plan.value); plan.value = null; ElMessage.success('整批已确认，缺失学生未自动归档'); await load() }
  catch (e) { plan.value = null; error.value = e instanceof Error ? e.message : '确认失败，请重新预览' }
  finally { busy.value = false }
}
async function download() {
  try { const blob = await exportStudentFile(props.collegeId, includeArchive.value); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = '学生交接.xlsx'; a.click(); URL.revokeObjectURL(url) }
  catch (e) { error.value = e instanceof Error ? e.message : '导出失败' }
}
watch(() => props.collegeId, () => { selected.value = ''; history.value = null; preview.value = null; plan.value = null; targetCollege.value = props.collegeId; void load(); void loadPending(); void listWorkspaces().then(rows => { targetColleges.value = rows }) }, { immediate: true })
watch(targetCollege, () => { form.target_class_id = ''; void loadTargetClasses() })
watch(selected, loadHistory)
watch(form, () => { ++previewRevision; preview.value = null; command = null }, { deep: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <div v-loading="busy">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <h3>学生数据交接</h3><p>导出保留学号、班级编码与版本。全量比较缺行仅列为待核对，转班和复学须走明确异动。</p>
    <el-checkbox v-model="includeArchive">包含离校归档</el-checkbox><el-button @click="download">导出交接模板</el-button>
    <el-select v-model="purpose" @change="plan = null"><el-option label="增量更新" value="INCREMENTAL" /><el-option label="全量比较" value="FULL_COMPARE" /><el-option label="明确学籍异动" value="ENROLLMENT_CHANGE" /></el-select>
    <input aria-label="选择学生交接文件" type="file" accept=".xlsx,.zip" :disabled="busy" @change="fileSelected" />
    <template v-if="plan"><p>缺失学生 {{ plan.missing_student_ids.length }} 人，仅待核对。</p><el-table :data="plan.rows" max-height="300"><el-table-column prop="student_no" label="学号" /><el-table-column prop="name" label="姓名" /><el-table-column label="计划操作"><template #default="{ row }">{{ actionLabels[row.action] || row.action }}</template></el-table-column></el-table><el-alert v-if="plan.errors?.length" :title="`有 ${plan.errors.length} 项资料错误，整批不能确认，请核对文件后重新预览。`" type="error" /><el-button type="primary" :disabled="!!plan.errors?.length" @click="confirm">确认整批应用</el-button></template>
    <h3>任务交接待复核</h3><el-button @click="loadPending">刷新复核清单</el-button><el-table :data="pendingTasks"><el-table-column prop="inspection_date" label="查课日期" /><el-table-column prop="course_name" label="课程" /><el-table-column prop="class_name" label="教学班" /><el-table-column prop="expected_count_current" label="当前应到" /><el-table-column label="操作"><template #default="{ row }"><el-button link @click="viewTask(row.id)">核对任务详情</el-button> <el-button link @click="review(row)">确认沿用当前名单与人数</el-button></template></el-table-column></el-table>
    <el-collapse v-if="plan?.missing_students?.length"><el-collapse-item title="待核对缺失学生（不会自动删除或归档）"><el-table :data="plan.missing_students"><el-table-column prop="student_no" label="学号" /><el-table-column prop="name" label="姓名" /><el-table-column label="操作"><template #default="{ row }"><el-button link @click="load(row.student_no).then(() => { selected = row.id })">查看并办理异动</el-button></template></el-table-column></el-table></el-collapse-item></el-collapse>
    <TaskDrawer v-model:visible="drawerVisible" :task="viewedTask" @corrected="loadPending" />
    <h3>办理学籍异动</h3>
    <el-select v-model="selected" filterable remote :remote-method="load" placeholder="搜索学生姓名或学号"><el-option v-for="s in students" :key="s.id" :value="s.id" :label="`${s.name}（${s.student_no}）`" /></el-select>
    <el-select v-model="form.kind"><el-option label="转班 / 转专业" value="TRANSFER" /><el-option label="休学" value="SUSPEND" /><el-option label="复学" value="RETURN" /><el-option label="毕业" value="GRADUATE" /><el-option label="退学" value="WITHDRAW" /></el-select>
    <el-date-picker v-model="form.effective_date" value-format="YYYY-MM-DD" placeholder="生效日期" />
    <el-select v-if="['TRANSFER', 'RETURN'].includes(form.kind)" v-model="targetCollege"><el-option v-for="c in targetColleges" :key="c.id" :value="c.id" :label="c.name" /></el-select>
    <el-select v-if="['TRANSFER', 'RETURN'].includes(form.kind)" v-model="form.target_class_id" filterable placeholder="目标行政班"><el-option v-for="c in classes" :key="c.id" :value="c.id" :label="c.class_name" /></el-select>
    <el-input v-model="form.reason" placeholder="说明（选填）" maxlength="512" />
    <el-checkbox v-model="form.correct_existing">回溯更正已有区间，保留后续学籍与原历史证据</el-checkbox>
    <el-button :disabled="!history" @click="prepare">预览影响</el-button>
    <template v-if="preview"><p>生效日期：{{ preview.effective_date }}。{{ impactText((preview.impact || {}) as Record<string, unknown>) }}</p><p>已完成、已开始或已有截止事实的任务保留原快照；旧名单不会覆盖本次异动。</p><el-button type="primary" @click="commit">确认此预览的异动</el-button></template>
    <template v-if="history"><h4>学籍与交接历史</h4><el-table :data="history.enrollments"><el-table-column label="区间效力"><template #default="{ row }">{{ row.superseded ? '已撤销 / 已更正' : '有效区间' }}</template></el-table-column><el-table-column prop="effective_from" label="开始日期" /><el-table-column prop="effective_to" label="结束日期" /><el-table-column label="状态"><template #default="{ row }">{{ statusLabels[row.status] || row.status }}</template></el-table-column><el-table-column label="学院 / 班级"><template #default="{ row }">{{ row.snapshot.college_name || '归属待核实' }} / {{ row.snapshot.class_name || '班级待核实' }}</template></el-table-column><el-table-column label="历史核实"><template #default="{ row }">{{ row.historical_confirmed ? '已确认' : '仅当前基线，过去未核实' }}</template></el-table-column></el-table><el-table :data="history.changes"><el-table-column label="异动"><template #default="{ row }">{{ statusLabels[row.kind] || row.kind }}</template></el-table-column><el-table-column prop="effective_date" label="生效日期" /><el-table-column label="状态"><template #default="{ row }">{{ statusLabels[row.state] || row.state }}</template></el-table-column><el-table-column label="交接影响"><template #default="{ row }"><p>{{ impactText(row.impact) }}</p><el-button v-if="row.state === 'SCHEDULED'" link @click="cancel(row.id)">撤销未来计划</el-button></template></el-table-column></el-table></template>
  </div>
</template>
<style scoped>h3 { margin-top: 24px; } .el-select { margin: 8px; width: 240px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; font-size: 12px; }</style>
