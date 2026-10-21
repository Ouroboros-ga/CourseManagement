<script setup lang="ts">
import AppPagination from '../../components/AppPagination.vue'
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { listTeacherAccounts, type TeacherAccountItem } from '../../api/accounts'
import {
  createStaff,
  issueBindingToken,
  linkAccount,
  listStaff,
  revokeBindingToken,
  unlinkAccount,
  updateStaff,
  type IssuedBindingToken,
  type StaffProfile
} from '../../api/staff'
import { formatBeijingTime } from '../../utils/datetime'

const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()

const keyword = ref('')
const appliedKeyword = ref('')
const statusFilter = ref('')
const page = ref(1)
const contextKey = computed(() => JSON.stringify([
  session.currentUser?.id || '', props.collegeId, session.workspace?.authorization_revision || ''
]))
const { data, busy, error, load } = useWorkspaceRead(
  () => JSON.stringify([contextKey.value, appliedKeyword.value, statusFilter.value, page.value]),
  () => !!props.collegeId,
  () => listStaff(props.collegeId, {
    keyword: appliedKeyword.value || undefined,
    status: statusFilter.value || undefined,
    page: page.value,
    page_size: 50
  })
)
function search() {
  keyword.value = keyword.value.trim()
  appliedKeyword.value = keyword.value
  page.value = 1
  void load()
}

// 账号、学院或授权修订变化时，未保存输入与展示过的绑定码一并失效。
watch(contextKey, () => {
  page.value = 1
  createOpen.value = false
  editRow.value = null
  editOpen.value = false
  accountRow.value = null
  accountOpen.value = false
  issuedToken.value = null
})

const createOpen = ref(false)
const createForm = ref({ staffNo: '', name: '', phone: '', status: 'ACTIVE' as 'ACTIVE' | 'INACTIVE', reason: '' })
const createError = ref('')
const createBusy = ref(false)
function startCreate() {
  createForm.value = { staffNo: '', name: '', phone: '', status: 'ACTIVE', reason: '' }
  createError.value = ''
  createOpen.value = true
}
async function saveCreate() {
  const staffNo = createForm.value.staffNo.trim()
  const name = createForm.value.name.trim()
  if (!staffNo || !name) { createError.value = '请填写工号和姓名'; return }
  createBusy.value = true
  createError.value = ''
  try {
    await createStaff(props.collegeId, {
      staff_no: staffNo,
      name,
      phone: createForm.value.phone.trim() || null,
      status: createForm.value.status,
      reason: createForm.value.reason.trim() || null
    })
    createOpen.value = false
    ElMessage.success('已新增教职工档案')
    void load()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '保存失败'
  } finally { createBusy.value = false }
}

const editOpen = ref(false)
const editRow = ref<StaffProfile | null>(null)
const editForm = ref({ name: '', phone: '', status: 'ACTIVE' as 'ACTIVE' | 'INACTIVE', reason: '' })
const editError = ref('')
const editBusy = ref(false)
function startEdit(row: StaffProfile) {
  editRow.value = row
  editForm.value = { name: row.name, phone: row.phone || '', status: row.status, reason: '' }
  editError.value = ''
  editOpen.value = true
}
async function saveEdit() {
  const row = editRow.value
  if (!row) return
  if (!editForm.value.name.trim()) { editError.value = '姓名不能为空'; return }
  editBusy.value = true
  editError.value = ''
  try {
    await updateStaff(props.collegeId, row.id, {
      lock_version: row.lock_version,
      name: editForm.value.name.trim(),
      phone: editForm.value.phone.trim() || null,
      status: editForm.value.status,
      reason: editForm.value.reason.trim() || null
    })
    editOpen.value = false
    ElMessage.success('档案已更新')
    void load()
  } catch (e) {
    editError.value = e instanceof Error ? e.message : '保存失败'
  } finally { editBusy.value = false }
}

