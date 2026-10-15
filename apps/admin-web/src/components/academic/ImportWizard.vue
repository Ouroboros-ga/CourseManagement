<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useSessionStore } from '../../stores/session'
import { useImportWizard } from '../../composables/useImportWizard'
import { listScopedAcademic, type ScopedAcademicRow } from '../../api/scopedAcademic'
import { ElMessageBox } from 'element-plus'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import ImportIdentityReview from './ImportIdentityReview.vue'
const session = useSessionStore()
const { target, teachingClassId, files, drafts, selectedIds, plan, result, busy, error, uploadErrors, canUpload, upload, review, confirm } = useImportWizard()
const teachingClasses = ref<ScopedAcademicRow[]>([]), classBusy = ref(false)
const classError = ref(''), form = ref<HTMLElement | null>(null)
watch(result, value => { if (value) markWorkspaceSaved(form.value) })
const changePages = ref<Record<string, number>>({})
const options = computed(() => [
  ...(session.hasPermission('student.manage') ? [{ id: 'admin_roster', label: '行政班与学生名单' }, { id: 'roster', label: '教学班补充名单' }] : []),
  ...(session.hasPermission('course_schedule.import') ? [{ id: 'grid_timetable', label: '教务网格课表' }] : []),
  ...(session.hasPermission('course_schedule.import') ? [{ id: 'timetable', label: '标准课表长表' }, { id: 'elective_course', label: '选修课与分层课' }] : []),
  ...(session.hasPermission('volunteer.manage') ? [{ id: 'volunteer', label: '志愿者学期资格' }] : [])
])
if (!options.value.some(row => row.id === target.value)) target.value = options.value[0]?.id || ''
const enabled = computed(() => !!session.campusRuntime?.business_scoped && session.hasPermission('import.execute'))
const step = computed(() => result.value ? 3 : plan.value ? 2 : drafts.value.length ? 1 : 0)
function fileChanged(event: Event) {
  const input = event.target as HTMLInputElement
  files.value = Array.from(input.files || [])
  input.value = ''
}
let classRequest = 0
async function searchClasses(keyword: string) {
  const requestId = ++classRequest, cid = session.workspaceCollegeId, sid = session.currentSemesterId
  if (!cid || !sid) return
  classBusy.value = true
  classError.value = ''
  try {
    const response = await listScopedAcademic(cid, 'teaching-classes', 1, keyword, sid)
    if (requestId === classRequest && cid === session.workspaceCollegeId && sid === session.currentSemesterId) teachingClasses.value = response.items
  } catch (e) { if (requestId === classRequest) classError.value = e instanceof Error ? e.message : '教学班加载失败' }
  finally { if (requestId === classRequest) classBusy.value = false }
}
function classesOpened(open: boolean) { if (open) void searchClasses('') }
async function save() {
  try {
    await ElMessageBox.confirm(`将一次保存选中的 ${plan.value?.batch_ids.length || 0} 个文件。任一阻断问题会使本集合整批不保存；未出现的名单行不会删除。`, '确认导入', { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '返回核对' })
    await confirm()
  } catch { /* 取消确认时保留已核对草稿。 */ }
}
const actionLabels = { CREATE: '新增', UPDATE: '更新', UNCHANGED: '不变／已处理' }
const entityLabels: Record<string, string> = { student: '学生', qualification: '学期资格', schedule: '课表', roster_member: '名单成员', class_duties: '班级负责人', class_metadata: '班级资料' }
const fieldLabels: Record<string, string> = { enabled: '启用', present: '在名单中', name: '姓名', class_name: '班级名称', class_code: '教学班码', course_code: '课程代码', course_name: '课程名称', weekday: '星期', start_period: '开始节次', end_period: '结束节次', weeks: '周次', classroom: '教室', teacher: '教师', head_teacher: '班主任', counselor: '辅导员', college: '学院', grade_year: '年级', student_nos: '学号' }
function describe(value: Record<string, unknown> | null) {
  if (!value) return '无原资料'
  return Object.entries(value).filter(([key]) => fieldLabels[key]).map(([key, val]) =>
    `${fieldLabels[key]}：${typeof val === 'boolean' ? val ? '是' : '否' : Array.isArray(val) ? val.join('、') : val ?? '未记录'}`).join('\n')
}
function savedSummary(summary: Record<string, unknown>) {
  const labels: Record<string, string> = { classes_created: '新增行政班', students_created: '新增学生', students_updated: '核对学生', courses_created: '新增课程', course_created: '新增课程', teaching_classes_created: '新增教学班', teaching_class_created: '新增教学班', schedules_created: '新增课表', schedule_created: '新增课表', qualification_created: '新增资格', qualification_updated: '更新资格', roster_after: '保存后名单人数', students_linked: '关联学生' }
  if (summary.unchanged) return '资料未变化，已跳过重复写入'
  return Object.entries(summary).filter(([key]) => labels[key]).map(([key, value]) => `${labels[key]} ${value}`).join('；') || '资料已保存'
}
</script>
<template>
  <section v-loading="busy" aria-label="教务导入向导">
    <el-alert v-if="!session.hasPermission('import.execute')" title="当前账号没有导入执行权限，请联系学院教师管理员。" type="warning" :closable="false" />
    <el-alert v-else-if="!enabled" title="新导入向导需要启用学院正式业务。当前可使用下方旧兼容入口，其批量导入逐文件保存，不保证跨文件整批回滚。" type="warning" :closable="false" />
    <el-alert v-else title="上传只生成草稿；核对具体新增、变更和问题后再明确保存。行政班与学生名单应先完成，课表再作为下一批导入。" type="info" :closable="false" />
    <el-steps :active="step" simple class="steps"><el-step title="上传解析" /><el-step title="选定文件" /><el-step title="核对确认" /><el-step title="保存结果" /></el-steps>
    <div ref="form" class="upload-form" data-unsaved-form>
      <label>资料类型 <el-select v-model="target" :disabled="busy || !enabled"><el-option v-for="row in options" :key="row.id" :value="row.id" :label="row.label" /></el-select></label>
      <label v-if="target === 'roster'">目标教学班 <el-select v-model="teachingClassId" filterable remote :remote-method="searchClasses" :loading="classBusy" placeholder="搜索本学期教学班" @visible-change="classesOpened"><el-option v-for="row in teachingClasses" :key="row.id" :value="row.id" :label="String(row.class_name || row.class_code || row.id)" /></el-select></label>
      <el-alert v-if="classError" :title="classError" type="error" :closable="false" />
      <input type="file" multiple accept=".xlsx,.xls,.csv" aria-label="选择导入文件" :disabled="busy || !enabled" @change="fileChanged" />
      <p class="hint">最多 20 个文件，每个不超过 10 MiB；一次核对最多 5000 条变更（以服务器配置为准）。本入口不自动解压 ZIP。</p>
      <p v-for="file in files" :key="file.name">{{ file.name }} · {{ Math.ceil(file.size / 1024) }} KiB</p>
      <el-button type="primary" :disabled="!canUpload || !enabled || busy" @click="upload">上传并解析草稿</el-button>
    </div>
    <el-alert v-for="message in uploadErrors" :key="message" :title="message + '；该文件未进入确认集合'" type="error" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="drafts.length" class="selection">
      <h3>明确选择本次保存的文件</h3>
      <el-checkbox-group v-model="selectedIds" :disabled="busy || !!result"><el-checkbox v-for="draft in drafts" :key="draft.id" :value="draft.id">{{ draft.filename }}{{ draft.can_confirm ? '' : '（解析有问题，需核对）' }}</el-checkbox></el-checkbox-group>
      <el-button :disabled="!selectedIds.length || busy || !!result" @click="review">核对选中的 {{ selectedIds.length }} 个文件</el-button>
    </div>
    <template v-if="plan && !result">
      <el-alert :title="plan.impact_note" type="info" :closable="false" />
      <el-card v-for="file in plan.files" :key="file.id" class="file-card">
        <h3>{{ file.filename }} · {{ file.changes.length }} 条核对项</h3>
        <p v-for="(issue, index) in file.issues.slice(0, 50)" :key="index" :class="issue.severity === 'error' ? 'issue-error' : 'hint'">{{ issue.severity === 'error' ? '阻断' : '提示' }} · {{ issue.row ? '第 ' + issue.row + ' 行 · ' : '' }}{{ issue.field || '' }} {{ issue.message }}</p>
        <p v-if="file.issues.length > 50">共 {{ file.issues.length }} 个问题，此处展示前 50 项；修正文件后重新上传。</p>
        <el-table :data="file.changes.slice(((changePages[file.id] || 1) - 1) * 30, (changePages[file.id] || 1) * 30)" empty-text="无可应用条目">
          <el-table-column label="处理" width="120"><template #default="{ row }">{{ actionLabels[row.action as keyof typeof actionLabels] }}</template></el-table-column>
          <el-table-column label="对象" width="110"><template #default="{ row }">{{ entityLabels[row.entity] || row.entity }}</template></el-table-column>
          <el-table-column prop="key" label="资料标识" min-width="160" />
          <el-table-column label="来源" min-width="140"><template #default="{ row }">{{ row.source.sheet || '首表／文本' }}{{ row.source.row ? ' · 第 ' + row.source.row + ' 行' : ' · 按标识定位' }}{{ row.source.column ? ' · 列 ' + row.source.column : '' }}</template></el-table-column>
          <el-table-column label="核对详情" min-width="200"><template #default="{ row }"><details><summary>查看前后资料</summary><pre>原：{{ describe(row.before) }}
