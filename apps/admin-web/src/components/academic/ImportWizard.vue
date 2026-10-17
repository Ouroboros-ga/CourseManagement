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

const router = useRouter()
const session = useSessionStore()
const { target, teachingClassId, courseTypeId, files, drafts, selectedIds, plan, result, busy, error, uploadErrors, canUpload, upload, review, confirm } = useImportWizard()
const teachingClasses = ref<ScopedAcademicRow[]>([]), classBusy = ref(false)
const classError = ref(''), form = ref<HTMLElement | null>(null)
const downloadingTemplate = ref(false)
const courseTypes = ref<CourseType[]>([])

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

interface OptionItem {
  id: string
  label: string
  category: string
  desc: string
  templateKey: string
  hasTemplate: boolean
}

const options = computed<OptionItem[]>(() => [
  ...(session.hasPermission('student.manage') ? [
    {
      id: 'admin_roster',
      label: '行政班与学生名单',
      category: '班级与学籍',
      desc: '批量建立行政班及录入在籍学生。可直接上传教务导出花名册原表，或下载平台标准模板填写。',
      templateKey: 'admin_roster',
      hasTemplate: true
    },
    {
      id: 'class_duty',
      label: '班级责任人表（班主任与辅导员）',
      category: '班级与学籍',
      desc: '按行政班批量更新班主任与辅导员管理责任人，仅需班级与责任人姓名，无需学生名单。',
      templateKey: 'class_duty',
      hasTemplate: true
    }
  ] : []),
  ...(session.hasPermission('course_schedule.import') ? [
    {
      id: 'grid_timetable',
      label: '学院教务课表（教务网格原表）',
      category: '教务正式课表',
      desc: '直接上传学校教务系统导出的 Excel 班级网格课表原表（.xls / .xlsx），自动提取课程与排课时段。',
      templateKey: 'timetable',
      hasTemplate: false
    },
    {
      id: 'timetable',
      label: '学院教务课表（平台标准长表）',
      category: '教务正式课表',
      desc: '按平台标准列（教学班码、课程名称、任课教师、星期、节次、周次、上课地点）填写的课表长表。',
      templateKey: 'timetable',
      hasTemplate: true
    }
  ] : []),
  ...(session.hasPermission('volunteer.manage') ? [
    {
      id: 'volunteer',
      label: '志愿者学期资格底册',
      category: '查课人员',
      desc: '批量导入本学期具备查课资格的志愿者学生学号底册。',
      templateKey: 'volunteer',
      hasTemplate: true
    }
  ] : []),
  ...(session.hasPermission('student.manage') ? [
    {
      id: 'roster',
      label: '教学班补充名单（选填）',
      category: '特殊名单',
      desc: '仅供特殊合班课按需指定学生名单。',
      templateKey: 'roster',
      hasTemplate: true
    }
  ] : [])
])

if (!options.value.some(row => row.id === target.value)) {
  target.value = options.value[0]?.id || ''
}

const currentOption = computed(() => options.value.find(row => row.id === target.value))

async function handleDownloadTemplate() {
  if (!currentOption.value) return
  downloadingTemplate.value = true
  try {
    await downloadImportTemplateFile(currentOption.value.templateKey)
    ElMessage.success(`已开始下载【${currentOption.value.label}】标准模板`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '下载模板失败')
  } finally {
    downloadingTemplate.value = false
  }
}

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
  const labels: Record<string, string> = { classes_created: '新增行政班', students_created: '新增学生', students_updated: '核对学生', courses_created: '新增课程', course_created: '新增课程', teaching_classes_created: '新增教学班', teaching_class_created: '新增教学班', schedules_created: '新增课表', schedule_created: '新增课表', qualification_created: '新增资格', qualification_updated: '更新资格', roster_after: '保存后名单人数', students_linked: '关联学生', class_duties_count: '更新班级责任人' }
  if (summary.unchanged) return '资料未变化，已跳过重复写入'
  return Object.entries(summary).filter(([key]) => labels[key]).map(([key, value]) => `${labels[key]} ${value}`).join('；') || '资料已保存'
}

function goToTimetable() {
  void router.push('/dashboard/academic?tab=timetable')
}
</script>

