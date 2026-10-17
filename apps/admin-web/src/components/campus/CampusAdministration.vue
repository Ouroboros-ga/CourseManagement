<script setup lang="ts">
import { onUnmounted, reactive, ref, watch } from 'vue'
import { listTeacherAccounts, type TeacherAccountItem } from '../../api/accounts'
import { createCollege, createSchool, listSchools, type College, type School } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'
import CollegeGrantEditor from './CollegeGrantEditor.vue'
import TeacherCollegeEditor from './TeacherCollegeEditor.vue'
import { ContextEpoch } from '../../utils/contextEpoch'

const props = defineProps<{ college: College | null }>()
const emit = defineEmits<{ changed: [] }>()
const { saving, run } = useCampusMutation(() => props.college?.id || '', () => { emit('changed'); void load() })
const schools = ref<School[]>([])
const teachers = ref<TeacherAccountItem[]>([])
const error = ref('')
const basic = reactive({ schoolName: '', schoolCode: '', collegeName: '', collegeCode: '' })
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
watch(() => props.college, () => { void load() }, { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>
<template>
  <section class="college-admin">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="!schools.length" class="admin-form">
      <h3>初始化学校</h3>
      <p class="admin-hint">全校只有一个学校主体；建好后本页其余操作都挂在它下面的学院上。</p>
      <el-input v-model="basic.schoolName" placeholder="学校名称" />
      <el-input v-model="basic.schoolCode" placeholder="学校编码（字母、数字或下划线）" />
      <el-button type="primary" :loading="saving" :disabled="!basic.schoolName || !basic.schoolCode" @click="run(() => createSchool(basic.schoolName, basic.schoolCode))">创建学校</el-button>
    </div>
    <div v-else class="admin-form">
      <h3>{{ schools[0]?.name }} · 新建学院</h3>
      <p class="admin-hint">新学院建好后，用上方“管理对象”切到它再配置授权与教师。</p>
      <el-input v-model="basic.collegeName" placeholder="学院名称" />
      <el-input v-model="basic.collegeCode" placeholder="学院编码" />
      <el-button type="primary" :loading="saving" :disabled="!basic.collegeName || !basic.collegeCode" @click="run(() => createCollege(schools[0]!.id, basic.collegeName, basic.collegeCode))">创建学院</el-button>
    </div>
    <template v-if="college">
      <CollegeGrantEditor :key="college.id" :college-id="college.id" :college-name="college.name" @changed="emit('changed')" />
      <TeacherCollegeEditor :teachers="teachers" :college-id="college.id" :college-name="college.name" @changed="emit('changed')" />
    </template>
  </section>
</template>
<style scoped>
.admin-form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 20px 0; }
.admin-form h3 { flex-basis: 100%; margin: 0; }
.admin-hint { flex-basis: 100%; margin: 0; font-size: 12px; color: var(--ink-mute); }
.admin-form :deep(.el-input) { max-width: 240px; }
</style>
