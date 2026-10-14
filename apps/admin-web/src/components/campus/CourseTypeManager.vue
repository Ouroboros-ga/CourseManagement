<script setup lang="ts">
import { reactive, shallowRef } from 'vue'
import { ElMessageBox } from 'element-plus'
import { createCourseType, updateCourseType, deleteCourseType, type CourseType } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'

const props = defineProps<{ collegeId: string; rows: CourseType[]; canManage: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { saving, run } = useCampusMutation(() => props.collegeId, () => emit('changed'))
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
  if (await run(cid => row ? updateCourseType(cid, row, body) : createCourseType(cid, body))) opened.value = false
}
async function remove(row: CourseType) {
  const cid = props.collegeId
  try {
    await ElMessageBox.confirm(`删除“${row.name}”？有引用的类型无法删除，可选择停用。`, '删除课程类型', { type: 'warning' })
    if (cid !== props.collegeId) return
    await run(id => deleteCourseType(id, row))
  } catch { /* 用户取消 */ }
}
</script>
<template>
  <el-button v-if="canManage" type="primary" :disabled="saving" @click="edit(null)">新建课程类型</el-button>
  <el-table :data="rows" empty-text="暂无课程类型，可新建普通课、早自习或其他分类">
    <el-table-column prop="name" label="名称" />
    <el-table-column prop="description" label="说明" />
    <el-table-column prop="sort_order" label="排序" width="80" />
    <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '启用' : '停用' }}</template></el-table-column>
    <el-table-column v-if="canManage" label="操作" width="220">
      <template #default="{ row }">
        <el-button link :disabled="saving" @click="edit(row)">编辑</el-button>
        <el-button link :disabled="saving" @click="run(cid => updateCourseType(cid, row, { status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' }))">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-button>
        <el-button link type="danger" :disabled="saving" @click="remove(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
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
