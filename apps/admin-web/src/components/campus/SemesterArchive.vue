<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { confirmArchive, previewArchive, type ArchivePreview } from '../../api/campusManagement'
import { useSessionStore } from '../../stores/session'
import { markWorkspaceSaved } from '../../composables/useWorkspaceChanges'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
const session = useSessionStore(), sid = ref(session.currentSemesterId), reason = ref(''), saving = ref(false), error = ref(''), message = ref('')
const root = ref<HTMLElement | null>(null)
const preview = shallowRef<ArchivePreview | null>(null)
const context = computed(() => `${identityContext(session.currentUser)}:${sid.value}:${reason.value}`)
const epoch = new ContextEpoch(() => context.value)
watch(context, () => { epoch.invalidate(); preview.value = null; error.value = ''; message.value = ''; saving.value = false })
onUnmounted(() => epoch.invalidate())
const labels: Record<string, string> = { unfinished_task_ids: '未完成查课任务', pending_objection_ids: '待处理学生异议', open_impact_ids: '未处置配置影响', generating_report_version_ids: '生成中的报表' }
async function run(confirm = false) {
  if (saving.value || !sid.value || !reason.value.trim()) return
  const ticket = epoch.begin(), semester = sid.value, note = reason.value
  saving.value = true; error.value = ''
  try {
    if (confirm && preview.value) {
      await confirmArchive(semester, note, preview.value.revision)
      if (ticket.isCurrent()) { message.value = '学期已归档，档案、绑定、组织和附件均保留。历史纠错请使用考勤记录内的归档更正入口。'; preview.value = null; markWorkspaceSaved(root.value); await session.fetchAcademicContext() }
    } else {
      const result = await previewArchive(semester, note)
      if (ticket.isCurrent()) preview.value = result
    }
  } catch (e) { if (ticket.isCurrent()) { preview.value = null; error.value = e instanceof Error ? e.message : '归档失败' } }
  finally { if (ticket.isLatest()) saving.value = false }
}
</script>
<template>
  <section ref="root" data-unsaved-form>
    <h3>学校学期归档</h3><p>此操作影响全校该学期，由超管统一执行。切换学期不会自动归档；归档后日常业务只读，授权教师可按专门入口更正历史考勤。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-alert v-if="message" :title="message" type="success" :closable="false" />
    <el-select v-model="sid" placeholder="选择归档学期" :disabled="saving"><el-option v-for="s in session.semesters" :key="s.id" :value="s.id" :label="`${s.name}${s.status === 'ARCHIVED' ? '（已归档）' : ''}`" /></el-select>
    <el-input v-model="reason" type="textarea" placeholder="归档说明（必填）" maxlength="512" :disabled="saving" />
    <el-button :disabled="saving || !sid || !reason.trim()" @click="run()">检查归档条件</el-button>
    <template v-if="preview"><ul><li v-for="(ids, key) in preview.blockers" :key="key">{{ labels[key] || key }}：{{ ids.length }}{{ ids.length ? `（编号 ${ids.slice(0, 20).join('、')}）` : '' }}</li></ul><p>保留 {{ preview.published_report_version_ids.length }} 个正式报表版本；更正历史考勤不会覆盖这些版本。</p><el-button type="danger" :loading="saving" :disabled="!preview.can_archive" @click="run(true)">确认全校该学期归档</el-button></template>
  </section>
</template>