const accountOpen = ref(false)
const accountRow = ref<StaffProfile | null>(null)
const accountOptions = ref<TeacherAccountItem[]>([])
const accountLoading = ref(false)
const accountsFailed = ref(false)
const accountUser = ref('')
const manualUserId = ref('')
const accountError = ref('')
const reasonForAccount = ref('')
const accountBusy = ref(false)
async function startAccount(row: StaffProfile) {
  accountRow.value = row
  accountUser.value = ''
  manualUserId.value = ''
  accountError.value = ''
  reasonForAccount.value = ''
  accountsFailed.value = false
  accountOpen.value = true
  accountLoading.value = true
  accountOptions.value = []
  try {
    const page = await listTeacherAccounts({ page_size: 500 })
    accountOptions.value = page.items.filter(item => item.status === 'ACTIVE')
  } catch (e) {
    accountsFailed.value = true
    accountError.value = '账号候选列表不可用：' + (e instanceof Error ? e.message : '加载失败')
  } finally { accountLoading.value = false }
}
async function saveAccountLink() {
  const row = accountRow.value
  if (!row) return
  const picked = accountUser.value || manualUserId.value.trim()
  if (!picked) { accountError.value = '请先明确选择要关联的账号'; return }
  accountBusy.value = true
  accountError.value = ''
  try {
    await linkAccount(props.collegeId, row.id, {
      user_id: picked,
      lock_version: row.lock_version,
      reason: reasonForAccount.value.trim() || null
    })
    accountOpen.value = false
    ElMessage.success('已关联账号')
    void load()
  } catch (e) {
    accountError.value = e instanceof Error ? e.message : '关联失败'
  } finally { accountBusy.value = false }
}
async function doUnlink(row: StaffProfile) {
  try { await ElMessageBox.confirm(`解除「${row.staff_no} ${row.name}」与登录账号的关联？之后本人教工入口立即失效。`, '解除账号关联') } catch { return }
  try {
    await unlinkAccount(props.collegeId, row.id, row.lock_version)
    ElMessage.success('已解除关联')
    void load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '解除失败')
  }
}

const issuedToken = ref<IssuedBindingToken | null>(null)
const tokenBusy = ref(false)
const tokenRow = ref<StaffProfile | null>(null)
async function requestToken(row: StaffProfile) {
  tokenRow.value = row
  issuedToken.value = null
  tokenBusy.value = true
  try {
    issuedToken.value = await issueBindingToken(props.collegeId, row.id)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发行绑定码失败')
  } finally { tokenBusy.value = false }
}
async function copyIssuedCode() {
  const code = issuedToken.value?.plaintext_code
  if (!code) return
  try { await navigator.clipboard.writeText(code); ElMessage.success('已复制，请在安全渠道分发') } catch {
    ElMessage.warning('复制失败，请手动选择并复制绑定码')
  }
}
async function revokeIssued() {
  const token = issuedToken.value
  if (!token) return
  tokenBusy.value = true
  try {
    await revokeBindingToken(props.collegeId, token.token_id, '管理员撤销')
    issuedToken.value = null
    ElMessage.success('绑定码已撤销')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '撤销失败')
  } finally { tokenBusy.value = false }
}

const formatTime = (value?: string | null) => formatBeijingTime(value, 'minute')
const statusText: Record<string, string> = { ACTIVE: '在职', INACTIVE: '停用' }
</script>

