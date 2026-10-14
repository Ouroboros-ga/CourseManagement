<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { type ScopedAcademicKind, type ScopedAcademicRow } from '../../api/scopedAcademic'
import { useScopedAcademicData } from '../../composables/useScopedAcademicData'
import ScopedClassEditor from './ScopedClassEditor.vue'

const props = defineProps<{ collegeId: string; capabilities: string[] }>()
const { options, kind, page, keyword, rows, total, busy, error, load, search } = useScopedAcademicData(() => props.collegeId, () => props.capabilities)
const opened = shallowRef(false)
const editing = shallowRef<ScopedAcademicRow | null>(null)
const canManageClasses = computed(() => props.capabilities.includes('academic.manage') && kind.value === 'administrative-classes')
watch(() => props.collegeId, () => { opened.value = false; editing.value = null })
const fields: Record<ScopedAcademicKind, { prop: string; label: string }[]> = {
  'administrative-classes': [{ prop: 'class_code', label: '班级代码' }, { prop: 'class_name', label: '班级名称' }, { prop: 'grade_year', label: '入学年份' }, { prop: 'status', label: '状态' }],
  students: [{ prop: 'student_no', label: '学号' }, { prop: 'name', label: '姓名' }, { prop: 'administrative_class_id', label: '行政班编号' }, { prop: 'status', label: '状态' }],
  'teaching-classes': [{ prop: 'class_code', label: '教学班代码' }, { prop: 'class_name', label: '教学班' }, { prop: 'teacher_name', label: '教师' }, { prop: 'status', label: '状态' }],
  schedules: [{ prop: 'weekday', label: '星期' }, { prop: 'start_period', label: '开始节次' }, { prop: 'end_period', label: '结束节次' }, { prop: 'classroom', label: '教室' }],
  courses: [{ prop: 'course_code', label: '课程代码' }, { prop: 'course_name', label: '课程名称' }, { prop: 'status', label: '状态' }],
  semesters: [{ prop: 'code', label: '学期代码' }, { prop: 'name', label: '名称' }, { prop: 'start_date', label: '开始日期' }, { prop: 'end_date', label: '结束日期' }],
  qualifications: [{ prop: 'student_id', label: '学生编号' }, { prop: 'semester_id', label: '学期编号' }, { prop: 'enabled', label: '有效资格' }]
}
const columns = computed(() => kind.value ? fields[kind.value] : [])
function edit(row: ScopedAcademicRow | null) { editing.value = row; opened.value = true }
function formatField(row: ScopedAcademicRow, column: { property: string }) {
  const value = row[column.property]
  if (column.property === 'status' && typeof value === 'string') return ({ ACTIVE: '启用', DISABLED: '停用', ARCHIVED: '归档' } as Record<string, string>)[value] || value
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (column.property === 'weekday' && typeof value === 'number') return `星期${['', '一', '二', '三', '四', '五', '六', '日'][value] || value}`
  return value == null ? '—' : String(value)
}
</script>
<template>
  <el-alert title="班级、学生、教学班、课表和资格按当前学院查询；课程和学期目录为学校共享只读资料。未知归属记录请由超管在存量归属核对中处理。" type="info" :closable="false" />
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="data-toolbar">
    <el-select v-model="kind" aria-label="本院基础数据类型"><el-option v-for="option in options" :key="option.value" :value="option.value" :label="option.label" /></el-select>
    <el-input v-if="kind !== 'schedules' && kind !== 'qualifications'" v-model="keyword" placeholder="名称关键词" clearable @keyup.enter="search" />
    <el-button :loading="busy" @click="search">查询</el-button>
    <el-button v-if="canManageClasses" :disabled="busy || !!error" type="primary" @click="edit(null)">新建行政班</el-button>
  </div>
  <el-table :data="rows" v-loading="busy" empty-text="当前学院没有符合条件的数据">
    <el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop" :label="column.label" :formatter="formatField" />
    <el-table-column v-if="canManageClasses" label="操作" width="100"><template #default="{ row }"><el-button link @click="edit(row)">编辑</el-button></template></el-table-column>
  </el-table>
  <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next, total" />
  <ScopedClassEditor :college-id="collegeId" :opened="opened && canManageClasses" :row="editing" @close="opened = false" @changed="load" />
</template>
<style scoped>
.data-toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.data-toolbar .el-input { width: 220px; }
.el-pagination { margin-top: 16px; }
</style>
