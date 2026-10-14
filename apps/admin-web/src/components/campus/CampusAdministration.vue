<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listTeacherAccounts, type TeacherAccountItem } from '../../api/accounts'
import { campusActionLabels, createCollege, createGrant, createSchool, listGrants, listSchools, revokeGrant, updateCollege, type College, type School, type ScopedGrant } from '../../api/campus'
import { useCampusMutation } from '../../composables/useCampusMutation'
import { ContextEpoch } from '../../utils/contextEpoch'

const props = defineProps<{ college: College | null }>()
const emit = defineEmits<{ changed: [] }>()
const { saving, run } = useCampusMutation(() => props.college?.id || '', () => { emit('changed'); void load() })
const schools = ref<School[]>([])
const teachers = ref<TeacherAccountItem[]>([])
const grants = ref<ScopedGrant[]>([])
const error = ref('')
const basic = reactive({ schoolName: '', schoolCode: '', collegeName: '', collegeCode: '', renamed: props.college?.name || '' })
const authorization = reactive({ userId: '', actions: [] as string[], expiry: '' })
const epoch = new ContextEpoch(() => props.college?.id || '')
const names = computed(() => new Map(teachers.value.map(row => [row.id, row.display_name])))
async function load(query = '') {
  const ticket = epoch.begin()
  try {
    const [schoolRows, accounts, grantRows] = await Promise.all([
      listSchools(), listTeacherAccounts({ page_size: 100, status: 'ACTIVE', query }),
      props.college ? listGrants(props.college.id) : Promise.resolve([])
    ])
    if (!ticket.isCurrent()) return
    schools.value = schoolRows; teachers.value = accounts.items; grants.value = grantRows; error.value = ''
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '加载失败' }
}
async function addGrant() {
  const expires = authorization.expiry ? new Date(authorization.expiry).toISOString() : null
  await run(cid => createGrant(cid, authorization.userId, [...authorization.actions], expires))
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
    <h3>本学院配置授权</h3>
    <el-form label-width="90px">
      <el-form-item label="教师账号"><el-select v-model="authorization.userId" filterable remote :remote-method="load" placeholder="搜索教师姓名或账号"><el-option v-for="row in teachers" :key="row.id" :value="row.id" :label="`${row.display_name}（${row.username}）`" /></el-select></el-form-item>
      <el-form-item label="操作能力"><el-checkbox-group v-model="authorization.actions"><el-checkbox v-for="(label, action) in campusActionLabels" :key="action" :value="action">{{ label }}</el-checkbox></el-checkbox-group></el-form-item>
      <el-form-item label="有效期结束"><el-date-picker v-model="authorization.expiry" type="datetime" placeholder="为空则长期有效" /></el-form-item>
      <el-button type="primary" :loading="saving" :disabled="college.status !== 'ACTIVE' || !authorization.userId || !authorization.actions.length" @click="addGrant">授予本学院能力</el-button>
    </el-form>
    <el-table :data="grants">
      <el-table-column label="被授权人"><template #default="{ row }">{{ names.get(row.user_id) || '账号不在当前搜索结果' }}</template></el-table-column>
      <el-table-column label="能力"><template #default="{ row }">{{ row.actions.map((a: string) => campusActionLabels[a] || a).join('、') }}</template></el-table-column>
      <el-table-column label="状态"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '有效（以起止时间为准）' : '撤销' }}</template></el-table-column>
      <el-table-column label="操作"><template #default="{ row }"><el-button v-if="row.status === 'ACTIVE'" link type="danger" :disabled="saving" @click="run(cid => revokeGrant(cid, row))">撤销授权</el-button></template></el-table-column>
    </el-table>
  </template>
</template>
<style scoped>
.admin-form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 20px 0; }
.admin-form :deep(.el-input) { max-width: 240px; }
</style>