<template>
  <section aria-label="教职工档案">
    <el-alert title="教职工档案与账号角色管理分开维护：本页不授予管理权限。工号在学校内唯一；绑定码只在发行结果中展示一次。" type="info" :closable="false" />
    <div class="filters">
      <el-input v-model="keyword" placeholder="工号或姓名" clearable style="max-width: 220px" @keyup.enter="search" />
      <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 120px" @change="search">
        <el-option value="ACTIVE" label="在职" />
        <el-option value="INACTIVE" label="停用" />
      </el-select>
      <el-button :loading="busy" @click="search">查询</el-button>
      <el-button type="primary" @click="startCreate">新增教职工</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="data?.items || []" v-loading="busy" empty-text="本院尚无教职工档案，可通过新增或资料导入建立">
      <el-table-column prop="staff_no" label="工号" min-width="110" />
      <el-table-column prop="name" label="姓名" min-width="110" />
      <el-table-column prop="phone" label="电话" min-width="130"><template #default="{ row }">{{ row.phone || '—' }}</template></el-table-column>
      <el-table-column label="状态" min-width="90"><template #default="{ row }">{{ statusText[row.status] || row.status }}</template></el-table-column>
      <el-table-column label="登录账号" min-width="140">
        <template #default="{ row }">{{ row.user_id ? `已关联（ID ${row.user_id}）` : '未关联' }}</template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="160"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
      <el-table-column label="操作" min-width="220" fixed="right">
        <template #default="{ row }">
          <el-button link @click="startEdit(row)">档案</el-button>
          <el-button link @click="row.user_id ? doUnlink(row) : startAccount(row)">{{ row.user_id ? '解绑账号' : '关联账号' }}</el-button>
          <el-button link :loading="tokenBusy && tokenRow?.id === row.id" @click="requestToken(row)">绑定码</el-button>
        </template>
      </el-table-column>
    </el-table>
    <AppPagination v-model:current-page="page" :page-size="50" :total="data?.total || 0" />

    <el-dialog v-model="createOpen" title="新增教职工档案" width="480px" :close-on-click-modal="false">
      <el-form label-width="92px">
        <el-form-item label="工号" required><el-input v-model="createForm.staffNo" placeholder="如 00023，前导零按原文保留" maxlength="64" /></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="createForm.name" maxlength="128" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="createForm.phone" maxlength="32" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="createForm.status"><el-option value="ACTIVE" label="在职" /><el-option value="INACTIVE" label="停用" /></el-select></el-form-item>
        <el-form-item label="备注"><el-input v-model="createForm.reason" type="textarea" :rows="2" maxlength="512" /></el-form-item>
      </el-form>
      <el-alert v-if="createError" :title="createError" type="error" :closable="false" />
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="createBusy" @click="saveCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editOpen" title="维护教职工档案" width="480px" :close-on-click-modal="false">
      <el-form label-width="92px">
        <el-form-item label="工号"><span>{{ editRow?.staff_no }}</span><span class="muted">（工号创建后不可改）</span></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="editForm.name" maxlength="128" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="editForm.phone" maxlength="32" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="editForm.status"><el-option value="ACTIVE" label="在职" /><el-option value="INACTIVE" label="停用" /></el-select></el-form-item>
        <el-form-item label="备注"><el-input v-model="editForm.reason" type="textarea" :rows="2" maxlength="512" /></el-form-item>
      </el-form>
      <el-alert v-if="editError" :title="editError" type="error" :closable="false" />
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="editBusy" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="accountOpen" title="关联登录账号" width="640px" :close-on-click-modal="false">
      <el-form label-width="92px">
        <el-form-item label="教职工">
          <span>{{ accountRow?.staff_no }} {{ accountRow?.name }}</span>
        </el-form-item>
        <el-form-item v-if="!accountsFailed" label="选择账号">
          <el-select v-model="accountUser" filterable placeholder="选择要关联的账号（不按姓名自动匹配）" style="width: 100%">
            <el-option v-for="item in accountOptions" :key="item.id" :value="item.id" :label="`${item.display_name}（${item.username}）`" :disabled="item.status !== 'ACTIVE'" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="accountsFailed || !!accountUser" label="账号编号">
          <el-input v-model="manualUserId" placeholder="已选择账号或候选不可用时手工输入账号编号" maxlength="19" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="reasonForAccount" type="textarea" :rows="2" maxlength="512" /></el-form-item>
      </el-form>
      <el-alert v-if="accountError" :title="accountError" type="error" :closable="false" />
      <template #footer>
        <el-button @click="accountOpen = false">取消</el-button>
        <el-button type="primary" :loading="accountBusy" @click="saveAccountLink">确认关联</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="!!issuedToken" title="绑定码（仅显示一次）" width="480px" :close-on-click-modal="false" @close="issuedToken = null">
      <template v-if="issuedToken">
        <p>教职工：{{ tokenRow?.staff_no }} {{ tokenRow?.name }}</p>
        <p class="code-line"><strong>{{ issuedToken.plaintext_code }}</strong><el-button size="small" link @click="copyIssuedCode">复制</el-button></p>
        <p class="muted">有效期至 {{ formatTime(issuedToken.expires_at) }}。原码不保存在系统内，关闭此窗口后不再展示；如需更换须撤销后重新发行。</p>
        <el-button size="small" :loading="tokenBusy" @click="revokeIssued">撤销此码</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }
.el-pagination { margin-top: 18px; }
.muted { color: var(--ink-mute); font-size: 12px; margin-left: 8px; }
.code-line { display: flex; align-items: center; gap: 10px; font-size: var(--text-lg); letter-spacing: 1px; }
</style>
