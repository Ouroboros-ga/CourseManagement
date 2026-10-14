<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getTeacherCollege, setTeacherCollege, type TeacherCollege } from '../../api/enrollment'
import type { TeacherAccountItem } from '../../api/accounts'
const props = defineProps<{ teachers: TeacherAccountItem[]; collegeId: string }>()
const emit = defineEmits<{ changed: [] }>()
const userId = ref(''), binding = ref<TeacherCollege | null>(null), busy = ref(false), error = ref('')
async function select() {
  binding.value = null
  const id = userId.value
  try { const result = await getTeacherCollege(id); if (id === userId.value) binding.value = result }
  catch (e) { error.value = e instanceof Error ? e.message : '归属加载失败' }
}
async function save() {
  if (!binding.value) return
  try { await ElMessageBox.confirm('教师将拥有当前学院全部教学与查课权限，原会话会撤销。原学院课程、任务和组不会迁移，请先完成交接。', '配置教师学院') }
  catch { return }
  busy.value = true
  try { binding.value = await setTeacherCollege(userId.value, props.collegeId, binding.value.lock_version); emit('changed'); ElMessage.success('已配置固定学院归属') }
  catch (e) { error.value = e instanceof Error ? e.message : '保存失败，请重新加载'; binding.value = null }
  finally { busy.value = false }
}
</script>
<template><h3>教师固定学院归属</h3><p>每个教师只绑定一个学院，并拥有本学院全部教学与查课权限；跨学院事务由管理员统筹。</p><el-alert v-if="error" :title="error" type="error" /><el-select v-model="userId" filterable placeholder="选择教师" @change="select"><el-option v-for="t in teachers.filter(t => t.roles?.includes('TEACHER_ADMIN') && !t.roles?.includes('SUPER_ADMIN'))" :key="t.id" :value="t.id" :label="`${t.display_name}（${t.username}）`" /></el-select><p v-if="binding">当前学院 ID：{{ binding.college_id || '尚未配置' }}；交接影响：{{ binding.handoff || '原资源归属保留' }}</p><el-button :disabled="!binding" :loading="busy" @click="save">绑定到当前学院</el-button></template>
