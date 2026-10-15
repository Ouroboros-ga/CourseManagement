<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { campusActionLabels } from '../../api/campus'
import { confirmHandover, ownerCandidates, previewHandover, type HandoverPreview } from '../../api/organizationManagement'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
const props = defineProps<{ collegeId: string; groupId: string }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore(), keyword = ref(''), selected = ref(''), reason = ref('')
const preview = shallowRef<HandoverPreview | null>(null), saving = ref(false), error = ref('')
const context = computed(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.groupId}`)
const { data: candidates, error: readError } = useWorkspaceRead(() => `${context.value}:${keyword.value}`, () => !!props.groupId, () => ownerCandidates(props.collegeId, props.groupId, keyword.value))
const epoch = new ContextEpoch(() => `${context.value}:${selected.value}:${reason.value}`)
watch([context, selected, reason], () => { epoch.invalidate(); preview.value = null; saving.value = false; error.value = '' })
onUnmounted(() => epoch.invalidate())
async function run(confirm = false) {
  if (saving.value || !selected.value || !reason.value.trim()) return
  const ticket = epoch.begin(), cid = props.collegeId, gid = props.groupId
  saving.value = true; error.value = ''
  try {
    if (confirm && preview.value) {
      await confirmHandover(cid, gid, selected.value, reason.value, preview.value.revision)
      if (ticket.isCurrent()) emit('changed')
    } else {
      const result = await previewHandover(cid, gid, selected.value, reason.value)
      if (ticket.isCurrent()) preview.value = result
    }
  } catch (e) { if (ticket.isCurrent()) { preview.value = null; error.value = e instanceof Error ? e.message : '交接失败' } }
  finally { if (ticket.isCurrent()) saving.value = false }
}
</script>
<template>
  <section data-unsaved-form>
    <p>由教师或超管直接确认。任务及受派人保留；只撤销本组负责人专属授权，原有独立权限继续生效。</p>
    <el-alert v-if="error || readError" :title="error || readError" type="error" :closable="false" />
    <el-input v-model.lazy="keyword" placeholder="搜索本院账号姓名或登录名，回车查询" :disabled="saving" />
    <el-select v-model="selected" placeholder="选择新负责人账号" :disabled="saving"><el-option v-for="row in candidates || []" :key="row.id" :value="row.id" :label="`${row.display_name}（${row.username || row.id}）`" /></el-select>
    <el-input v-model="reason" type="textarea" placeholder="交接原因（必填，写入审计）" maxlength="512" :disabled="saving" />
    <el-button :disabled="saving || !selected || !reason.trim()" @click="run()">预览交接</el-button>
    <template v-if="preview">
      <p>新负责人：{{ preview.new_owner_name }}；保留 {{ preview.retained_task_ids.length }} 个任务；撤销 {{ preview.revoke_dedicated_grant_ids.length }} 条本组专属授权。</p>
      <el-alert v-if="preview.new_owner_web_login_ready === false" title="该账号尚无 Web 登录凭证。交接只调整负责人及授权，不自动创建登录名或密码；请按现有账号管理流程配置登录方式。" type="info" :closable="false" />
      <p>授予本组范围内：{{ preview.grant_actions.map(x => campusActionLabels[x] || x).join('、') }}</p>
      <p>原负责人仍有 {{ preview.old_owner_retained_sources.length }} 个其他权限来源；教师本院默认权限也会保留。</p>
      <el-button type="primary" :loading="saving" @click="run(true)">确认交接负责人及专属权限</el-button>
    </template>
  </section>
</template>