<template>
  <section v-loading="busy" aria-label="教务导入中心" class="import-center">
    <!-- 业务提示横幅 -->
    <div class="banner-grid">
      <div class="tip-card self-study-tip">
        <div class="tip-header">
          <span class="tip-badge">自习排课指引</span>
          <strong>早自习与晚自习无需手工做表导入</strong>
        </div>
        <p class="tip-body">
          全校早晚自习天然具备规律性（如指定年级工作日固定时段在固定教室自习）。请直接在“正式课表”页面点击【批量生成早/晚自习】按钮一键排课，系统将自动关联行政班在籍学生并生成排课。
        </p>
        <el-button size="small" type="primary" plain @click="goToTimetable">前往正式课表一键排课</el-button>
      </div>

      <div class="tip-card notice-tip">
        <div class="tip-header">
          <span class="tip-badge neutral">全校选修说明</span>
          <strong>公选课/选修课全校统筹，本系统无需导入</strong>
        </div>
        <p class="tip-body">
          公选课由全校统一在固定专属时段（如周二下午与晚上）开展，不设日常查课任务，不会与志愿者查课发生排班冲突，请勿导入公选课名单。
        </p>
      </div>
    </div>

    <el-alert v-if="!session.hasPermission('import.execute')" title="当前账号没有导入执行权限，请联系学院教师管理员。" type="warning" :closable="false" />
    <el-alert v-else-if="!enabled" title="新导入中心需要启用学院正式业务。当前可使用下方旧兼容入口，其批量导入逐文件保存，不保证跨文件整批回滚。" type="warning" :closable="false" />
    <el-alert v-else title="上传只生成草稿；核对具体新增、变更和问题后再明确保存。行政班与学生名单应先完成，课表再作为下一批导入。" type="info" :closable="false" />

    <el-steps :active="step" simple class="steps">
      <el-step title="选择并上传" />
      <el-step title="选定批次" />
      <el-step title="差异核对" />
      <el-step title="保存结果" />
    </el-steps>

    <div ref="form" class="upload-form" data-unsaved-form>
      <div class="form-row">
        <label class="form-item-label">资料类型</label>
        <div class="form-item-ctrl">
          <el-select v-model="target" :disabled="busy || !enabled" class="target-select">
            <el-option v-for="row in options" :key="row.id" :value="row.id" :label="row.label">
              <span class="opt-label">{{ row.label }}</span>
              <span class="opt-category">{{ row.category }}</span>
            </el-option>
          </el-select>

          <el-button
            v-if="currentOption"
            type="primary"
            plain
            :loading="downloadingTemplate"
            @click="handleDownloadTemplate"
          >
            下载【{{ currentOption.label.split('（')[0] }}】标准模板
          </el-button>
        </div>
      </div>

      <div v-if="currentOption" class="target-desc-panel">
        <p class="desc-text"><strong>业务说明：</strong>{{ currentOption.desc }}</p>
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
      <el-alert v-if="classError" :title="classError" type="error" :closable="false" />

      <div v-if="['grid_timetable', 'timetable', 'elective_course'].includes(target)" class="form-row">
        <label class="form-item-label">课程类型</label>
        <div class="form-item-ctrl">
          <el-select
            v-model="courseTypeId"
            placeholder="选择生成的教学班课程类型（默认普通课）"
            class="target-select"
          >
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
        <div class="form-item-ctrl">
          <input
            type="file"
            multiple
            accept=".xlsx,.xls,.csv"
            aria-label="选择导入文件"
            :disabled="busy || !enabled"
            @change="fileChanged"
          />
          <p class="hint">支持 .xlsx、.xls、.csv 格式。最多 20 个文件，每个不超过 10 MiB；一次核对最多 5000 条变更。</p>
          <div v-if="files.length" class="selected-files">
            <span v-for="file in files" :key="file.name" class="file-tag">
              {{ file.name }} ({{ Math.ceil(file.size / 1024) }} KiB)
            </span>
          </div>
        </div>
      </div>

      <div class="form-actions">
        <el-button type="primary" size="large" :disabled="!canUpload || !enabled || busy" @click="upload">
          上传并解析草稿
        </el-button>
      </div>
    </div>

    <el-alert v-for="message in uploadErrors" :key="message" :title="message + '；该文件未进入确认集合'" type="error" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />

    <div v-if="drafts.length" class="selection">
      <h3>明确选择本次保存的文件批次</h3>
      <el-checkbox-group v-model="selectedIds" :disabled="busy || !!result">
        <el-checkbox v-for="draft in drafts" :key="draft.id" :value="draft.id">
          {{ draft.filename }}{{ draft.can_confirm ? '' : '（解析有问题，需核对）' }}
        </el-checkbox>
      </el-checkbox-group>
      <el-button type="primary" :disabled="!selectedIds.length || busy || !!result" @click="review">
        核对选中的 {{ selectedIds.length }} 个文件
      </el-button>
    </div>

    <template v-if="plan && !result">
      <el-alert :title="plan.impact_note" type="info" :closable="false" class="impact-alert" />
      <el-card v-for="file in plan.files" :key="file.id" class="file-card">
        <template #header>
          <div class="card-head">
            <strong>{{ file.filename }}</strong>
            <span class="change-count">共 {{ file.changes.length }} 条待核对变更</span>
          </div>
        </template>

        <div v-if="file.issues.length" class="issues-box">
          <p
            v-for="(issue, index) in file.issues.slice(0, 50)"
            :key="index"
            :class="issue.severity === 'error' ? 'issue-error' : 'hint'"
          >
            {{ issue.severity === 'error' ? '【阻断】' : '【提示】' }}
            {{ issue.row ? '第 ' + issue.row + ' 行 · ' : '' }}
            {{ issue.field ? issue.field + '：' : '' }}
            {{ issue.message }}
          </p>
          <p v-if="file.issues.length > 50" class="hint">
            共 {{ file.issues.length }} 个问题，此处展示前 50 项；请修正文件后重新上传。
          </p>
        </div>

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
      </el-card>

      <el-alert
        v-if="!plan.can_confirm"
        title="存在阻断性问题，无法保存入库。请根据上方提示修正文件后重新上传，或取消勾选有问题的文件再重新核对。"
        type="error"
        :closable="false"
      />
      <div class="confirm-bar">
        <el-button type="primary" size="large" :disabled="!plan.can_confirm || busy" @click="save">
          确认保存本次集合入库
        </el-button>
      </div>
    </template>

    <el-result v-if="result" icon="success" title="本次导入集合已成功保存入库" sub-title="重复请求不会重复导入。正式课表仍需在“发布给学生”中确认发布。">
      <template #extra>
        <div class="result-details">
          <p v-for="file in result.files" :key="file.id" class="result-item">
            <strong>{{ file.filename }}</strong>：{{ savedSummary(file.summary) }}
          </p>
        </div>
        <div class="result-actions">
          <el-button type="primary" @click="goToTimetable">前往核对正式课表</el-button>
        </div>
      </template>
    </el-result>

    <ImportIdentityReview
      v-if="result && ['timetable', 'grid_timetable'].includes(target) && session.hasPermission('academic.manage') && session.campusRuntime?.scheduling"
    />
  </section>
