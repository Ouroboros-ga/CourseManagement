<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { listRoleTargets, type RoleAssignmentTarget } from '../../api/accounts'
import { campusActionLabels, listCourseTypes, listGroups, listGrants, previewGrant, submitGrant, revokeGrant,
  type GrantBody, type ScopedGrant } from '../../api/campus'
import { listScopedAcademic } from '../../api/scopedAcademic'
import { ContextEpoch } from '../../utils/contextEpoch'

const props = defineProps<{ collegeId: string }>()
const emit = defineEmits<{ changed: [] }>()
const accounts = ref<RoleAssignmentTarget[]>([]), grants = ref<ScopedGrant[]>([])
const options = ref<{ id: string; name: string }[]>([])
const busy = ref(false), loadingOptions = ref(false), error = ref('')
const form = reactive({ user_id: '', actions: [] as string[], kind: 'GROUPS' as GrantBody['resource_scope']['kind'], ids: [] as string[], expires: '' })
const epoch = new ContextEpoch(() => props.collegeId)
const limited = new Set(['inspection.read', 'inspection.roster.read', 'inspection.roster.manage', 'inspection.generate', 'inspection.cancel', 'assignment.manage', 'assignment.change_review', 'submission.read', 'submission.review', 'attendance.read', 'attendance.correct', 'attendance.expected_count_adjust', 'objection.read', 'objection.final_review', 'volunteer.group.read', 'volunteer.group.manage', 'volunteer.member.manage', 'volunteer.config.publish'])
const actionOptions = computed(() => Object.entries(campusActionLabels).filter(([code]) => form.kind === 'COLLEGE' || (limited.has(code) && (form.kind === 'GROUPS' || !code.startsWith('volunteer.')))))
const accountName = (id: string) => accounts.value.find(row => row.id === id)?.display_name || `账号 ${id}`
async function load() {
  const ticket = epoch.begin()
  try {
    const [users, rows] = await Promise.all([listRoleTargets(), listGrants(props.collegeId)])
    if (!ticket.isCurrent()) return
    accounts.value = users.items.filter(row => row.status === 'ACTIVE'); grants.value = rows
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '读取授权失败' }
}
let optionSerial = 0
async function loadOptions() {
  const serial = ++optionSerial, cid = props.collegeId, kind = form.kind
  options.value = []; form.ids = []; form.actions = form.actions.filter(code => actionOptions.value.some(([allowed]) => allowed === code))
  if (kind === 'COLLEGE') return
  loadingOptions.value = true
  try {
    let rows: { id: string; name: string }[]
    if (kind === 'GROUPS') rows = (await listGroups(cid)).filter(row => row.status === 'ACTIVE').map(row => ({ id: row.id, name: row.name }))
    else if (kind === 'COURSE_TYPES') rows = (await listCourseTypes(cid)).filter(row => row.status === 'ACTIVE').map(row => ({ id: row.id, name: row.name }))
    else {
      rows = []
      for (let page = 1; ; page++) {
        const result = await listScopedAcademic(cid, 'teaching-classes', page, '')
        if (serial !== optionSerial || cid !== props.collegeId) return
        rows.push(...result.items.filter(row => row.status === 'ACTIVE').map(row => ({ id: row.id, name: String(row.class_name) })))
        if (page * result.page_size >= result.total) break
        if (!result.items.length) throw new Error('教学班范围已变化，请刷新')
      }
    }
    if (serial === optionSerial && cid === props.collegeId) options.value = rows
  } catch (e) { if (serial === optionSerial) error.value = e instanceof Error ? e.message : '读取范围失败' }
  finally { if (serial === optionSerial) loadingOptions.value = false }
}
function preset() {
  form.kind = 'GROUPS'
  form.actions = ['volunteer.group.read', 'volunteer.member.manage', 'inspection.read', 'inspection.roster.read', 'assignment.manage']
}
async function save() {
  const ticket = epoch.begin(), cid = props.collegeId
  busy.value = true; error.value = ''
  try {
    const body: GrantBody = { user_id: form.user_id, actions: [...form.actions], starts_at: null,
      expires_at: form.expires ? new Date(form.expires).toISOString() : null,
      resource_scope: { kind: form.kind, ids: [...form.ids] } }
    const preview = await previewGrant(cid, body)
    if (!ticket.isCurrent()) return
    const names = body.resource_scope.ids.map(id => options.value.find(row => row.id === id)?.name || id).join('、')
    await ElMessageBox.confirm(`向 ${accountName(body.user_id)} 授权：${preview.actions.map(code => campusActionLabels[code] || code).join('、')}。范围：${form.kind === 'COLLEGE' ? '整个学院（包括未来新增资源）' : names}。截止：${form.expires || '长期有效'}。指定组授权以当前发布的类型及班级范围为上限，扩大范围需重新授权。`, '确认学院授权', { confirmButtonText: '确认授予', cancelButtonText: '取消' })
    if (!ticket.isCurrent()) return
    await submitGrant(cid, { ...body, preview_revision: preview.revision })
    if (!ticket.isCurrent()) return
    emit('changed'); await load()
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '授权失败' }
  finally { busy.value = false }
}
async function revoke(row: ScopedGrant) {
  const ticket = epoch.begin(), cid = props.collegeId
  busy.value = true
  try {
    await ElMessageBox.confirm(`撤销 ${accountName(row.user_id)} 的此条授权？其他授权及本院教师默认权限保留。`, '撤销授权')
    if (!ticket.isCurrent()) return
    await revokeGrant(cid, row)
    if (!ticket.isCurrent()) return
    emit('changed'); await load()
  } catch (e) { if (ticket.isCurrent() && e !== 'cancel' && e !== 'close') error.value = e instanceof Error ? e.message : '撤销失败' }
  finally { busy.value = false }
}
watch(() => props.collegeId, () => { form.user_id = ''; form.actions = []; error.value = ''; void load(); void loadOptions() }, { immediate: true })
watch(() => form.kind, () => void loadOptions())
onUnmounted(() => { epoch.invalidate(); optionSerial++ })
</script>
<template>
  <section>
    <h3>跨学院与组织范围授权</h3>
    <p>教师默认管理本学院。这里配置额外授权；未选择的资源不开放。受限授权暂不支持导入、报表和全院教学数据动作。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" :disabled="busy">
      <el-button @click="preset">使用组织负责人配置</el-button>
      <el-form-item label="被授权账号"><el-select v-model="form.user_id" filterable><el-option v-for="row in accounts" :key="row.id" :value="row.id" :label="`${row.display_name}（${row.username || row.id}）`" /></el-select></el-form-item>
      <el-form-item label="资源范围"><el-select v-model="form.kind"><el-option value="GROUPS" label="指定志愿者组" /><el-option value="COURSE_TYPES" label="指定课程类型" /><el-option value="TEACHING_CLASSES" label="指定教学班" /><el-option value="COLLEGE" label="整个学院" /></el-select></el-form-item>
      <el-form-item v-if="form.kind !== 'COLLEGE'" label="明确选择资源"><el-select v-model="form.ids" multiple filterable :loading="loadingOptions"><el-option v-for="row in options" :key="row.id" :value="row.id" :label="row.name" /></el-select></el-form-item>
      <el-form-item label="允许操作"><el-select v-model="form.actions" multiple><el-option v-for="[code, label] in actionOptions" :key="code" :value="code" :label="label" /></el-select></el-form-item>
      <el-form-item label="授权截止（本地时间，留空长期有效）"><el-date-picker v-model="form.expires" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
      <el-button type="primary" :loading="busy" :disabled="!form.user_id || !form.actions.length || (form.kind !== 'COLLEGE' && !form.ids.length)" @click="save">预览并确认授权</el-button>
    </el-form>
    <el-table :data="grants">
      <el-table-column label="账号"><template #default="{ row }">{{ accountName(row.user_id) }}</template></el-table-column>
      <el-table-column label="范围"><template #default="{ row }">{{ row.resource_scope?.kind || 'COLLEGE' }} {{ row.resource_scope?.ids?.join('、') }}</template></el-table-column>
      <el-table-column label="操作"><template #default="{ row }">{{ row.actions.map((code: string) => campusActionLabels[code] || code).join('、') }}</template></el-table-column>
      <el-table-column prop="status" label="状态" />
      <el-table-column label="管理"><template #default="{ row }"><el-button :disabled="busy || row.status !== 'ACTIVE'" @click="revoke(row)">撤销</el-button></template></el-table-column>
    </el-table>
  </section>
</template>
<style scoped>
section { margin-top: 28px; }
.el-select { width: 100%; }
</style>
