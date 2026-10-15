<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, shallowRef } from 'vue'
import { groupReferences, type CourseType, type Effect, type GroupConfiguration } from '../../api/campus'
import { type ScopedAcademicRow } from '../../api/scopedAcademic'

const props = defineProps<{ collegeId: string; groupId: string; initial: GroupConfiguration | null; types: CourseType[]; saving: boolean }>()
const emit = defineEmits<{ publish: [configuration: GroupConfiguration] }>()
const form = reactive<GroupConfiguration>(props.initial ? JSON.parse(JSON.stringify(props.initial)) : {
  course_type_ids: [], default_effect: 'BLOCK', type_overrides: {}, own_class_effect: 'BLOCK',
  task_conflict_effect: 'BLOCK', daily_limit: 3, weekly_limit: 10, count_scope: 'ALL_GROUPS', buffer_minutes: 0
})
form.class_mode ||= 'ALL_AUTHORIZED'
form.class_ids ||= []
form.teaching_class_overrides ||= {}
const availableTypes = shallowRef<CourseType[]>(props.types)
const classes = shallowRef<ScopedAcademicRow[]>([]), teaching = shallowRef<ScopedAcademicRow[]>([])
const loading = shallowRef(false), loadError = shallowRef(''), exceptionId = shallowRef('')
let disposed = false
onUnmounted(() => { disposed = true })
onMounted(async () => {
  loading.value = true
  try {
    const references = await groupReferences(props.collegeId, props.groupId)
    if (disposed) return
    classes.value = references.classes.filter(row => row.status === 'ACTIVE')
    teaching.value = references.teaching_classes.filter(row => row.status === 'ACTIVE')
    availableTypes.value = references.types

  } catch (error) { if (!disposed) loadError.value = error instanceof Error ? error.message : '读取范围失败' }
  finally { if (!disposed) loading.value = false }
})
const teachingName = (id: string) => String(teaching.value.find(row => row.id === id)?.class_name || `教学班 ${id}`)
function addException() {
  if (exceptionId.value) form.teaching_class_overrides![exceptionId.value] = 'BLOCK'
  exceptionId.value = ''
}
const effects: { value: Effect; label: string }[] = [{ value: 'BLOCK', label: '禁止' }, { value: 'WARN', label: '人工确认后允许' }, { value: 'ALLOW', label: '允许' }]
const missingTypeIds = computed(() => form.course_type_ids.filter(id => !availableTypes.value.some(row => row.id === id)))
function publish() {
  const payload: GroupConfiguration = JSON.parse(JSON.stringify(form))
  if (payload.class_mode === 'ALL_AUTHORIZED') payload.class_ids = []
  emit('publish', payload)
}
function updateOverride(id: string, value: Effect | '') {
  if (value) form.type_overrides[id] = value
  else delete form.type_overrides[id]
}
</script>
<template>
  <el-form label-position="top">
    <h3>本组检查哪些课</h3>
    <el-form-item label="负责的课程类型（至少一项）">
      <el-select v-model="form.course_type_ids" multiple placeholder="明确选择类型；留空不表示全部" style="width:100%">
        <el-option v-for="row in availableTypes" :key="row.id" :value="row.id" :label="row.name + (row.status === 'INACTIVE' ? '（停用）' : '')" :disabled="row.status !== 'ACTIVE'" />
        <el-option v-for="id in missingTypeIds" :key="id" :value="id" label="已不可见的历史类型（请移除）" disabled />
      </el-select>
    </el-form-item>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <el-form-item label="长期负责的班级范围">
      <el-radio-group v-model="form.class_mode"><el-radio value="ALL_AUTHORIZED">全部授权班级</el-radio><el-radio value="SPECIFIC">指定班级</el-radio></el-radio-group>
      <el-select v-if="form.class_mode === 'SPECIFIC'" v-model="form.class_ids" multiple filterable :loading="loading" placeholder="明确选择班级；新增班级不会自动纳入" style="width:100%">
        <el-option v-for="row in classes" :key="row.id" :value="row.id" :label="String(row.class_name)" />
      </el-select>
    </el-form-item>
    <h3>志愿者本人有课时怎么处理</h3>
    <el-form-item label="默认课程冲突处理"><el-select v-model="form.default_effect"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select></el-form-item>
    <el-form-item v-for="row in availableTypes" :key="row.id" :label="`本人正在上：${row.name}`">
      <el-select :model-value="form.type_overrides[row.id] || ''" placeholder="使用默认规则" @update:model-value="updateOverride(row.id, $event)">
        <el-option value="" label="使用默认规则" />
        <el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" />
      </el-select>
    </el-form-item>
    <el-form-item label="检查本人班级"><el-select v-model="form.own_class_effect"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select></el-form-item>
    <h3>本人具体教学班的冲突例外</h3>
    <p>具体教学班优先于类型规则；这不是被查课程的分类，也不改变本人考勤。</p>
    <el-select v-model="exceptionId" filterable :loading="loading" placeholder="选择本人可能参与的正式教学班"><el-option v-for="row in teaching" :key="row.id" :value="row.id" :label="`${row.class_name}（学期 ${row.semester_id}）`" /></el-select>
    <el-button :disabled="!exceptionId || saving" @click="addException">添加例外</el-button>
    <el-form-item v-for="(_effect, id) in form.teaching_class_overrides" :key="id" :label="teachingName(String(id))">
      <el-select v-model="form.teaching_class_overrides![id]"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select>
      <el-button :disabled="saving" @click="delete form.teaching_class_overrides![id]">移除例外</el-button>
    </el-form-item>
    <el-form-item label="每日 / 每周上限"><el-input-number v-model="form.daily_limit" :min="1" :max="100" /><el-input-number v-model="form.weekly_limit" :min="1" :max="700" /></el-form-item>
    <el-form-item label="上限统计口径"><el-radio-group v-model="form.count_scope"><el-radio value="ALL_GROUPS">本人所有组</el-radio><el-radio value="GROUP">仅本组</el-radio></el-radio-group></el-form-item>
    <el-form-item label="移动缓冲（分钟）"><el-input-number v-model="form.buffer_minutes" :min="0" :max="120" /></el-form-item>
    <p>另一组同时到场的任务始终禁止；允许本人课程重叠不会修改本人考勤。</p>
    <el-button type="primary" :loading="saving" :disabled="!form.course_type_ids.length || missingTypeIds.length > 0 || (form.class_mode === 'SPECIFIC' && !form.class_ids?.length)" @click="publish">一起发布范围与规则</el-button>
  </el-form>
</template>
