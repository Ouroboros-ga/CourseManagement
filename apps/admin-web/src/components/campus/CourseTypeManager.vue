<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { reactive, shallowRef } from 'vue'
import { createCourseType, updateCourseType, type CourseType } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'
import { useConfigurationImpact } from '../../composables/useConfigurationImpact'
import { deleteManagedResource } from '../../composables/useResourceDeletion'
import DeletedResources from './DeletedResources.vue'

const props = defineProps<{ collegeId: string; rows: CourseType[]; canManage: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { saving, run } = useCampusMutation(() => props.collegeId, () => emit('changed'))
const confirmImpact = useConfigurationImpact(() => props.collegeId)
const updateExisting = (row: CourseType, body: Partial<CourseType>) => run(async cid => {
  const revision = await confirmImpact('course-types', row.id)
  return updateCourseType(cid, row, body, revision)
})
const editing = shallowRef<CourseType | null>(null)
const opened = shallowRef(false)
const form = reactive({ name: '', description: '', display_color: '#409EFF', sort_order: 0 })
function edit(row: CourseType | null) {
  editing.value = row
  Object.assign(form, row ? { name: row.name, description: row.description, display_color: row.display_color, sort_order: row.sort_order } : { name: '', description: '', display_color: '#409EFF', sort_order: 0 })
  opened.value = true
}
async function save() {
  const row = editing.value
  const body = { ...form }
  if (await (row ? updateExisting(row, body) : run(cid => createCourseType(cid, body)))) opened.value = false
}
async function remove(row: CourseType) {
  const cid = props.collegeId
  await run(id => deleteManagedResource(id, 'course-types', row, () => cid === props.collegeId))
}
</script>
<template>
  <el-button v-if="canManage" type="primary" :disabled="saving" @click="edit(null)">新建课程类型</el-button>
  <DeletedResources v-if="canManage" :college-id="collegeId" kind="course-types" @changed="emit('changed')" />
  <PaginatedTable :data="rows" empty-text="暂无课程类型，可新建普通课、早自习或其他分类">
    <el-table-column prop="name" label="名称" />
    <el-table-column prop="description" label="说明" />
    <el-table-column prop="sort_order" label="排序" width="80" />
    <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '启用' : '停用' }}</template></el-table-column>
    <el-table-column v-if="canManage" label="操作" width="220">
      <template #default="{ row }">
        <el-button link :disabled="saving" @click="edit(row)">编辑</el-button>
        <el-button link :disabled="saving" @click="updateExisting(row, { status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' })">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-button>
        <el-button link type="danger" :disabled="saving" @click="remove(row)">删除</el-button>
      </template>
    </el-table-column>
  </PaginatedTable>
  <el-dialog v-model="opened" :title="editing ? '编辑课程类型' : '新建课程类型'" width="480px" :close-on-click-modal="false" :show-close="!saving" :close-on-press-escape="!saving">
    <el-form label-width="70px" @submit.prevent="save">
      <el-form-item label="名称"><el-input v-model="form.name" maxlength="128" /></el-form-item>
      <el-form-item label="说明"><el-input v-model="form.description" type="textarea" maxlength="512" /></el-form-item>
      <el-form-item label="颜色"><el-color-picker v-model="form.display_color" /></el-form-item>
      <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" :max="100000" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="opened = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">保存</el-button></template>
  </el-dialog>
</template>
