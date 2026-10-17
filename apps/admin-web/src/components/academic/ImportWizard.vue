<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../../stores/session'
import { useImportWizard } from '../../composables/useImportWizard'
import { listCourseTypes, type CourseType } from '../../api/campus'
import { listScopedAcademic, type ScopedAcademicRow } from '../../api/scopedAcademic'
import { downloadImportTemplateFile } from '../../api/importer'
import { ElMessage, ElMessageBox } from 'element-plus'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import ImportIdentityReview from './ImportIdentityReview.vue'
import { previewSummary, savedSummary, targetLabels } from './importLabels'

const props = withDefaults(defineProps<{ initialTarget?: string }>(), { initialTarget: 'admin_roster' })
const emit = defineEmits<{ back: [] }>()

const router = useRouter()
const session = useSessionStore()
const { target, teachingClassId, courseTypeId, files, drafts, plan, result, busy, error, uploadErrors, canUpload, upload, review, confirm, removeDraft } = useImportWizard()
const teachingClasses = ref<ScopedAcademicRow[]>([]), classBusy = ref(false)
const classError = ref(''), form = ref<HTMLElement | null>(null)
const downloadingTemplate = ref(false)
const courseTypes = ref<CourseType[]>([])

target.value = props.initialTarget

const isTimetable = computed(() => ['grid_timetable', 'timetable'].includes(target.value))
const displayTitle = computed(() => (isTimetable.value ? '本学期教务课表' : targetLabels[target.value] || '导入资料'))
const step = computed(() => (result.value ? 3 : plan.value ? 1 : 0))

async function loadCourseTypes() {
  if (!session.workspaceCollegeId) return
  try {
    const list = await listCourseTypes(session.workspaceCollegeId)
    courseTypes.value = list.filter(t => t.status === 'ACTIVE')
    const regular = courseTypes.value.find(t => t.code === 'builtin_regular' || t.name === '普通课')
    if (regular) {
      courseTypeId.value = regular.id
    } else if (courseTypes.value.length > 0 && !courseTypeId.value) {
      courseTypeId.value = courseTypes.value[0].id
    }
  } catch (e) {
    console.error('加载课程类型失败', e)
  }
}
watch(() => session.workspaceCollegeId, loadCourseTypes, { immediate: true })

watch(result, value => { if (value) markWorkspaceSaved(form.value) })
const changePages = ref<Record<string, number>>({})

const templateKey = computed(() => {
  if (target.value === 'grid_timetable') return ''
  if (target.value === 'timetable') return 'timetable'
  return target.value
})

async function handleDownloadTemplate() {
  if (!templateKey.value) return
  downloadingTemplate.value = true
  try {
    await downloadImportTemplateFile(templateKey.value)
    ElMessage.success('已开始下载标准模板')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '下载模板失败')
  } finally {
    downloadingTemplate.value = false
  }
}

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

async function uploadAndReview() {
  await upload()
  if (drafts.value.length) await review()
}

function removeFile(id: string) {
  removeDraft(id)
  if (drafts.value.length) void review()
}

async function save() {
  try {
    await ElMessageBox.confirm(
      `将保存本次核对的 ${plan.value?.batch_ids.length || 0} 个文件。任一阻断问题会使本次不保存；未出现在文件中的已有名单不会被删除。`,
      '确认导入',
      { type: 'warning', confirmButtonText: '确认导入', cancelButtonText: '返回核对' }
    )
    await confirm()
  } catch { /* 取消确认时保留已核对草稿。 */ }
}

interface FlatIssue { severity: string; message: string; row?: number; field?: string; filename: string }
const allIssues = computed<FlatIssue[]>(() =>
  (plan.value?.files || []).flatMap(f => f.issues.map(i => ({ ...i, filename: i.filename || f.filename })))
)
const errorCount = computed(() => allIssues.value.filter(i => i.severity === 'error').length)
function issueAdvice(severity: string) {
  return severity === 'error' ? '修正该文件后重新上传' : '可忽略；如需计入请修正后重新上传'
}

