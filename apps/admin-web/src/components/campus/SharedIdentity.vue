<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { identityCandidates, previewIdentity, confirmIdentity, type IdentityPreview } from '../../api/sharedIdentity'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
const props = defineProps<{ collegeId: string; teachingId: string }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore(), target = ref(''), reason = ref(''), saving = ref(false), error = ref('')
const preview = shallowRef<IdentityPreview | null>(null)
const context = computed(() => `${identityContext(session.currentUser)}:${props.collegeId}:${props.teachingId}`)
const { data: candidates, error: loadError } = useWorkspaceRead(() => context.value, () => !!props.teachingId, () => identityCandidates(props.collegeId, props.teachingId))
const epoch = new ContextEpoch(() => `${context.value}:${target.value}:${reason.value}`)
watch([context, target, reason], () => { epoch.invalidate(); preview.value = null; error.value = ''; saving.value = false })
onUnmounted(() => epoch.invalidate())
async function run(confirm = false) {
  if (saving.value || !target.value || !reason.value.trim()) return
  const ticket = epoch.begin(), cid = props.collegeId, tid = props.teachingId
  saving.value = true; error.value = ''
  try {
    if (confirm && preview.value) {
      await confirmIdentity(cid, tid, target.value, reason.value, preview.value.revision)
      if (ticket.isCurrent()) emit('changed')
    } else {
      const result = await previewIdentity(cid, tid, target.value, reason.value)
      if (ticket.isCurrent()) preview.value = result
    }
  } catch (e) { if (ticket.isCurrent()) { preview.value = null; error.value = e instanceof Error ? e.message : '关联失败' } }
  finally { if (ticket.isLatest()) saving.value = false }
}
</script>
<template>
  <section data-unsaved-form>
    <p>下面只推荐上课资料一致的教学班。请结合教务资料确认是否确为同一教学班；同名平行班请保持独立。关联不会共享学生名单、管理权限或考勤结果。</p>
    <el-alert v-if="error || loadError" :title="error || loadError" type="error" :closable="false" />
    <PaginatedTable :data="candidates?.items || []" empty-text="没有匹配候选，保留学院独立记录即可正常使用">
      <el-table-column prop="college_name" label="维护学院" min-width="160" show-overflow-tooltip /><el-table-column prop="class_name" label="教学班" />
      <el-table-column label="时间地点"><template #default="{ row }"><p v-for="(m, i) in row.facts.meetings" :key="i">星期{{ m.weekday }} · 第{{ m.start_period }}—{{ m.end_period }}节 · {{ m.room }} · {{ m.teacher }} · 周次 {{ m.weeks.join('、') }}<br /><span v-for="t in m.times || []" :key="t.week">第{{ t.week }}周 {{ t.start || '时间待配置' }}—{{ t.end || '待配置' }}；</span></p></template></el-table-column>
      <el-table-column label="选择"><template #default="{ row }"><el-radio v-model="target" :value="row.teaching_class_id" :disabled="saving || row.already_linked">{{ row.already_linked ? '已关联' : '核对此班' }}</el-radio></template></el-table-column>
    </PaginatedTable>
    <el-input v-model="reason" type="textarea" placeholder="确认依据与原因（必填）" maxlength="512" :disabled="saving" />
    <el-button :disabled="!target || !reason.trim() || saving" @click="run()">预览关联</el-button>
    <template v-if="preview"><p>从 {{ preview.effective_from }} 起使用确认身份；历史任务不改写。后续来源发生时间地点冲突时，会阻止该班的新任务生成并要求核对。</p><el-button type="primary" :loading="saving" @click="run(true)">确认是同一教学班并关联</el-button></template>
  </section>
</template>
