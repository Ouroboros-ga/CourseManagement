<script setup lang="ts">
import PaginatedTable from '../PaginatedTable.vue'
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { request } from '../../api/http'
import type { MemberImportPreview } from '../../api/groupMembers'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'
import { memberDates } from '../../utils/memberDates'
const props = defineProps<{ collegeId: string; groupId: string; semesterId: string }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore()
const form = reactive({ text: '', ...memberDates(session.currentSemester) })
const preview = ref<MemberImportPreview | null>(null)
const busy = ref(false), error = ref(''), message = ref('')
const body = computed(() => ({ semester_id: props.semesterId, student_nos: form.text.split(/[\s,，;；]+/).filter(Boolean), effective_from: form.from, effective_to: form.to, enable_qualification: session.hasPermission('volunteer.manage'), skip_existing: true }))
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.groupId}:${props.semesterId}`)
const signature = () => JSON.stringify(body.value)
watch(signature, () => { epoch.invalidate(); preview.value = null; message.value = '' })
async function run(commit: boolean) {
  if (busy.value || (commit && !preview.value?.can_commit)) return
  const ticket = epoch.begin(), payload = structuredClone(body.value), original = signature()
  const revision = preview.value?.revision
  busy.value = true; error.value = ''; message.value = ''
  try {
    const url = `/api/v1/colleges/${encodeURIComponent(props.collegeId)}/groups/${encodeURIComponent(props.groupId)}/members/batch/${commit ? 'commit' : 'preview'}`
    const result = await request<MemberImportPreview & { created?: number }>(url,
      { method: 'POST', body: JSON.stringify({ ...payload, ...(commit ? { revision } : {}) }) })
    if (!ticket.isCurrent() || signature() !== original) return
    if (commit) { preview.value = null; message.value = `已整批新增 ${result.created} 位组成员`; emit('changed') }
    else preview.value = result
  } catch (e) { if (ticket.isCurrent()) { error.value = e instanceof Error ? e.message : '批量成员操作失败'; preview.value = null } }
  finally { busy.value = false }
}
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <el-collapse><el-collapse-item title="按学号批量新增成员" name="batch">
    <p>每次最多200人；支持换行、空格和逗号分隔。仅可加入本学院学生，学籍核对通过后整批新增；有资格管理权限时同时开通缺失的本学期资格。</p>
    <el-alert v-if="!session.hasPermission('volunteer.manage')" title="你没有开通资格权限。本次仅加入组织；请联系学院管理员核对本学期志愿者资格，否则不能排班。" type="warning" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <el-input v-model="form.text" type="textarea" :rows="4" placeholder="粘贴学号" :disabled="busy" />
    <el-date-picker v-model="form.from" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" :disabled="busy" />
    <el-date-picker v-model="form.to" type="date" value-format="YYYY-MM-DD" placeholder="结束日期（不包含当天）" :disabled="busy" />
    <el-button :disabled="busy || !body.student_nos.length || !form.from || !form.to" @click="run(false)">预览整批成员</el-button>
    <template v-if="preview"><el-alert v-if="!preview.can_commit" title="存在阻断项，整批不会保存。请按行修正或先维护学籍。" type="error" :closable="false" /><PaginatedTable :data="preview.items"><el-table-column prop="student_no" label="学号" /><el-table-column prop="name" label="姓名" /><el-table-column label="核对结果"><template #default="{ row }">{{ row.status === 'ADD' ? '将加入本组' : row.status === 'UNCHANGED' ? '已存在，保留' : row.message || '需修正' }}</template></el-table-column></PaginatedTable><el-button type="primary" :disabled="busy || !preview.can_commit" @click="run(true)">确认新增这 {{ preview.count }} 人</el-button></template>
  </el-collapse-item></el-collapse>
</template>
