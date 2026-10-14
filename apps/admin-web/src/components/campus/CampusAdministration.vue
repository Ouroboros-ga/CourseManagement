<script setup lang="ts">
import { onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listTeacherAccounts, type TeacherAccountItem } from '../../api/accounts'
import { createCollege, createSchool, listSchools, updateCollege, type College, type School } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'
import TeacherCollegeEditor from './TeacherCollegeEditor.vue'
import { ContextEpoch } from '../../utils/contextEpoch'

const props = defineProps<{ college: College | null }>()
const emit = defineEmits<{ changed: [] }>()
const { saving, run } = useCampusMutation(() => props.college?.id || '', () => { emit('changed'); void load() })
const schools = ref<School[]>([])
const teachers = ref<TeacherAccountItem[]>([])
const error = ref('')
const basic = reactive({ schoolName: '', schoolCode: '', collegeName: '', collegeCode: '', renamed: props.college?.name || '' })
const epoch = new ContextEpoch(() => props.college?.id || '')
async function load(query = '') {
  const ticket = epoch.begin()
  try {
    const [schoolRows, accounts] = await Promise.all([
      listSchools(), listTeacherAccounts({ page_size: 100, status: 'ACTIVE', query })
    ])
    if (!ticket.isCurrent()) return
    schools.value = schoolRows; teachers.value = accounts.items; error.value = ''
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '加载失败' }
}
async function toggleCollege() {
  const row = props.college
  if (!row) return
  try {
    await ElMessageBox.confirm(row.status === 'ACTIVE' ? '停用后停止本学院配置的新写操作，已有配置保留。' : '恢复本学院配置？', '学院状态变更')
    await run(cid => updateCollege(cid, { status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE', lock_version: row.lock_version }))
  } catch { /* 用户取消 */ }
}
watch(() => props.college, (college) => { basic.renamed = college?.name || ''; void load() }, { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div v-if="!schools.length" class="admin-form">
    <h3>初始化学校</h3>
    <el-input v-model="basic.schoolName" placeholder="学校名称" />
    <el-input v-model="basic.schoolCode" placeholder="学校编码（字母、数字或下划线）" />
    <el-button type="primary" :loading="saving" :disabled="!basic.schoolName || !basic.schoolCode" @click="run(() => createSchool(basic.schoolName, basic.schoolCode))">创建学校</el-button>
  </div>
  <div v-else class="admin-form">
    <h3>{{ schools[0]?.name }} · 新建学院</h3>
    <el-input v-model="basic.collegeName" placeholder="学院名称" />
    <el-input v-model="basic.collegeCode" placeholder="学院编码" />
    <el-button type="primary" :loading="saving" :disabled="!basic.collegeName || !basic.collegeCode" @click="run(() => createCollege(schools[0]!.id, basic.collegeName, basic.collegeCode))">创建学院</el-button>
  </div>
  <template v-if="college">
    <div class="admin-form">
      <h3>当前学院：{{ college.name }}</h3>
      <el-input v-model="basic.renamed" placeholder="修改学院名称" />
      <el-button :disabled="saving || !basic.renamed.trim()" @click="run(cid => updateCollege(cid, { name: basic.renamed, lock_version: college!.lock_version }))">保存名称</el-button>
      <el-button :disabled="saving" @click="toggleCollege">{{ college.status === 'ACTIVE' ? '停用学院' : '恢复学院' }}</el-button>
    </div>
    <TeacherCollegeEditor :teachers="teachers" :college-id="college.id" @changed="emit('changed')" />
  </template>
</template>
<style scoped>
.admin-form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 20px 0; }
.admin-form :deep(.el-input) { max-width: 240px; }
</style>
