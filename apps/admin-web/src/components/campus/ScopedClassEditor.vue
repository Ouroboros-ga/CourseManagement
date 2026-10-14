<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { createScopedClass, updateScopedClass, type ScopedAcademicRow } from '../../api/scopedAcademic'
import { useCampusMutation } from '../../composables/useCampusMutation'

const props = defineProps<{ collegeId: string; opened: boolean; row: ScopedAcademicRow | null }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const form = reactive({ class_code: '', class_name: '', grade_year: '', reason: '' })
const yearValid = computed(() => !form.grade_year.trim() || (/^[0-9]{4}$/.test(form.grade_year.trim()) && Number(form.grade_year) >= 1900 && Number(form.grade_year) <= 2999))
watch(() => [props.opened, props.row], () => {
  if (!props.opened) return
  Object.assign(form, { class_code: String(props.row?.class_code || ''), class_name: String(props.row?.class_name || ''), grade_year: typeof props.row?.grade_year === 'number' ? String(props.row.grade_year) : '', reason: '' })
})
watch(() => props.collegeId, () => emit('close'))
const { saving, run } = useCampusMutation(() => props.collegeId, () => emit('changed'))
async function save() {
  const row = props.row
  if (!yearValid.value) return
  const body = { class_name: form.class_name, grade_year: form.grade_year.trim() ? Number(form.grade_year) : null, reason: form.reason }
  const saved = await run(cid => row ? updateScopedClass(cid, row, body) : createScopedClass(cid, { ...body, class_code: form.class_code }))
  if (saved) emit('close')
}
</script>
<template>
  <el-dialog :model-value="opened" :title="row ? '编辑本院行政班' : '新建本院行政班'" width="480px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @close="emit('close')">
    <el-form label-width="70px" @submit.prevent="save">
      <el-form-item label="班级代码"><el-input v-model="form.class_code" :disabled="!!row || saving" maxlength="64" /></el-form-item>
      <el-form-item label="班级名称"><el-input v-model="form.class_name" :disabled="saving" maxlength="128" /></el-form-item>
      <el-form-item label="入学年份" :error="yearValid ? '' : '填写 1900—2999 的四位年份，或留空'"><el-input v-model="form.grade_year" :disabled="saving" maxlength="4" inputmode="numeric" placeholder="选填" /></el-form-item>
      <el-form-item label="说明"><el-input v-model="form.reason" :disabled="saving" type="textarea" maxlength="512" placeholder="选填" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="emit('close')">取消</el-button><el-button type="primary" :loading="saving" :disabled="!yearValid || !form.class_name.trim() || (!row && !form.class_code.trim())" @click="save">保存</el-button></template>
  </el-dialog>
</template>
