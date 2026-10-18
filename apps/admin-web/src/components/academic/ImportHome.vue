<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import { getImportBatch, listRecentImports, type ImportBatchListItem, type ImportPreviewResult } from '../../api/importer'
import { batchStatusLabels, savedSummary, targetLabels } from './importLabels'
import { formatBeijingTime } from '../../utils/datetime'
import ImportWizard from './ImportWizard.vue'
import ImportCenter from './ImportCenter.vue'
const router = useRouter(), session = useSessionStore()
const recent = ref<ImportBatchListItem[]>([]), recentError = ref(''), busy = ref(false)
const resumeBatch = ref<(ImportPreviewResult & { filename: string }) | null>(null), detail = ref<ImportPreviewResult | null>(null), detailBusy = ref(false)
const context = () => `${session.currentUser?.id}:${session.workspaceCollegeId}`
let requestId = 0
async function loadRecent() {
  const ticket = ++requestId, captured = context()
  recentError.value = ''; recent.value = []
  try { const rows = await listRecentImports(10); if (ticket === requestId && captured === context()) recent.value = rows }
  catch { if (ticket === requestId && captured === context()) recentError.value = '最近导入读取失败，请重试。' }
}
watch(context, () => { resumeBatch.value = null; detail.value = null; void loadRecent() }, { immediate: true })
async function open(row: ImportBatchListItem) {
  const captured = context()
  detailBusy.value = true
  try {
    const value = await getImportBatch(row.id)
    if (captured !== context()) return
    if (row.status === 'PREVIEW') {
      if (row.semester_id && row.semester_id !== session.currentSemesterId) { ElMessage.warning('请先切换到这条记录所属学期，再继续核对。'); return }
      resumeBatch.value = { ...value, filename: row.filename || '未命名文件' }
    } else detail.value = value
  } catch (e) { if (captured === context()) ElMessage.error(e instanceof Error ? e.message : '记录读取失败') }
  finally { detailBusy.value = false }
}
</script>
<template>
  <section aria-label="资料导入"><ImportWizard v-if="resumeBatch" :resume-batch="resumeBatch" @saved="loadRecent" @busy="busy = $event" /><ImportCenter v-else @saved="loadRecent" @busy="busy = $event" /><el-button v-if="resumeBatch" :disabled="busy" @click="resumeBatch = null">返回统一导入</el-button><div class="other-actions"><span>其他操作</span><el-button v-if="session.hasPermission('academic.manage')" link @click="router.push('/dashboard/academic?tab=timetable&selfStudy=1')">批量生成早晚自习</el-button><el-button v-if="session.hasPermission('volunteer.manage')" link @click="router.push('/dashboard/organizations')">维护志愿者组织</el-button></div>
    <details class="recent"><summary>最近导入记录<template v-if="recent.length">（{{ recent.length }} 条）</template></summary><el-alert v-if="recentError" :title="recentError" type="error" :closable="false" /><p v-else-if="!recent.length" class="hint">暂无导入记录。</p><table v-else class="tbl"><thead><tr><th>文件</th><th>状态</th><th>时间</th><th>操作</th></tr></thead><tbody><tr v-for="row in recent" :key="row.id"><td>{{ row.filename }}<div class="hint">{{ targetLabels[row.target] || row.target }}</div></td><td>{{ batchStatusLabels[row.status] || row.status }}</td><td>{{ formatBeijingTime(row.created_at, 'minute') }}</td><td><el-button link :disabled="detailBusy || busy" @click="open(row)">{{ row.status === 'PREVIEW' ? '继续核对' : '查看结果' }}</el-button></td></tr></tbody></table></details>
    <el-dialog :model-value="!!detail" title="导入记录" @close="detail = null"><template v-if="detail"><p>{{ batchStatusLabels[detail.status] || detail.status }}</p><p>{{ savedSummary(detail.summary) }}</p><p v-for="(issue, index) in [...detail.errors, ...detail.warnings]" :key="index">{{ issue.row ? `第${issue.row}行：` : '' }}{{ issue.message }}</p></template></el-dialog>
  </section>
</template>
<style scoped>
.other-actions { display:flex;align-items:center;gap:16px;flex-wrap:wrap;border-top:1px solid var(--line);padding:16px 0;margin-top:24px;font-size:13px;color:var(--ink-mute); }.recent { border-top:1px solid var(--line);padding-top:18px; }.recent summary { cursor:pointer;font-size:14px;font-weight:600; }.recent table { margin-top:14px; }.hint { color:var(--ink-mute);font-size:12px;margin-top:5px; }td { overflow-wrap:anywhere; }
</style>
