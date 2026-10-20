<script setup lang="ts">
import PaginatedTable from '../PaginatedTable.vue'
import { computed, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { applyOwnership, listUnresolvedOwnership, previewOwnership, type College, type OwnershipItem, type OwnershipKind, type OwnershipMappings, type OwnershipPreview } from '../../api/campus'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'
import { useSessionStore } from '../../stores/session'

const props = defineProps<{ colleges: College[] }>()
const session = useSessionStore()
const kind = ref<OwnershipKind>('administrative_class')
const kinds: Record<OwnershipKind, string> = { administrative_class: '行政班', teaching_class: '教学班', import_batch: '独立导入批次', report: '旧报表' }
const resourceLabels: Record<string, string> = { ...kinds, course_schedule: '课表', inspection_task: '查课任务' }
const conflictLabels: Record<string, string> = { KNOWN_OWNER_IMMUTABLE: '已确定归属，须使用专门的迁院流程', PARENT_OWNER_CONFLICT: '关联业务所属学院不一致', PARENT_OWNER_UNRESOLVED: '部分关联业务归属尚未确定' }
const rows = shallowRef<OwnershipItem[]>([])
const targets = reactive<Record<string, string>>({})
const after = ref('0')
const next = ref<string | null>(null)
const busy = ref(false)
const error = ref('')
const preview = shallowRef<OwnershipPreview | null>(null)
const submitted = shallowRef<OwnershipMappings | null>(null)
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${kind.value}:${after.value}`)
let active = true
onUnmounted(() => { active = false; epoch.invalidate() })
const activeColleges = computed(() => props.colleges.filter(c => c.status === 'ACTIVE'))
function clearPreview() { preview.value = null; submitted.value = null }
async function load() {
  clearPreview()
  for (const key of Object.keys(targets)) delete targets[key]
  rows.value = []
  const ticket = epoch.begin()
  busy.value = true
  error.value = ''
  try {
    const result = await listUnresolvedOwnership(kind.value, after.value)
    if (!active || !ticket.isCurrent()) return
    rows.value = result.items
    next.value = result.next_after_id
  } catch (e) {
    if (active && ticket.isCurrent()) error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    if (active && ticket.isCurrent()) busy.value = false
  }
}
watch([kind, () => session.currentUser?.id], () => { after.value = '0'; void load() }, { immediate: true })
watch(targets, clearPreview)
async function inspect() {
  const mapping: OwnershipMappings = { [kind.value]: Object.fromEntries(Object.entries(targets).filter(([, value]) => value)) }
  const ticket = epoch.begin()
  busy.value = true
  error.value = ''
  try {
    const result = await previewOwnership(mapping)
    if (!active || !ticket.isCurrent()) return
    submitted.value = mapping
    preview.value = result
  } catch (e) {
    if (active && ticket.isCurrent()) error.value = e instanceof Error ? e.message : '预览失败'
  } finally {
    if (active && ticket.isCurrent()) busy.value = false
  }
}
async function confirm() {
  if (!preview.value || !submitted.value || busy.value) return
  const result = preview.value
  const mapping = submitted.value
  const ticket = epoch.begin()
  busy.value = true
  try {
    await ElMessageBox.confirm(`确认回填 ${result.changes.length} 条业务归属？已确定归属不能通过本工具迁院。`, '确认存量归属')
    if (!active || !ticket.isCurrent() || preview.value !== result) return
    const saved = await applyOwnership(mapping, result.revision)
    if (!active || !ticket.isCurrent()) return
    ElMessage.success(`已回填 ${saved.updated} 条归属`)
    await load()
  } catch (e) {
    if (active && ticket.isCurrent() && e instanceof Error) {
      error.value = e.message
      clearPreview()
    }
  } finally {
    if (active && ticket.isCurrent()) busy.value = false
  }
}
</script>
<template>
  <el-alert title="明确确认存量归属。旧学院文本仅供核对，不会自动映射；归属回填完成后仍需通过所有业务入口的隔离验收。" type="info" :closable="false" />
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="ownership-toolbar">
    <el-select v-model="kind" :disabled="busy" aria-label="待核对资源类型">
      <el-option v-for="(label, value) in kinds" :key="value" :value="value" :label="label" />
    </el-select>
    <el-button :disabled="busy" @click="after = '0'; load()">返回首批 / 刷新</el-button>
    <el-button :disabled="busy || !next" @click="after = next!; load()">下一批</el-button>
  </div>
  <PaginatedTable :data="rows" v-loading="busy" empty-text="当前批次没有待核对资源">
    <el-table-column prop="id" label="ID" width="120" />
    <el-table-column prop="label" label="资源" />
    <el-table-column prop="legacy_college_text" label="旧学院文本（仅参考）" />
    <el-table-column label="明确所属学院">
      <template #default="{ row }"><el-select v-model="targets[row.id]" clearable :disabled="busy" placeholder="暂不回填">
        <el-option v-for="college in activeColleges" :key="college.id" :value="college.id" :label="college.name" />
      </el-select></template>
    </el-table-column>
  </PaginatedTable>
  <el-button :disabled="busy" @click="inspect">预览归属与关联影响</el-button>
  <template v-if="preview">
    <p>待回填 {{ preview.changes.length }} 条，冲突 {{ preview.conflicts.length }} 条。</p>
    <p>仍未确定：{{ Object.entries(preview.unresolved).map(([name, count]) => `${resourceLabels[name] || name} ${count} 条`).join('；') }}</p>
    <PaginatedTable :data="preview.conflicts" v-if="preview.conflicts.length">
      <el-table-column label="资源类型"><template #default="{ row }">{{ resourceLabels[row.kind] || row.kind }}</template></el-table-column><el-table-column prop="id" label="ID" /><el-table-column label="冲突原因"><template #default="{ row }">{{ conflictLabels[row.reason] || row.reason }}</template></el-table-column>
    </PaginatedTable>
    <PaginatedTable :data="preview.changes" max-height="360">
      <el-table-column label="资源类型"><template #default="{ row }">{{ resourceLabels[row.kind] || row.kind }}</template></el-table-column><el-table-column prop="id" label="ID" /><el-table-column label="所属学院">
        <template #default="{ row }">{{ colleges.find(c => c.id === row.college_id)?.name || row.college_id }}</template>
      </el-table-column>
    </PaginatedTable>
    <el-button type="primary" :disabled="busy || !preview.changes.length || !!preview.conflicts.length" @click="confirm">确认本次回填</el-button>
  </template>
</template>
<style scoped>
.ownership-toolbar { display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
</style>
