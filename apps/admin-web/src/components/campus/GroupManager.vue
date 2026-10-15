<script setup lang="ts">
import { computed, reactive, shallowRef } from 'vue'
import { ElMessageBox } from 'element-plus'
import { createGroup, deleteGroup, publishGroup, updateGroup, type CourseType, type GroupConfiguration, type VolunteerGroup } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'
import { useConfigurationImpact } from '../../composables/useConfigurationImpact'
import GroupRuleEditor from './GroupRuleEditor.vue'

const props = defineProps<{ collegeId: string; rows: VolunteerGroup[]; types: CourseType[]; userId: string; canManage: boolean; canPublish: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { saving, run } = useCampusMutation(() => props.collegeId, () => emit('changed'))
const confirmImpact = useConfigurationImpact(() => props.collegeId)
const updateExisting = (row: VolunteerGroup, body: Parameters<typeof updateGroup>[2]) => run(async cid => {
  const revision = await confirmImpact('groups', row.id)
  return updateGroup(cid, row, body, revision)
})
const selected = shallowRef<VolunteerGroup | null>(null)
const editing = shallowRef(false)
const configuring = shallowRef(false)
const form = reactive({ name: '', starts_on: null as string | null, ends_on: null as string | null })
const typesById = computed(() => new Map(props.types.map(row => [row.id, row.name])))
const scopeName = (row: VolunteerGroup) => row.configuration?.course_type_ids.map(id => typesById.value.get(id) || '类型已不可见').join('、') || '未发布范围'
function edit(row: VolunteerGroup | null) {
  selected.value = row
  Object.assign(form, row ? { name: row.name, starts_on: row.starts_on, ends_on: row.ends_on } : { name: '', starts_on: null, ends_on: null })
  editing.value = true
}
async function save() {
  const row = selected.value
  const body = { ...form }
  if (await (row ? updateExisting(row, body) : run(cid => createGroup(cid, { ...body, owner_user_id: props.userId })))) editing.value = false
}
async function publish(configuration: GroupConfiguration) {
  const row = selected.value
  if (!row) return
  if (await run(async cid => {
    const revision = await confirmImpact('groups', row.id)
    return publishGroup(cid, row, configuration, revision)
  })) configuring.value = false
}
async function remove(row: VolunteerGroup) {
  try {
    await ElMessageBox.confirm(`删除“${row.name}”？已有配置历史的组只能停用。`, '删除志愿者组', { type: 'warning' })
    await run(cid => deleteGroup(cid, row))
  } catch { /* 用户取消 */ }
}
</script>
<template>
  <el-button v-if="canManage" type="primary" :disabled="saving" @click="edit(null)">新建志愿者组</el-button>
  <el-table :data="rows" empty-text="暂无志愿者组">
    <el-table-column prop="name" label="组织名称" />
    <el-table-column label="查课范围"><template #default="{ row }">{{ scopeName(row) }}</template></el-table-column>
    <el-table-column label="状态" width="100"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '启用' : row.status === 'DRAFT' ? '草稿' : '停用' }}</template></el-table-column>
    <el-table-column label="配置版本" prop="config_version" width="90" />
    <el-table-column label="操作" width="280">
      <template #default="{ row }">
        <el-button v-if="canManage" link :disabled="saving" @click="edit(row)">编辑</el-button>
        <el-button v-if="canPublish" link :disabled="saving" @click="selected = row; configuring = true">范围与规则</el-button>
        <el-button v-if="canManage" link :disabled="saving" @click="updateExisting(row, { status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' })">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-button>
        <el-button v-if="canManage" link type="danger" :disabled="saving" @click="remove(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-dialog v-model="editing" :title="selected ? '编辑志愿者组' : '新建志愿者组'" width="500px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
    <el-form label-width="90px">
      <el-form-item label="名称"><el-input v-model="form.name" maxlength="128" /></el-form-item>
      <el-form-item label="有效期开始"><el-date-picker v-model="form.starts_on" value-format="YYYY-MM-DD" placeholder="不限开始日期" /></el-form-item>
      <el-form-item label="有效期结束"><el-date-picker v-model="form.ends_on" value-format="YYYY-MM-DD" placeholder="不限结束日期" /></el-form-item>
      <el-form-item v-if="!selected" label="负责人">默认由当前创建人负责；负责人交接页面随成员管理阶段提供。</el-form-item>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="editing = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">保存</el-button></template>
  </el-dialog>
  <el-dialog v-model="configuring" :title="`${selected?.name || ''} · 查课范围与冲突规则`" width="680px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
    <GroupRuleEditor v-if="selected && configuring" :key="selected.id" :group-id="selected.id" :college-id="collegeId" :initial="selected.configuration" :types="types" :saving="saving" @publish="publish" />
  </el-dialog>
</template>
