<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listUnavailability, createUnavailability, getUnavailabilityImpact, decideUnavailability, type Unavailability } from '../../api/unavailability'
import type { GroupMember } from '../../api/groupMembers'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'
import { formatBeijingTime } from '../../utils/datetime'
const props = defineProps<{ collegeId: string; groupId: string; semesterId: string; members: GroupMember[]; canManage: boolean }>()
const session = useSessionStore()
const rows = ref<Unavailability[]>([]), total = ref(0), page = ref(1), busy = ref(false), error = ref('')
const form = reactive({ student_id: '', start: '', end: '', reason: '' })
const candidates = computed(() => [...new Map(props.members.filter(row => row.status === 'ACTIVE').map(row => [row.student_id, row])).values()])
const labels = { PENDING: '待审批', APPROVED: '已批准', REJECTED: '已拒绝', CANCELED: '已撤销' }
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.groupId}:${props.semesterId}`)
async function load() {
  if (!props.semesterId) return
  const ticket = epoch.begin()
  try {
    const result = await listUnavailability(props.collegeId, props.groupId, props.semesterId, page.value)
    if (!ticket.isCurrent()) return
    rows.value = result.items; total.value = result.total; error.value = ''
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '读取申请失败' }
}
async function create() {
  const ticket = epoch.begin(), cid = props.collegeId, gid = props.groupId, sid = props.semesterId
  busy.value = true; error.value = ''
  try {
    await createUnavailability(cid, gid, { student_id: form.student_id, semester_id: sid, reason: form.reason,
      starts_at: new Date(`${form.start.slice(0,16)}:00+08:00`).toISOString(), ends_at: new Date(`${form.end.slice(0,16)}:00+08:00`).toISOString() })
    if (ticket.isCurrent()) { form.reason = ''; await load() }
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '创建失败' }
  finally { busy.value = false }
}
async function decide(row: Unavailability, status: 'APPROVED' | 'REJECTED' | 'CANCELED') {
  const ticket = epoch.begin(), cid = props.collegeId, gid = props.groupId
  busy.value = true; error.value = ''
  try {
    const impact = await getUnavailabilityImpact(cid, gid, row.id)
    if (!ticket.isCurrent()) return
    if (impact.lock_version !== row.lock_version) throw new Error('申请已变化，请刷新')
    await ElMessageBox.confirm(status === 'APPROVED' ? `批准后此人在该时段所有组都不可新增排班。已有 ${impact.retained_assignment_count} 个受派保持不变，未来任务加入影响处置清单。` : status === 'CANCELED' ? '撤销后此时段恢复可用；现有任务和历史考勤不变。调整时间需撤销后重新申请。' : '拒绝此申请？待审批申请本身不影响排班。', '确认不可用申请处理')
    if (!ticket.isCurrent()) return
    await decideUnavailability(cid, gid, row, status, '', impact.revision)
    if (ticket.isCurrent()) await load()
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '审批失败' }
  finally { busy.value = false }
}
watch(() => [props.collegeId, props.groupId, props.semesterId, identityContext(session.currentUser), page.value], () => void load(), { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <el-collapse><el-collapse-item title="请假／不可用申请与审批" name="availability">
    <p>获批后限制本人所有组的新排班；已有受派保留。列表时间统一为北京时间，结束时刻不包含在不可用区间内。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form v-if="canManage" :disabled="busy" label-position="top">
      <el-form-item label="组成员"><el-select v-model="form.student_id" filterable><el-option v-for="row in candidates" :key="row.student_id" :value="row.student_id" :label="`${row.name || row.student_id}（${row.student_no || ''}）`" /></el-select></el-form-item>
      <el-form-item label="北京时间起止"><el-date-picker v-model="form.start" type="datetime" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="开始" /><el-date-picker v-model="form.end" type="datetime" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="结束" /></el-form-item>
      <el-form-item label="原因（选填）"><el-input v-model="form.reason" maxlength="512" /></el-form-item>
      <el-button :disabled="!form.student_id || !form.start || !form.end" @click="create">新增待审批申请</el-button>
    </el-form>
    <el-button :disabled="busy" @click="load">刷新</el-button>
    <el-table :data="rows" v-loading="busy">
      <el-table-column label="成员"><template #default="{ row }">{{ row.name || row.student_id }} {{ row.student_no }}</template></el-table-column>
      <el-table-column label="不可用时段" min-width="210"><template #default="{ row }">{{ formatBeijingTime(row.starts_at, 'minute') }} 至 {{ formatBeijingTime(row.ends_at, 'minute') }}</template></el-table-column>
      <el-table-column prop="reason" label="原因" />
      <el-table-column label="状态"><template #default="{ row }">{{ labels[row.status as keyof typeof labels] }}</template></el-table-column>
      <el-table-column v-if="canManage" label="审批" min-width="210"><template #default="{ row }">
        <el-button v-if="row.status === 'PENDING'" :disabled="busy" @click="decide(row, 'APPROVED')">查看影响并批准</el-button>
        <el-button v-if="row.status === 'PENDING'" :disabled="busy" @click="decide(row, 'REJECTED')">拒绝</el-button>
        <el-button v-if="row.status === 'PENDING' || row.status === 'APPROVED'" :disabled="busy" @click="decide(row, 'CANCELED')">撤销</el-button>
      </template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="prev,pager,next,total" />
  </el-collapse-item></el-collapse>
</template>
