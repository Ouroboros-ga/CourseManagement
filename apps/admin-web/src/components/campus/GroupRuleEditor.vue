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
const replacesLegacyExceptions = Object.keys(form.type_overrides || {}).length > 0
  || Object.keys(form.teaching_class_overrides || {}).length > 0
form.type_overrides = {}
form.teaching_class_overrides = {}
form.class_mode ||= 'ALL_AUTHORIZED'
form.class_ids ||= []
const availableTypes = shallowRef<CourseType[]>(props.types)
const classes = shallowRef<ScopedAcademicRow[]>([])
const loading = shallowRef(false), loadError = shallowRef('')
let disposed = false
onUnmounted(() => { disposed = true })
onMounted(async () => {
  loading.value = true
  try {
    const references = await groupReferences(props.collegeId, props.groupId)
    if (disposed) return
    classes.value = references.classes.filter(row => row.status === 'ACTIVE')
    availableTypes.value = references.types

  } catch (error) { if (!disposed) loadError.value = error instanceof Error ? error.message : '读取范围失败' }
  finally { if (!disposed) loading.value = false }
})
const effects: { value: Effect; label: string }[] = [{ value: 'BLOCK', label: '禁止' }, { value: 'WARN', label: '人工确认后允许' }, { value: 'ALLOW', label: '允许' }]
const missingTypeIds = computed(() => form.course_type_ids.filter(id => !availableTypes.value.some(row => row.id === id)))
function publish() {
  if (loading.value || loadError.value || missingTypeIds.value.length) return
  const payload: GroupConfiguration = JSON.parse(JSON.stringify(form))
  if (payload.class_mode === 'ALL_AUTHORIZED') payload.class_ids = []
  emit('publish', payload)
}
</script>
<template>
  <el-form label-position="top">
    <h3>1. 这个组查什么课？</h3>
    <el-form-item label="负责的课程类型（至少一项）">
      <el-select v-model="form.course_type_ids" multiple placeholder="明确选择类型；留空不表示全部" style="width:100%">
        <el-option v-for="row in availableTypes" :key="row.id" :value="row.id" :label="row.name + (row.status === 'INACTIVE' ? '（停用）' : '')" :disabled="row.status !== 'ACTIVE'" />
        <el-option v-for="id in missingTypeIds" :key="id" :value="id" label="已不可见的历史类型（请移除）" disabled />
      </el-select>
    </el-form-item>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <h3>2. 查哪些班级？</h3>
    <el-form-item label="负责的班级范围">
      <el-radio-group v-model="form.class_mode"><el-radio value="ALL_AUTHORIZED">全部授权班级</el-radio><el-radio value="SPECIFIC">指定班级</el-radio></el-radio-group>
      <el-select v-if="form.class_mode === 'SPECIFIC'" v-model="form.class_ids" multiple filterable :loading="loading" placeholder="明确选择班级；新增班级不会自动纳入" style="width:100%">
        <el-option v-for="row in classes" :key="row.id" :value="row.id" :label="String(row.class_name)" />
      </el-select>
    </el-form-item>
    <h3>3. 组员什么时候可以查？</h3>
    <el-alert v-if="replacesLegacyExceptions" title="本次保存将清除旧的课程类型及教学班例外，统一采用下方默认课程冲突处理；历史任务不变。" type="warning" :closable="false" />
    <el-form-item label="默认课程冲突处理"><el-select v-model="form.default_effect"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select></el-form-item>
    <p>组员本人有课且时间重叠时，所有课程统一按此规则处理。</p>
    <el-form-item label="检查本人班级"><el-select v-model="form.own_class_effect"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select></el-form-item>
    <h3>4. 每个人安排多少次？</h3>
    <el-form-item label="每日 / 每周上限"><el-input-number v-model="form.daily_limit" :min="1" :max="100" /><el-input-number v-model="form.weekly_limit" :min="1" :max="700" /></el-form-item>
    <el-form-item label="上限统计口径"><el-radio-group v-model="form.count_scope"><el-radio value="ALL_GROUPS">本人所有组</el-radio><el-radio value="GROUP">仅本组</el-radio></el-radio-group></el-form-item>
    <el-form-item label="移动缓冲（分钟）"><el-input-number v-model="form.buffer_minutes" :min="0" :max="120" /></el-form-item>
    <p>另一组同时到场的任务始终禁止；允许本人课程重叠不会修改本人考勤。</p>
    <el-button type="primary" :loading="saving" :disabled="loading || !!loadError || !form.course_type_ids.length || missingTypeIds.length > 0 || (form.class_mode === 'SPECIFIC' && !form.class_ids?.length)" @click="publish">保存查课范围与排班规则</el-button>
  </el-form>
</template>

<style scoped>
h3 { margin: 22px 0 14px; }
p { font-size: var(--text-sm); color: var(--ink-mute); line-height: 1.7; }
</style>
