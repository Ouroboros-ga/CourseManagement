<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { CourseType, Effect, GroupConfiguration } from '../../api/campus'

const props = defineProps<{ initial: GroupConfiguration | null; types: CourseType[]; saving: boolean }>()
const emit = defineEmits<{ publish: [configuration: GroupConfiguration] }>()
const form = reactive<GroupConfiguration>(props.initial ? JSON.parse(JSON.stringify(props.initial)) : {
  course_type_ids: [], default_effect: 'BLOCK', type_overrides: {}, own_class_effect: 'BLOCK',
  task_conflict_effect: 'BLOCK', daily_limit: 3, weekly_limit: 10, count_scope: 'ALL_GROUPS', buffer_minutes: 0
})
const effects: { value: Effect; label: string }[] = [{ value: 'BLOCK', label: '禁止' }, { value: 'WARN', label: '人工确认后允许' }, { value: 'ALLOW', label: '允许' }]
const missingTypeIds = computed(() => form.course_type_ids.filter(id => !props.types.some(row => row.id === id)))
function publish() {
  const payload: GroupConfiguration = JSON.parse(JSON.stringify(form))
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
        <el-option v-for="row in types" :key="row.id" :value="row.id" :label="row.name + (row.status === 'INACTIVE' ? '（停用）' : '')" :disabled="row.status !== 'ACTIVE'" />
        <el-option v-for="id in missingTypeIds" :key="id" :value="id" label="已不可见的历史类型（请移除）" disabled />
      </el-select>
    </el-form-item>
    <p>当前配置作用于本学院授权范围内的班级；指定班级和跨院支援随业务隔离阶段接入。</p>
    <h3>志愿者本人有课时怎么处理</h3>
    <el-form-item label="默认课程冲突处理"><el-select v-model="form.default_effect"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select></el-form-item>
    <el-form-item v-for="row in types" :key="row.id" :label="`本人正在上：${row.name}`">
      <el-select :model-value="form.type_overrides[row.id] || ''" placeholder="使用默认规则" @update:model-value="updateOverride(row.id, $event)">
        <el-option value="" label="使用默认规则" />
        <el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" />
      </el-select>
    </el-form-item>
    <el-form-item label="检查本人班级"><el-select v-model="form.own_class_effect"><el-option v-for="effect in effects" :key="effect.value" :value="effect.value" :label="effect.label" /></el-select></el-form-item>
    <el-form-item label="每日 / 每周上限"><el-input-number v-model="form.daily_limit" :min="1" :max="100" /><el-input-number v-model="form.weekly_limit" :min="1" :max="700" /></el-form-item>
    <el-form-item label="上限统计口径"><el-radio-group v-model="form.count_scope"><el-radio value="ALL_GROUPS">本人所有组</el-radio><el-radio value="GROUP">仅本组</el-radio></el-radio-group></el-form-item>
    <el-form-item label="移动缓冲（分钟）"><el-input-number v-model="form.buffer_minutes" :min="0" :max="120" /></el-form-item>
    <p>另一组同时到场的任务始终禁止；允许本人课程重叠不会修改本人考勤。</p>
    <el-button type="primary" :loading="saving" :disabled="!form.course_type_ids.length || missingTypeIds.length > 0" @click="publish">一起发布范围与规则</el-button>
  </el-form>
</template>
