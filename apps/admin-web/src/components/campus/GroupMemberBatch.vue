<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { request } from '../../api/http'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'
const props = defineProps<{ collegeId: string; groupId: string; semesterId: string }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore()
const form = reactive({ text: '', from: '', to: '' })
const preview = ref<{ revision: string; count: number; items: { student_id: string; student_no: string; name: string }[] } | null>(null)
const busy = ref(false), error = ref(''), message = ref('')
const body = computed(() => ({ semester_id: props.semesterId, student_nos: form.text.split(/[\s,，;；]+/).filter(Boolean), effective_from: form.from, effective_to: form.to }))
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.groupId}:${props.semesterId}`)
const signature = () => JSON.stringify(body.value)
watch(signature, () => { epoch.invalidate(); preview.value = null; message.value = '' })
async function run(commit: boolean) {
  const ticket = epoch.begin(), payload = structuredClone(body.value), original = signature()
  const revision = preview.value?.revision
  busy.value = true; error.value = ''; message.value = ''
  try {
    const url = `/api/v1/colleges/${encodeURIComponent(props.collegeId)}/groups/${encodeURIComponent(props.groupId)}/members/batch/${commit ? 'commit' : 'preview'}`
    const result = await request<{ revision: string; count: number; items: { student_id: string; student_no: string; name: string }[]; created?: number }>(url,
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
    <p>每次最多200人；支持换行、空格和逗号分隔。全部通过学籍、学院和支援范围校验后再整批新增；不会自动授予志愿者资格或跨院支援权限。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <el-input v-model="form.text" type="textarea" :rows="4" placeholder="粘贴学号" :disabled="busy" />
    <el-date-picker v-model="form.from" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" :disabled="busy" />
    <el-date-picker v-model="form.to" type="date" value-format="YYYY-MM-DD" placeholder="结束日期（不包含当天）" :disabled="busy" />
    <el-button :disabled="busy || !body.student_nos.length || !form.from || !form.to" @click="run(false)">预览整批成员</el-button>
    <template v-if="preview"><el-table :data="preview.items"><el-table-column prop="student_no" label="学号" /><el-table-column prop="name" label="姓名" /></el-table><el-button type="primary" :disabled="busy" @click="run(true)">确认新增这 {{ preview.count }} 人</el-button></template>
  </el-collapse-item></el-collapse>
</template>
