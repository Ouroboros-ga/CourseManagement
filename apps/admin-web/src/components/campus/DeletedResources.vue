<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { request } from '../../api/http'
import { useSessionStore } from '../../stores/session'

const props = defineProps<{ collegeId: string; kind: 'groups' | 'course-types' }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore()
const rows = ref<{ id: string; name: string; lock_version: number }[]>([]), open = ref(false), busy = ref(false), error = ref('')
let epoch = 0
watch(() => `${session.currentUser?.id}:${props.collegeId}:${props.kind}`, () => { epoch++; rows.value = []; open.value = false; busy.value = false; error.value = '' })
async function load() {
  const ticket = ++epoch, cid = props.collegeId
  busy.value = true; error.value = ''
  try {
    const listKind = props.kind === 'groups' ? 'volunteer-groups' : props.kind
    const result = await request<typeof rows.value>(`/api/v1/colleges/${encodeURIComponent(cid)}/${listKind}?deleted_only=true`)
    if (ticket === epoch) rows.value = result
  } catch (e) { if (ticket === epoch) error.value = e instanceof Error ? e.message : '读取失败' }
  finally { if (ticket === epoch) busy.value = false }
}
async function restore(row: typeof rows.value[number]) {
  const cid = props.collegeId, kind = props.kind, userId = session.currentUser?.id
  try {
    const result = await ElMessageBox.prompt('恢复后保持停用状态。可修改名称避免与新建记录重名；原有专属授权不会自动恢复。', '恢复记录', { inputValue: row.name, inputValidator: value => !!value?.trim() || '请输入名称' })
    if (cid !== props.collegeId || kind !== props.kind || userId !== session.currentUser?.id) return
    busy.value = true
    await request(`/api/v1/colleges/${encodeURIComponent(cid)}/${kind}/${row.id}/restore-deleted`, { method: 'POST', body: JSON.stringify({ lock_version: row.lock_version, name: result.value }) })
    if (cid !== props.collegeId || kind !== props.kind || userId !== session.currentUser?.id) return
    ElMessage.success('已恢复为停用状态'); emit('changed'); await load()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(e instanceof Error ? e.message : '恢复失败') }
  finally { if (cid === props.collegeId && kind === props.kind) busy.value = false }
}
</script>
<template>
  <el-button link @click="open = true; load()">已删除记录</el-button>
  <el-dialog v-model="open" title="已删除记录（历史保留）" width="560px" :show-close="!busy" :close-on-click-modal="false">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <PaginatedTable :data="rows" v-loading="busy" empty-text="没有可恢复记录；彻底删除的未使用数据不在此处显示">
      <el-table-column prop="name" label="名称" /><el-table-column label="操作" width="100"><template #default="{ row }"><el-button link :disabled="busy" @click="restore(row)">恢复</el-button></template></el-table-column>
    </PaginatedTable>
  </el-dialog>
</template>