const actionLabels = { CREATE: '新增', UPDATE: '更新', UNCHANGED: '不变／已处理' }
const entityLabels: Record<string, string> = { student: '学生', qualification: '学期资格', schedule: '课表', roster_member: '名单成员', class_duties: '班级负责人', class_metadata: '班级资料' }
const fieldLabels: Record<string, string> = { enabled: '启用', present: '在名单中', name: '姓名', class_name: '班级名称', class_code: '教学班码', course_code: '课程代码', course_name: '课程名称', weekday: '星期', start_period: '开始节次', end_period: '结束节次', weeks: '周次', classroom: '教室', teacher: '教师', head_teacher: '班主任', counselor: '辅导员', college: '学院', grade_year: '年级', student_nos: '学号' }

function describe(value: Record<string, unknown> | null) {
  if (!value) return '无原资料'
  return Object.entries(value).filter(([key]) => fieldLabels[key]).map(([key, val]) =>
    `${fieldLabels[key]}：${typeof val === 'boolean' ? (val ? '是' : '否') : Array.isArray(val) ? val.join('、') : val ?? '未记录'}`).join('\n')
}

function goToTimetable() {
  void router.push('/dashboard/academic?tab=timetable')
}
</script>

<template>
  <section v-loading="busy" aria-label="导入向导" class="wizard">
    <header class="wizard-head">
      <button class="btn btn-ghost btn-sm" @click="emit('back')">← 返回资料准备</button>
      <h2 class="wizard-title">{{ displayTitle }}</h2>
    </header>

    <el-steps :active="step" simple class="steps">
      <el-step title="上传文件" />
      <el-step title="核对结果" />
      <el-step title="确认导入" />
    </el-steps>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="alert-line" />
    <el-alert
      v-for="message in uploadErrors"
      :key="message"
      :title="`上传失败：${message}。请修正该文件后重新选择上传。`"
      type="error"
      :closable="false"
      class="alert-line"
    />

    <!-- 第一步：上传文件 -->
    <div v-if="!plan && !result" ref="form" class="panel step-panel" data-unsaved-form>
      <div v-if="isTimetable" class="form-row">
        <label class="form-item-label">课表格式</label>
        <div class="form-item-ctrl">
          <el-radio-group v-model="target" :disabled="busy">
            <el-radio value="grid_timetable">教务网格原表（学校教务系统导出的班级课表）</el-radio>
            <el-radio value="timetable">平台标准长表（按标准列填写）</el-radio>
          </el-radio-group>
        </div>
      </div>

      <div v-if="target === 'roster'" class="form-row">
        <label class="form-item-label">目标教学班</label>
        <div class="form-item-ctrl">
          <el-select
            v-model="teachingClassId"
            filterable
            remote
            :remote-method="searchClasses"
            :loading="classBusy"
            placeholder="搜索本学期教学班"
            class="target-select"
            @visible-change="classesOpened"
          >
            <el-option
              v-for="row in teachingClasses"
              :key="row.id"
              :value="row.id"
              :label="String(row.class_name || row.class_code || row.id)"
            />
          </el-select>
        </div>
      </div>
      <el-alert v-if="classError" :title="classError" type="error" :closable="false" class="alert-line" />

      <div v-if="isTimetable" class="form-row">
        <label class="form-item-label">课程类型</label>
        <div class="form-item-ctrl">
          <el-select v-model="courseTypeId" placeholder="选择生成的教学班课程类型（默认普通课）" class="target-select">
            <el-option
              v-for="row in courseTypes"
              :key="row.id"
              :value="row.id"
              :label="`${row.name} ${(row.code === 'builtin_regular' || row.name === '普通课') ? '（默认）' : ''}`"
            />
          </el-select>
        </div>
      </div>

      <div class="form-row file-upload-row">
        <label class="form-item-label">选择文件</label>
        <div class="form-item-ctrl file-ctrl">
          <input
            type="file"
            multiple
            accept=".xlsx,.xls,.csv"
            aria-label="选择导入文件"
            :disabled="busy"
            @change="fileChanged"
          />
          <p class="hint">支持 .xlsx、.xls、.csv 格式，单个文件不超过 10 MiB。</p>
          <details class="limit-details">
            <summary>更多限制</summary>
            <p class="hint">一次最多 20 个文件；一次核对最多 5000 条变更。上传后先生成草稿，核对无误并明确确认后才会保存。</p>
          </details>
          <div v-if="files.length" class="selected-files">
            <span v-for="file in files" :key="file.name" class="file-tag">
              {{ file.name }}（{{ Math.ceil(file.size / 1024) }} KiB）
            </span>
          </div>
        </div>
      </div>

      <div class="form-actions">
        <el-button type="primary" size="large" :disabled="!canUpload || busy" @click="uploadAndReview">
          上传并核对
        </el-button>
        <el-button v-if="templateKey" plain :loading="downloadingTemplate" @click="handleDownloadTemplate">
          下载标准模板
        </el-button>
        <span v-if="target === 'grid_timetable'" class="hint">网格原表无需模板，直接使用教务系统导出的 Excel 文件。</span>
      </div>
    </div>

    <!-- 第二步：核对结果 -->
    <template v-if="plan && !result">
      <div class="panel step-panel">
        <h3 class="panel-title">本次上传的文件</h3>
        <p class="hint">需要排除某个文件时可明确移除，移除后自动重新核对。</p>
        <table class="tbl file-tbl">
          <thead>
            <tr><th>文件名称</th><th class="col-status">状态</th><th class="col-op">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="file in plan.files" :key="file.id">
              <td>
                <div class="file-name">{{ file.filename }}</div>
                <div v-if="previewSummary(file.target, file.summary)" class="file-summary">
                  {{ previewSummary(file.target, file.summary) }}
                </div>
              </td>
              <td class="col-status">
                <span
                  class="tag"
                  :class="file.issues.some(i => i.severity === 'error') ? 'tag-red' : file.issues.length ? 'tag-amber' : 'tag-green'"
                >
                  {{ file.issues.some(i => i.severity === 'error') ? '需处理' : file.issues.length ? '有提示' : '解析成功' }}
                </span>
              </td>
              <td class="col-op">
                <button class="btn btn-ghost btn-sm" :disabled="busy" @click="removeFile(file.id)">移除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="allIssues.length" class="panel step-panel">
        <h3 class="panel-title">需要处理的问题</h3>
        <p v-if="errorCount" class="hint">其中 {{ errorCount }} 项为阻断问题，修正前本次不会保存。</p>
        <table class="tbl">
          <thead>
            <tr><th>文件</th><th>位置</th><th>问题</th><th>处理方法</th></tr>
          </thead>
          <tbody>
            <tr v-for="(issue, index) in allIssues.slice(0, 100)" :key="index">
              <td class="issue-file">{{ issue.filename }}</td>
              <td>{{ issue.row ? `第 ${issue.row} 行` : '' }}{{ issue.row && issue.field ? ' · ' : '' }}{{ issue.field || '' }}{{ !issue.row && !issue.field ? '—' : '' }}</td>
              <td>
                <span class="issue-severity" :class="issue.severity === 'error' ? 'is-error' : 'is-warning'">
                  {{ issue.severity === 'error' ? '阻断' : '提示' }}
                </span>
                {{ issue.message }}
              </td>
              <td class="issue-advice">{{ issueAdvice(issue.severity) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="allIssues.length > 100" class="hint">共 {{ allIssues.length }} 个问题，此处展示前 100 项。</p>
      </div>

      <div class="panel step-panel">
        <h3 class="panel-title">具体变更</h3>
        <el-alert :title="plan.impact_note" type="info" :closable="false" class="alert-line" />
        <el-collapse>
          <el-collapse-item
            v-for="file in plan.files"
            :key="file.id"
            :title="`${file.filename}：查看详细差异（${file.changes.length} 条）`"
            :name="file.id"
          >
            <el-table
              :data="file.changes.slice(((changePages[file.id] || 1) - 1) * 30, (changePages[file.id] || 1) * 30)"
              empty-text="无可应用条目"
              border
            >
              <el-table-column label="处理动作" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.action === 'CREATE' ? 'success' : row.action === 'UPDATE' ? 'warning' : 'info'" size="small">
                    {{ actionLabels[row.action as keyof typeof actionLabels] }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="实体对象" width="120">
                <template #default="{ row }">{{ entityLabels[row.entity] || row.entity }}</template>
              </el-table-column>
              <el-table-column prop="key" label="资料标识" min-width="160" />
              <el-table-column label="表格来源" min-width="140">
                <template #default="{ row }">
                  {{ row.source.sheet || '首表' }}{{ row.source.row ? ' · 第 ' + row.source.row + ' 行' : '' }}
                </template>
              </el-table-column>
              <el-table-column label="核对详情 (Before / After)" min-width="240">
                <template #default="{ row }">
                  <details>
                    <summary>查看字段前后比对</summary>
                    <pre class="diff-pre">原：{{ describe(row.before) }}
新：{{ describe(row.after) }}</pre>
                  </details>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination
              v-model:current-page="changePages[file.id]"
              :page-size="30"
              :total="file.changes.length"
              layout="prev, pager, next, total"
              class="table-pagination"
            />
          </el-collapse-item>
        </el-collapse>
      </div>

      <el-alert
        v-if="!plan.can_confirm"
        title="存在阻断性问题，本次无法保存。请修正文件后重新上传，或移除有问题的文件（会自动重新核对）。"
        type="error"
        :closable="false"
        class="alert-line"
      />
      <div class="confirm-bar">
        <el-button type="primary" size="large" :disabled="!plan.can_confirm || busy" @click="save">
          确认导入
        </el-button>
      </div>
    </template>

    <!-- 第三步：保存结果 -->
    <el-result v-if="result" icon="success" title="本次导入已保存" sub-title="重复请求不会重复导入。正式课表仍需在“发布给学生”中确认发布。">
      <template #extra>
        <div class="result-details">
          <p v-for="file in result.files" :key="file.id" class="result-item">
            <strong>{{ file.filename }}</strong>：{{ savedSummary(file.summary) }}
          </p>
        </div>
        <div class="result-actions">
          <el-button v-if="isTimetable" type="primary" @click="goToTimetable">查看正式课表</el-button>
          <el-button @click="emit('back')">返回资料准备</el-button>
        </div>
      </template>
    </el-result>

    <ImportIdentityReview
      v-if="result && isTimetable && session.hasPermission('academic.manage') && session.campusRuntime?.scheduling"
    />
  </section>
</template>

<style scoped>
.wizard {
  margin: 12px 0;
}
.wizard-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 4px;
}
.wizard-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 18px;
  font-weight: 600;
  color: var(--ink);
}
.steps {
  margin: 16px 0;
}
.alert-line {
  margin: 10px 0;
}
.step-panel {
  margin: 16px 0;
}
.panel-title {
  margin-bottom: 4px;
}
.form-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.form-item-label {
  width: 90px;
  font-weight: 600;
  padding-top: 6px;
  color: var(--ink-soft);
}
.form-item-ctrl {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.file-ctrl {
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.target-select {
  max-width: 420px;
  width: 100%;
}
.file-upload-row input[type="file"] {
  border: 1px dashed var(--line-strong);
  padding: 10px;
  border-radius: var(--radius);
  width: 100%;
  max-width: 520px;
  background: var(--paper);
}
.hint {
  color: var(--ink-mute);
  font-size: 12px;
  margin-top: 4px;
}
.limit-details summary {
  color: var(--ink-mute);
  font-size: 12px;
  cursor: pointer;
}
.selected-files {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.file-tag {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  color: var(--ink-soft);
  padding: 2px 8px;
  border-radius: var(--radius);
  font-size: 12px;
}
.form-actions {
  margin-left: 106px;
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.file-tbl {
  margin-top: 10px;
}
.file-name {
  font-weight: 600;
  color: var(--ink);
}
.file-summary {
  color: var(--ink-mute);
  font-size: 12px;
  margin-top: 2px;
}
.col-status {
  width: 110px;
}
.col-op {
  width: 90px;
}
.issue-file {
  max-width: 200px;
  word-break: break-all;
}
.issue-severity {
  font-weight: 600;
  margin-right: 4px;
}
.issue-severity.is-error {
  color: var(--accent);
}
.issue-severity.is-warning {
  color: var(--amber);
}
.issue-advice {
  color: var(--ink-mute);
  font-size: 12px;
  min-width: 200px;
}
.diff-pre {
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 460px;
  font-size: 12px;
  background: var(--paper-deep);
  padding: 8px;
  border-radius: var(--radius);
  margin: 6px 0 0 0;
}
.table-pagination {
  margin-top: 14px;
}
.confirm-bar {
  margin: 24px 0;
  text-align: right;
}
.result-details {
  text-align: left;
  max-width: 500px;
  margin: 16px auto;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 16px;
  border-radius: var(--radius);
}
.result-item {
  font-size: 13px;
  margin: 6px 0;
}
.result-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  gap: 12px;
}
</style>
