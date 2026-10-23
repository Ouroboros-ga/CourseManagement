<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getManagerFunctions, setManagerFunctions, type ManagerFunctions } from '../../api/enrollment'
import { campusActionLabels } from '../../api/campus'
const props = defineProps<{ userId: string }>()
const emit = defineEmits<{ changed: [] }>()
const state = ref<ManagerFunctions | null>(null)
const visible = ref(false), busy = ref(false)
const labels: Record<string, string> = {
  'identity.binding.manage': '身份绑定', 'student.read': '学生名单查看', 'inspection.read': '任务查看',
  'inspection.roster.read': '任务名单查看', 'submission_deadline.read': '提交截止查看', 'attendance.read': '考勤查看',
  'attendance.correct': '考勤更正', 'objection.final_review': '学生异议处理', 'attendance.expected_count_adjust': '应到人数调整',
  'submission.read': '提交查看', 'submission.review': '历史审核兼容项（无需提交审核）', 'statistics.read': '本学院统计'
}
async function open() {
  busy.value = true
  try { state.value = await getManagerFunctions(props.userId); visible.value = true }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : '配置加载失败') }
  finally { busy.value = false }
}
async function save() {
  if (!state.value) return
  busy.value = true
  try { state.value = await setManagerFunctions(props.userId, [...state.value.allowed_actions], state.value.lock_version); visible.value = false; emit('changed'); ElMessage.success('已更新本学院功能，原管理会话已撤销') }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : '保存失败，请重新打开配置') }
  finally { busy.value = false }
}
</script>
<template>
  <el-button link :loading="busy" @click="open">本院功能设置</el-button>
  <el-dialog v-model="visible" title="学生负责人功能设置" width="640px" destroy-on-close>
    <p>仅适用于本人当前在读学院；转院或离校后结束原任命。志愿者提交即生效，学生异议一次审核。</p>
    <el-checkbox-group v-if="state" v-model="state.allowed_actions" class="function-options"><el-checkbox v-for="action in state.configurable_actions" :key="action" :value="action">{{ labels[action] || campusActionLabels[action] || '其他已授权功能' }}</el-checkbox></el-checkbox-group>
    <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" :loading="busy" @click="save">保存</el-button></template>
  </el-dialog>
</template>
<style scoped>
.function-options { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.function-options :deep(.el-checkbox) { margin: 0; height: auto; min-height: 32px; }
.function-options :deep(.el-checkbox__label) { white-space: normal; line-height: 1.5; }
</style>