新：{{ describe(row.after) }}</pre></details></template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="changePages[file.id]" :page-size="30" :total="file.changes.length" layout="prev, pager, next, total" />
      </el-card>
      <el-alert v-if="!plan.can_confirm" title="存在阻断问题，不能保存。修正后重新上传，或明确取消选择有问题的文件，再重新核对集合。" type="error" :closable="false" />
      <el-button type="primary" :disabled="!plan.can_confirm || busy" @click="save">确认保存本次集合</el-button>
    </template>
    <el-result v-if="result" icon="success" title="本次确认集合已保存" sub-title="重复请求不会重复导入。正式发布仍需在“发布给学生”中单独确认。">
      <template #extra><p v-for="file in result.files" :key="file.id">{{ file.filename }} · {{ savedSummary(file.summary) }}</p><router-link to="/dashboard/academic?tab=timetable">核对正式课表</router-link></template>
    </el-result>
    <ImportIdentityReview v-if="result && ['timetable', 'grid_timetable', 'elective_course'].includes(target) && session.hasPermission('academic.manage') && session.campusRuntime?.scheduling" />
  </section>
</template>
<style scoped>
.steps,.upload-form,.selection,.file-card { margin: 20px 0; }.upload-form label { display: flex; align-items: center; gap: 12px; margin: 12px 0; }.el-select { max-width: 380px; width: 100%; }.hint { color: var(--ink-mute); font-size: 12px; }.issue-error { color: var(--red); }.selection .el-checkbox-group { margin-bottom: 14px; }pre { white-space: pre-wrap; word-break: break-word; max-width: 420px; font-size: 12px; }.el-pagination { margin-top: 14px; }
</style>
