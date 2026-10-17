<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import {
  downloadImportTemplateFile,
  getImportBatch,
  listRecentImports,
  type ImportBatchListItem,
  type ImportPreviewResult
} from '../../api/importer'
import { batchStatusLabels, savedSummary, targetLabels } from './importLabels'
import { formatBeijingTime } from '../../utils/datetime'
import ImportWizard from './ImportWizard.vue'

const router = useRouter()
const session = useSessionStore()

const view = ref<'home' | 'wizard'>('home')
const wizardTarget = ref('admin_roster')

function startImport(target: string) {
  wizardTarget.value = target
  view.value = 'wizard'
}

const canStudentManage = () => session.hasPermission('student.manage')
const canScheduleImport = () => session.hasPermission('course_schedule.import')
const canVolunteerManage = () => session.hasPermission('volunteer.manage')
const canSelfStudy = () => session.hasPermission('course_schedule.manage') || session.hasPermission('academic.manage')

const downloadingTemplate = ref('')
async function handleTemplate(target: string) {
  downloadingTemplate.value = target
  try {
    await downloadImportTemplateFile(target)
    ElMessage.success('已开始下载标准模板')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '下载模板失败')
  } finally {
    downloadingTemplate.value = ''
  }
}

const showExample = ref(false)

function goSelfStudy() {
  void router.push('/dashboard/academic?tab=timetable&selfStudy=1')
}

// ---- 最近导入 ----
const recent = ref<ImportBatchListItem[]>([])
const recentError = ref('')
async function loadRecent() {
  recentError.value = ''
  try {
    recent.value = await listRecentImports(10)
  } catch (e) {
    recentError.value = e instanceof Error ? e.message : '最近导入加载失败'
  }
}
onMounted(loadRecent)

function statusTagType(status: string) {
  return status === 'CONFIRMED' ? 'tag-green' : status === 'PREVIEW' ? 'tag-amber' : status === 'FAILED' ? 'tag-red' : 'tag-gray'
}

const detail = ref<ImportPreviewResult | null>(null)
const detailBusy = ref(false)
async function openDetail(row: ImportBatchListItem) {
  detailBusy.value = true
  try {
    detail.value = await getImportBatch(row.id)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '详情加载失败')
  } finally {
    detailBusy.value = false
  }
}
</script>

