<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listGroups, type VolunteerGroup } from '../../api/campus'
import { groupMemberApi, type MemberCandidate } from '../../api/groupMembers'
import { useSessionStore } from '../../stores/session'
import { memberDates } from '../../utils/memberDates'

const props = defineProps<{ modelValue: boolean; initialStudent?: MemberCandidate | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const session = useSessionStore()
const groups = ref<VolunteerGroup[]>([]), candidates = ref<MemberCandidate[]>([]), selected = ref<MemberCandidate | null>(null)
const groupId = ref(''), keyword = ref(''), busy = ref(false), error = ref('')
const dates = reactive(memberDates(session.currentSemester))
const key = () => `${session.currentUser?.id}:${session.workspaceCollegeId}:${session.currentSemesterId}:${props.modelValue}`
let epoch = 0
let groupLoadVersion = 0
watch(key, async () => {
  epoch++
  const ticket = ++groupLoadVersion
  groups.value = []; candidates.value = []; selected.value = props.initialStudent || null; groupId.value = ''; error.value = ''; busy.value = false
  Object.assign(dates, memberDates(session.currentSemester))
  if (!props.modelValue) return
  busy.value = true
  try { const result = await listGroups(session.workspaceCollegeId); if (ticket === groupLoadVersion) groups.value = result }
  catch (e) { if (ticket === groupLoadVersion) error.value = e instanceof Error ? e.message : '组织读取失败' }
  finally { if (ticket === groupLoadVersion) busy.value = false }
}, { immediate: true })
watch(() => `${groupId.value}:${dates.from}:${dates.to}`, () => { epoch++; candidates.value = []; if (!props.initialStudent) selected.value = null; error.value = ''; busy.value = false })
const valid = computed(() => !!groupId.value && !!selected.value && dates.from < dates.to && session.currentSemester?.status === 'ACTIVE')
async function search() {
  const ticket = ++epoch, context = key(), gid = groupId.value
  if (!gid || !dates.from || dates.from >= dates.to) return
  busy.value = true; error.value = ''
  try {
    const result = await groupMemberApi.candidates(session.workspaceCollegeId, gid, session.currentSemesterId, dates.from, dates.to, keyword.value, false)
    if (ticket === epoch && context === key()) candidates.value = result
  } catch (e) { if (ticket === epoch) error.value = e instanceof Error ? e.message : '学籍查询失败' }
  finally { if (ticket === epoch) busy.value = false }
}
async function save() {
  if (!valid.value || busy.value || !selected.value) return
  const ticket = ++epoch, context = key()
  busy.value = true; error.value = ''
  try {
    await groupMemberApi.create('members', session.workspaceCollegeId, groupId.value, {
      student_id: selected.value.id, semester_id: session.currentSemesterId, effective_from: dates.from,
      effective_to: dates.to, enable_qualification: true
    })
    if (ticket === epoch && context === key()) { ElMessage.success('已开通资格并加入所选组'); emit('saved'); emit('update:modelValue', false) }
  } catch (e) { if (ticket === epoch) error.value = e instanceof Error ? e.message : '加入组织失败，未保存资格和成员' }
  finally { if (ticket === epoch) busy.value = false }
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="添加志愿者并选择组织" width="580px" append-to-body :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @update:model-value="emit('update:modelValue', $event)">
    <p>先选择组织，再从已有有效学籍中选人；一次保存开通本学期资格并加入该组。不创建学生、不退出其他组、不自动排班。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-width="130px" :disabled="busy">
      <el-form-item label="所属组织（必选）"><el-select v-model="groupId" placeholder="选择加入的志愿者组"><el-option v-for="group in groups" :key="group.id" :value="group.id" :label="group.name + (group.status === 'ACTIVE' ? '' : '（准备成员）')" /></el-select></el-form-item>
      <el-form-item label="生效日期"><el-date-picker v-model="dates.from" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="失效日期（不含）"><el-date-picker v-model="dates.to" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item v-if="!initialStudent" label="查找在籍学生"><el-input v-model="keyword" placeholder="姓名或学号" @keyup.enter="search" /><el-button :disabled="!groupId" @click="search">查询学籍</el-button></el-form-item>
      <el-form-item v-if="!initialStudent && candidates.length" label="选择学生"><el-select :model-value="selected?.id" @change="selected = candidates.find(row => row.id === $event) || null"><el-option v-for="candidate in candidates" :key="candidate.id" :value="candidate.id" :label="`${candidate.name}（${candidate.student_no}）`" /></el-select></el-form-item>
    </el-form>
    <p v-if="selected">已选学生：{{ selected.name }}（{{ selected.student_no }}）</p>
    <p v-if="!groups.length && !busy">请先在“志愿者组织”创建组；新增学生请先到“学生与班级”维护。</p>
    <template #footer><el-button :disabled="busy" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="busy" :disabled="!valid" @click="save">开通资格并加入所选组</el-button></template>
  </el-dialog>
</template>
