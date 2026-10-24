<script setup lang="ts">
import AppPagination from '../../components/AppPagination.vue'
import { onUnmounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listConfigurationImpacts, resolveConfigurationImpact, type ConfigurationImpactItem } from '../../api/configurationImpacts'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'
const props = defineProps<{ collegeId: string; capabilities: string[] }>()
const session = useSessionStore()
const rows = ref<ConfigurationImpactItem[]>([]), total = ref(0), page = ref(1), status = ref('OPEN')
const busy = ref(false), error = ref('')
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}`)
const labels: Record<string, string> = { OPEN: '待处置', KEEP: '保留原快照', CANCEL: '已取消', REASSIGNED: '已完成改派', unavailability: '获批不可用', member: '成员有效期', support: '历史授权变更（功能已停用）', group: '组规则', course_type: '课程类型', teaching_class: '教学班分类', time_version: '作息', time_binding: '教学班作息绑定', college: '学院' }
async function load() {
  const ticket = epoch.begin()
  try {
    const response = await listConfigurationImpacts(props.collegeId, page.value, status.value)
    if (!ticket.isCurrent()) return
    rows.value = response.items; total.value = response.total; error.value = ''
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '加载失败' }
}
async function resolve(row: ConfigurationImpactItem, decision: 'KEEP' | 'CANCEL' | 'REASSIGNED') {
  const ticket = epoch.begin(), cid = props.collegeId
  busy.value = true
  try {
    await ElMessageBox.confirm(decision === 'CANCEL' ? `取消任务 ${row.task_id}？沿用正式取消规则，保留历史记录。` : decision === 'REASSIGNED' ? `确认任务 ${row.task_id} 已通过排班流程完成新的受派？服务端将复核。` : `任务 ${row.task_id} 保留原时间、分类和受派，不跟随本次配置改写。`, '确认变更处置', { confirmButtonText: '确认', cancelButtonText: '取消' })
    if (!ticket.isCurrent()) return
    await resolveConfigurationImpact(cid, row, decision, '')
    if (ticket.isCurrent()) await load()
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '处置失败' }
  finally { busy.value = false }
}
watch(() => [props.collegeId, identityContext(session.currentUser), status.value, page.value], () => void load(), { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <h3>配置变更影响处置</h3>
  <p>历史任务保持原快照。先核对受影响任务；取消或有效改派后系统自动结清对应待办；未结清的事项可选择保留原快照。每次配置变更仍留痕。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-select v-model="status" :disabled="busy" @change="page = 1"><el-option value="OPEN" label="待处置" /><el-option value="" label="全部" /><el-option value="KEEP" label="保留原快照" /><el-option value="CANCEL" label="已取消" /><el-option value="REASSIGNED" label="已改派" /></el-select>
  <el-button :disabled="busy" @click="load">刷新</el-button>
  <el-table :data="rows" v-loading="busy">
    <el-table-column label="变更来源"><template #default="{ row }">{{ labels[row.source_kind] || row.source_kind }} #{{ row.source_id }} · v{{ row.source_version }}</template></el-table-column>
    <el-table-column prop="snapshot.inspection_date" label="任务日期" />
    <el-table-column label="任务"><template #default="{ row }">#{{ row.task_id }} {{ row.snapshot.course_name }}</template></el-table-column>
    <el-table-column label="当前受派"><template #default="{ row }">{{ row.current_assignment?.volunteer_user_id || '未派' }}</template></el-table-column>
    <el-table-column label="状态"><template #default="{ row }">{{ labels[row.status] }}</template></el-table-column>
    <el-table-column label="处置" min-width="260"><template #default="{ row }"><template v-if="row.status === 'OPEN'">
      <el-button v-if="capabilities.includes('inspection.generate')" :disabled="busy || row.canceled" @click="resolve(row, 'KEEP')">保留</el-button>
      <el-button v-if="capabilities.includes('inspection.cancel')" :disabled="busy" @click="resolve(row, 'CANCEL')">{{ row.canceled ? '登记已取消' : '取消任务' }}</el-button>
      <el-button v-if="capabilities.includes('assignment.manage')" :disabled="busy || row.canceled" @click="resolve(row, 'REASSIGNED')">核对历史改派</el-button>
    </template></template></el-table-column>
  </el-table>
  <AppPagination v-model:current-page="page" :page-size="50" :total="total" />
</template>
