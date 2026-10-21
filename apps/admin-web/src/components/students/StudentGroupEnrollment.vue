<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listGroups, type VolunteerGroup } from '../../api/campus'
import { groupMemberApi, type GroupMember } from '../../api/groupMembers'
import { useSessionStore } from '../../stores/session'

const props = defineProps<{ studentId: string; name: string }>()
const session = useSessionStore()
const open = ref(false), busy = ref(false), error = ref(''), groupId = ref('')
const groups = ref<VolunteerGroup[]>([]), rows = ref<GroupMember[]>([]), from = ref(''), to = ref('')
const key = () => `${session.currentUser?.id}:${session.workspaceCollegeId}:${session.currentSemesterId}:${props.studentId}`
let epoch = 0
watch(key, () => { epoch++; open.value = false; groups.value = []; rows.value = []; busy.value = false })
const existing = computed(() => rows.value.filter(row => row.student_id === props.studentId))
async function loadRows() {
  const ticket = ++epoch, context = key()
  rows.value = []; error.value = ''; busy.value = true
  try {
    if (groupId.value) {
      const result = await groupMemberApi.list('members', session.workspaceCollegeId, groupId.value, session.currentSemesterId)
      if (ticket === epoch && context === key()) rows.value = result
    }
  } catch (e) { if (ticket === epoch) error.value = e instanceof Error ? e.message : '成员读取失败' }
  finally { if (ticket === epoch) busy.value = false }
}
async function start() {
  const ticket = ++epoch, context = key()
  open.value = true; error.value = ''; groupId.value = ''; rows.value = []; busy.value = true
  const semester = session.currentSemester
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
  from.value = [today, semester?.start_date || today].sort().at(-1)!
  const end = new Date(`${semester?.end_date || today}T00:00:00Z`)
  end.setUTCDate(end.getUTCDate() + 1); to.value = end.toISOString().slice(0, 10)
  try {
    const result = await listGroups(session.workspaceCollegeId)
    if (ticket === epoch && context === key()) groups.value = result
  } catch (e) { if (ticket === epoch) error.value = e instanceof Error ? e.message : '组织读取失败' }
  finally { if (ticket === epoch) busy.value = false }
}
async function save() {
  const context = key(), ticket = ++epoch
  busy.value = true; error.value = ''
  try {
    await groupMemberApi.create('members', session.workspaceCollegeId, groupId.value, {
      student_id: props.studentId, semester_id: session.currentSemesterId, effective_from: from.value, effective_to: to.value
    })
    if (context === key() && ticket === epoch) await loadRows()
  } catch (e) { if (ticket === epoch) error.value = e instanceof Error ? e.message : '加入组织失败' }
  finally { if (context === key()) busy.value = false }
}
</script>
<template>
  <el-button link @click="start">所属组织</el-button>
  <el-dialog v-model="open" :title="`${name} · 学期组织成员`" width="640px" append-to-body :close-on-click-modal="false" :show-close="!busy" @closed="epoch++">
    <p>学期资格表示可以参与查课；加入组织决定由哪个组排班。允许加入多个组，新增不会退出其他组，也不会自动下发任务。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-width="110px">
      <el-form-item label="志愿者组"><el-select v-model="groupId" :disabled="busy" placeholder="选择要查看或加入的组" @change="loadRows"><el-option v-for="group in groups" :key="group.id" :value="group.id" :label="group.name + (group.status === 'ACTIVE' ? '' : '（未启用，可准备成员）')" /></el-select></el-form-item>
      <el-form-item label="生效日期"><el-date-picker v-model="from" value-format="YYYY-MM-DD" :disabled="busy" /></el-form-item>
      <el-form-item label="失效日期（不含）"><el-date-picker v-model="to" value-format="YYYY-MM-DD" :disabled="busy" /></el-form-item>
    </el-form>
    <p v-for="row in existing" :key="row.id">已有成员记录：{{ row.effective_from }} 至 {{ row.effective_to }}（不含），{{ row.status === 'ACTIVE' ? '有效' : '已停用' }}。</p>
    <p v-if="groupId && !busy && !existing.length && !error">该学生尚未加入所选组。</p>
    <p v-if="!groups.length && !busy && !error">请先在“志愿者组织”新建组。</p>
    <template #footer><el-button :disabled="busy" @click="open = false">关闭</el-button><el-button type="primary" :loading="busy" :disabled="!groupId || !from || !to || from >= to || !!error" @click="save">加入所选组</el-button></template>
  </el-dialog>
</template>
