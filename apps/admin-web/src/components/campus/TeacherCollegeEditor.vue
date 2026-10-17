<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getTeacherCollege, setTeacherCollege, type TeacherCollege } from '../../api/enrollment'
import type { TeacherAccountItem } from '../../api/accounts'
const props = defineProps<{ teachers: TeacherAccountItem[]; collegeId: string; collegeName: string }>()
const emit = defineEmits<{ changed: [] }>()
const userId = ref(''), binding = ref<TeacherCollege | null>(null), busy = ref(false), error = ref('')
const alreadyBound = computed(() => !!binding.value && binding.value.college_id === props.collegeId)
const handoffSummary = computed(() => {
  const handoff = binding.value?.handoff
  const groups = Array.isArray(handoff?.active_owned_group_ids) ? handoff.active_owned_group_ids as string[] : []
  return `原学院资源保留在原学院${groups.length ? `；其担任负责人的 ${groups.length} 个志愿者组需另行移交` : '，本人未担任任何志愿者组负责人'}`
})
async function select() {
  binding.value = null
  const id = userId.value
  try { const result = await getTeacherCollege(id); if (id === userId.value) binding.value = result }
  catch (e) { error.value = e instanceof Error ? e.message : '归属加载失败' }
}
async function save() {
  if (!binding.value) return
  try {
    await ElMessageBox.confirm(
      `教师将拥有「${props.collegeName}」全部教学与查课权限，原会话会撤销。${handoffSummary.value}。`,
      '配置教师学院'
    )
  } catch { return }
  busy.value = true
  try {
    binding.value = await setTeacherCollege(userId.value, props.collegeId, binding.value.lock_version)
    emit('changed')
    ElMessage.success(`已绑定到「${props.collegeName}」`)
  }
  catch (e) { error.value = e instanceof Error ? e.message : '保存失败，请重新加载'; binding.value = null }
  finally { busy.value = false }
}
</script>
<template>
  <section class="teacher-college">
    <h3>教师固定学院归属</h3>
    <p>每个教师只绑定一个学院，并拥有该学院全部教学与查课权限；跨学院事务由管理员统筹。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-select v-model="userId" filterable placeholder="选择教师" @change="select">
      <el-option v-for="t in teachers.filter(t => t.roles?.includes('TEACHER_ADMIN') && !t.roles?.includes('SUPER_ADMIN'))" :key="t.id" :value="t.id" :label="`${t.display_name}（${t.username}）`" />
    </el-select>
    <p v-if="binding && !alreadyBound" class="binding-state">
      现在的归属：{{ binding.college_id ? `学院 ID ${binding.college_id}` : '尚未配置' }}。{{ handoffSummary }}。
    </p>
    <p v-else-if="binding" class="binding-state">该教师已经归属「{{ collegeName }}」。</p>
    <el-button :disabled="!binding || alreadyBound" :loading="busy" @click="save">绑定到「{{ collegeName }}」</el-button>
  </section>
</template>
<style scoped>
.teacher-college { margin-top: 28px; display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }
.teacher-college .el-select { width: 100%; max-width: 360px; }
.binding-state { font-size: 12px; color: var(--ink-soft); }
</style>