</template>

<style scoped>
.import-center {
  margin: 12px 0;
}
.banner-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}
@media (max-width: 900px) {
  .banner-grid {
    grid-template-columns: 1fr;
  }
}
.tip-card {
  padding: 16px;
  border-radius: 8px;
  background-color: #f8fafc;
  border: 1px solid #e2e8f0;
}
.self-study-tip {
  border-left: 4px solid #3b82f6;
  background-color: #eff6ff;
}
.notice-tip {
  border-left: 4px solid #64748b;
}
.tip-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.tip-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: #2563eb;
  color: white;
}
.tip-badge.neutral {
  background: #64748b;
}
.tip-body {
  font-size: 13px;
  color: #334155;
  line-height: 1.5;
  margin-bottom: 12px;
}
.steps {
  margin: 20px 0;
}
.upload-form {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 20px;
  margin: 20px 0;
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
  color: #1e293b;
}
.form-item-ctrl {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.target-select {
  max-width: 420px;
  width: 100%;
}
.opt-label {
  font-weight: 500;
}
.opt-category {
  float: right;
  color: #94a3b8;
  font-size: 12px;
}
.target-desc-panel {
  margin-left: 106px;
  margin-top: -8px;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 12px;
  color: #475569;
}
.file-upload-row input[type="file"] {
  border: 1px dashed #cbd5e1;
  padding: 10px;
  border-radius: 6px;
  width: 100%;
  max-width: 520px;
}
.hint {
  color: #64748b;
  font-size: 12px;
  margin-top: 4px;
}
.selected-files {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.file-tag {
  background: #e2e8f0;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.form-actions {
  margin-left: 106px;
  margin-top: 10px;
}
.selection {
  margin: 24px 0;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.selection h3 {
  margin-top: 0;
  margin-bottom: 12px;
  font-size: 15px;
}
.impact-alert {
  margin: 16px 0;
}
.file-card {
  margin: 16px 0;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.change-count {
  font-size: 13px;
  color: #64748b;
}
.issues-box {
  background: #fff1f2;
  border: 1px solid #fecdd3;
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 16px;
}
.issue-error {
  color: #e11d48;
  font-size: 13px;
  margin: 4px 0;
}
.diff-pre {
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 460px;
  font-size: 12px;
  background: #f8fafc;
  padding: 8px;
  border-radius: 4px;
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
  background: #f8fafc;
  padding: 16px;
  border-radius: 8px;
}
.result-item {
  font-size: 13px;
  margin: 6px 0;
}
.result-actions {
  margin-top: 16px;
}
</style>
