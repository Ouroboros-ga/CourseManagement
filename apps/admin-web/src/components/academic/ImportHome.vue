<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import { getImportBatch, listRecentImports, type ImportBatchListItem, type ImportPreviewResult } from '../../api/importer'
import { batchStatusLabels, savedSummary, targetLabels } from './importLabels'
import { formatBeijingTime } from '../../utils/datetime'
import ImportWizard from './ImportWizard.vue'
import ImportCenter from './ImportCenter.vue'
import AssistantImportReviewCard from './AssistantImportReviewCard.vue'
import StoredImportWorkspaceCard from './StoredImportWorkspaceCard.vue'
import type { ResumableImport } from '../../api/assistantImports'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const recent = ref<ImportBatchListItem[]>([])
const recentError = ref('')
const busy = ref(false)
const resumeBatch = ref<(ImportPreviewResult & { filename: string }) | null>(null)
const resumeBatches = ref<ResumableImport[]>([])
const detail = ref<ImportPreviewResult | null>(null)
const detailBusy = ref(false)

const assistantTaskId = computed(() => route.query.assistant_task_id === undefined ? ''
  : typeof route.query.assistant_task_id === 'string' && route.query.assistant_task_id ? route.query.assistant_task_id : 'INVALID')
const assistantAvailable = computed(() => !!session.campusRuntime?.business_scoped && session.hasPermission('import.execute'))
const assistantWorkspaceId = computed(() => route.query.assistant_workspace_id === undefined ? ''
  : typeof route.query.assistant_workspace_id === 'string' && route.query.assistant_workspace_id ? route.query.assistant_workspace_id : 'INVALID')
const storedAvailable = computed(() => assistantAvailable.value && import.meta.env.VITE_AGENT_IMPORT_ENABLED === 'true')
const context = () => JSON.stringify([session.currentUser?.id, session.currentUser?.roles,
  session.workspaceCollegeId, session.currentSemesterId, session.workspace?.authorization_revision,
  session.workspace?.configuration_revision, session.workspace?.capabilities, assistantTaskId.value, assistantWorkspaceId.value, assistantAvailable.value])
let requestId = 0

async function loadRecent() {
  const ticket = ++requestId
  const captured = context()
  recentError.value = ''
  recent.value = []
  try {
    const rows = await listRecentImports(10)
    if (ticket === requestId && captured === context()) recent.value = rows
  } catch {
    if (ticket === requestId && captured === context()) recentError.value = '最近导入读取失败，请重试。'
  }
}

watch(context, () => {
  resumeBatch.value = null
  resumeBatches.value = []; busy.value = false
  detail.value = null
  void loadRecent()
}, { immediate: true })

function resumeAssistant(rows: ResumableImport[]) {
  if (busy.value) return
  resumeBatch.value = null; resumeBatches.value = rows
}
function backToImport() {
  resumeBatch.value = null; resumeBatches.value = []
  if (assistantTaskId.value || assistantWorkspaceId.value) {
    const query = { ...route.query }; delete query.assistant_task_id; delete query.assistant_workspace_id
    void router.replace({ query })
  }
}

async function open(row: ImportBatchListItem) {
  const captured = context()
  detailBusy.value = true
  try {
    const value = await getImportBatch(row.id)
    if (captured !== context()) return
    if (row.status === 'PREVIEW') {
      if (row.semester_id && row.semester_id !== session.currentSemesterId) {
        ElMessage.warning('请先切换到这条记录所属学期，再继续核对。')
        return
      }
      resumeBatch.value = { ...value, filename: row.filename || '未命名文件' }
    } else {
      detail.value = value
    }
  } catch (e) {
    if (captured === context()) ElMessage.error(e instanceof Error ? e.message : '记录读取失败')
  } finally {
    detailBusy.value = false
  }
}
</script>

<template>
  <section aria-label="资料导入">
    <StoredImportWorkspaceCard v-if="assistantWorkspaceId" :key="context()" :workspace-id="assistantWorkspaceId"
      :college-id="session.workspaceCollegeId" :semester-id="session.currentSemesterId"
      :context-key="context()" :available="storedAvailable" @saved="loadRecent" @busy="busy = $event" />
    <AssistantImportReviewCard v-if="assistantTaskId" :task-id="assistantTaskId"
      :college-id="session.workspaceCollegeId" :semester-id="session.currentSemesterId"
      :context-key="context()" :available="assistantAvailable" :locked="busy" @resume="resumeAssistant" />
    <ImportWizard
      v-if="resumeBatch || resumeBatches.length"
      :resume-batch="resumeBatch"
      :resume-batches="resumeBatches.length ? resumeBatches : undefined"
      @saved="loadRecent"
      @busy="busy = $event"
    />
    <ImportCenter v-else-if="!assistantTaskId && !assistantWorkspaceId" @saved="loadRecent" @busy="busy = $event" />

    <el-button v-if="resumeBatch || resumeBatches.length || assistantTaskId || assistantWorkspaceId" :disabled="busy" @click="backToImport">返回统一导入</el-button>

    <div class="other-actions">
      <span>其他操作</span>
      <el-button
        v-if="session.hasPermission('academic.manage')"
        link
        @click="router.push('/dashboard/academic?tab=timetable&selfStudy=1')"
      >
        批量生成早晚自习
      </el-button>
      <el-button
        v-if="session.hasPermission('volunteer.manage')"
        link
        @click="router.push('/dashboard/organizations')"
      >
        维护志愿者组织
      </el-button>
    </div>

    <details v-if="!assistantTaskId" class="recent disclosure">
      <summary>最近导入记录<template v-if="recent.length">（{{ recent.length }} 条）</template></summary>
      <el-alert v-if="recentError" :title="recentError" type="error" :closable="false" />
      <p v-else-if="!recent.length" class="hint">暂无导入记录。</p>
      <table v-else class="tbl">
        <thead>
          <tr><th>文件</th><th>状态</th><th>时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in recent" :key="row.id">
            <td>
              {{ row.filename }}
              <div class="hint">{{ targetLabels[row.target] || row.target }}</div>
            </td>
            <td>{{ batchStatusLabels[row.status] || row.status }}</td>
            <td>{{ formatBeijingTime(row.created_at, 'minute') }}</td>
            <td>
              <el-button link :disabled="detailBusy || busy" @click="open(row)">
                {{ row.status === 'PREVIEW' ? '继续核对' : '查看结果' }}
              </el-button>
            </td>
          </tr>
        </tbody>
      </table>
    </details>

    <el-dialog :model-value="!!detail" title="导入记录" @close="detail = null">
      <template v-if="detail">
        <p>{{ batchStatusLabels[detail.status] || detail.status }}</p>
        <p>{{ savedSummary(detail.summary) }}</p>
        <p v-for="(issue, index) in [...detail.errors, ...detail.warnings]" :key="index">
          {{ issue.row ? `第${issue.row}行：` : '' }}{{ issue.message }}
        </p>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.other-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 24px;
  padding: 16px 0;
  border-top: 1px solid var(--line);
  font-size: var(--text-sm);
  color: var(--ink-mute);
}
.recent {
  margin-top: 24px;
}
.recent table {
  margin: 14px 0;
}
.recent td {
  overflow-wrap: anywhere;
}
</style>