<template>
  <ImportWizard v-if="view === 'wizard'" :initial-target="wizardTarget" @back="view = 'home'; loadRecent()" />
  <section v-else class="import-home" aria-label="资料准备">
    <header class="home-head">
      <h2 class="home-title">资料准备</h2>
      <span class="home-context">{{ session.workspace?.name || '当前学院' }} · {{ session.currentSemesterName }}</span>
    </header>
    <p class="home-lead">第一次使用？先导入学生名单，再导入课表。</p>

    <div class="card-grid">
      <div v-if="canStudentManage()" class="entry-card">
        <h3>行政班与学生名单</h3>
        <p>建立班级，录入学生。</p>
        <div class="card-actions">
          <button class="btn btn-dark btn-sm" @click="startImport('admin_roster')">开始导入</button>
          <button class="btn btn-ghost btn-sm" :disabled="downloadingTemplate === 'admin_roster'" @click="handleTemplate('admin_roster')">下载模板</button>
        </div>
      </div>
      <div v-if="canScheduleImport()" class="entry-card">
        <h3>本学期教务课表</h3>
        <p>导入教务导出的班级课表。</p>
        <div class="card-actions">
          <button class="btn btn-dark btn-sm" @click="startImport('grid_timetable')">开始导入</button>
          <button class="btn btn-ghost btn-sm" @click="showExample = true">查看示例</button>
        </div>
      </div>
    </div>

    <div class="panel other-panel">
      <h3 class="panel-title">其他资料</h3>
      <div class="other-list">
        <div v-if="canStudentManage()" class="other-row">
          <span class="other-name">班主任与责任区辅导员</span>
          <button class="btn btn-ghost btn-sm" @click="startImport('class_duty')">导入或维护</button>
        </div>
        <div v-if="canVolunteerManage()" class="other-row">
          <span class="other-name">志愿者与组织成员</span>
          <button class="btn btn-ghost btn-sm" @click="router.push('/dashboard/organizations')">前往准备</button>
        </div>
        <div v-if="canStudentManage()" class="other-row">
          <span class="other-name">补充教学班名单</span>
          <button class="btn btn-ghost btn-sm" @click="startImport('roster')">导入</button>
        </div>
      </div>
    </div>

    <div v-if="canSelfStudy()" class="panel self-study-row">
      <div>
        <h3 class="panel-title">早晚自习不用制作 Excel</h3>
        <p class="hint">按年级、工作日和固定时段一键生成排课，自动关联行政班在籍学生。</p>
      </div>
      <button class="btn btn-accent btn-sm" @click="goSelfStudy">批量生成</button>
    </div>

    <div class="panel">
      <h3 class="panel-title">最近导入</h3>
      <el-alert v-if="recentError" :title="recentError" type="error" :closable="false" />
      <p v-else-if="!recent.length" class="hint">暂无导入记录。</p>
      <table v-else class="tbl">
        <thead>
          <tr><th>文件名称</th><th>资料</th><th>处理结果</th><th>时间</th><th class="col-op">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in recent" :key="row.id">
            <td class="file-cell">{{ row.filename || '未命名文件' }}</td>
            <td>{{ targetLabels[row.target] || row.target }}</td>
            <td>
              <span class="tag" :class="statusTagType(row.status)">{{ batchStatusLabels[row.status] || row.status }}</span>
              <div v-if="row.status === 'CONFIRMED'" class="result-text">{{ savedSummary(row.summary) }}</div>
            </td>
            <td class="time-cell">{{ formatBeijingTime(row.created_at, 'minute') }}</td>
            <td class="col-op">
              <button class="btn btn-ghost btn-sm" :disabled="detailBusy" @click="openDetail(row)">查看</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <el-dialog v-model="showExample" title="教务课表支持的格式" width="560px">
      <div class="example-body">
        <p><strong>教务网格原表（推荐）</strong>：学校教务系统按班级导出的 Excel 课表（.xls / .xlsx），每个行政班一个文件，系统自动识别课程与上课时段，无需修改格式。</p>
        <p><strong>平台标准长表</strong>：按标准列（教学班码、课程名称、任课教师、星期、节次、周次、上课地点）逐行填写，适合教务无法导出原表时使用。</p>
        <p>公选课与早晚自习无需导入：公选课全校统筹、不设查课任务；早晚自习在教务资料一键批量生成。</p>
      </div>
      <template #footer>
        <button class="btn btn-ghost btn-sm" :disabled="downloadingTemplate === 'timetable'" @click="handleTemplate('timetable')">下载标准长表模板</button>
        <button class="btn btn-dark btn-sm" @click="showExample = false">知道了</button>
      </template>
    </el-dialog>

    <el-dialog :model-value="!!detail" title="导入详情" width="640px" @close="detail = null">
      <div v-if="detail" class="detail-body">
        <p><strong>资料类型：</strong>{{ targetLabels[detail.target] || detail.target }}</p>
        <p><strong>状态：</strong>{{ batchStatusLabels[detail.status] || detail.status }}</p>
        <p v-if="detail.status === 'CONFIRMED'"><strong>结果：</strong>{{ savedSummary(detail.summary) }}</p>
        <template v-if="detail.errors.length">
          <p><strong>阻断问题：</strong></p>
          <p v-for="(issue, index) in detail.errors.slice(0, 20)" :key="`e${index}`" class="issue-line">
            {{ issue.row ? `第 ${issue.row} 行 · ` : '' }}{{ issue.message }}
          </p>
          <p v-if="detail.errors.length > 20" class="hint">共 {{ detail.errors.length }} 项，此处展示前 20 项。</p>
        </template>
        <template v-if="detail.warnings.length">
          <p><strong>提示：</strong></p>
          <p v-for="(issue, index) in detail.warnings.slice(0, 20)" :key="`w${index}`" class="issue-line">
            {{ issue.row ? `第 ${issue.row} 行 · ` : '' }}{{ issue.message }}
          </p>
        </template>
      </div>
    </el-dialog>
  </section>
</template>

<style scoped>
.import-home {
  margin: 12px 0;
}
.home-head {
  display: flex;
  align-items: baseline;
  gap: 14px;
}
.home-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 18px;
  font-weight: 600;
  color: var(--ink);
}
.home-context {
  color: var(--ink-mute);
  font-size: 12px;
}
.home-lead {
  color: var(--ink-soft);
  margin: 8px 0 18px;
}
.card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 900px) {
  .card-grid {
    grid-template-columns: 1fr;
  }
}
.entry-card {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  padding: 18px;
}
.entry-card h3 {
  font-family: 'Noto Serif SC', serif;
  font-size: 16px;
  color: var(--ink);
  margin-bottom: 4px;
}
.entry-card p {
  color: var(--ink-mute);
  font-size: 13px;
  margin-bottom: 14px;
}
.card-actions {
  display: flex;
  gap: 10px;
}
.other-panel {
  margin-top: 16px;
}
.other-list {
  display: flex;
  flex-direction: column;
}
.other-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.other-row:last-child {
  border-bottom: none;
}
.other-name {
  color: var(--ink-soft);
}
.self-study-row {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.hint {
  color: var(--ink-mute);
  font-size: 12px;
  margin-top: 4px;
}
.panel {
  margin-top: 16px;
}
.file-cell {
  max-width: 240px;
  word-break: break-all;
}
.result-text {
  color: var(--ink-mute);
  font-size: 12px;
  margin-top: 4px;
}
.time-cell {
  white-space: nowrap;
  color: var(--ink-mute);
  font-size: 12px;
}
.col-op {
  width: 80px;
}
.example-body p {
  margin: 8px 0;
  line-height: 1.8;
}
.detail-body p {
  margin: 6px 0;
}
.issue-line {
  color: var(--ink-soft);
  font-size: 13px;
}
</style>
