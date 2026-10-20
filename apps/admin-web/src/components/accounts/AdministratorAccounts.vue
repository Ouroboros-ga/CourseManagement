<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createAdministrator, listAdministrators, updateAdministrator, resetAdministratorPassword, type AdministratorAccount, type AdministratorCreate } from '../../api/administrators'
import { useSessionStore } from '../../stores/session'
import AdministratorCreateForm from './AdministratorCreateForm.vue'
import AdministratorAccountTable from './AdministratorAccountTable.vue'
const session = useSessionStore()
const router = useRouter()
const rows = ref<AdministratorAccount[]>([])
const page = shallowRef(1)
const total = shallowRef(0)
const busy = shallowRef(false)
const creating = shallowRef(false)
function errorMessage(error: unknown) { return error instanceof Error ? error.message : '操作失败，请刷新后重试' }
async function load() {
  busy.value = true
  try { const data = await listAdministrators(page.value); rows.value = data.items; total.value = data.total }
  catch (error) { ElMessage.error(errorMessage(error)) }
  finally { busy.value = false }
}
async function create(body: AdministratorCreate) {
  busy.value = true
  try { await createAdministrator(body); creating.value = false; await load(); ElMessage.success('管理员已创建') }
  catch (error) { ElMessage.error(errorMessage(error)) }
  finally { busy.value = false }
}
async function finish(row: AdministratorAccount, revokedSelf: boolean) {
  if (row.id === session.currentUser?.id && revokedSelf) {
    try { await session.signOut() } catch { /* 会话已由服务端撤销 */ }
    await router.replace('/login')
    ElMessage.success('已保存，请重新登录')
  } else { await load(); ElMessage.success('已保存') }
}
async function update(row: AdministratorAccount, operation: 'status' | 'platform') {
  if (busy.value) return
  const label = operation === 'status' ? (row.status === 'ACTIVE' ? '停用账号' : '启用账号') : (row.can_manage_administrators ? '取消平台管理员' : '设为平台管理员')
  try { await ElMessageBox.confirm(`确认对 ${row.display_name}（${row.username}）执行「${label}」？`, '管理员维护', { type: 'warning' }) }
  catch { return }
  busy.value = true
  try {
    await updateAdministrator(row.id, { lock_version: row.lock_version, ...(operation === 'status' ? { status: row.status === 'ACTIVE' ? 'DISABLED' as const : 'ACTIVE' as const } : { can_manage_administrators: !row.can_manage_administrators }) })
    await finish(row, operation === 'platform' ? row.can_manage_administrators : row.status === 'ACTIVE')
  } catch (error) { ElMessage.error(errorMessage(error)); await load() }
  finally { busy.value = false }
}
async function reset(row: AdministratorAccount) {
  if (busy.value) return
  let password: string
  try { const result = await ElMessageBox.prompt(`为 ${row.username} 设置新密码`, '重置管理员密码', { inputType: 'password', inputPattern: /^.{6,128}$/, inputErrorMessage: '密码长度须为 6—128 位', closeOnClickModal: false }); password = result.value }
  catch { return }
  busy.value = true
  try { await resetAdministratorPassword(row.id, password, row.lock_version); await finish(row, true) }
  catch (error) { ElMessage.error(errorMessage(error)); await load() }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <section v-loading="busy" class="administrator-panel">
    <div class="toolbar"><div><h3>管理员账号</h3><p>这里列出全部超级管理员账号。标为「平台管理员」的可以维护本列表；标为「管理员」的只有同等的全校业务权限，不能增删其他管理员。系统保护最后一位有效管理员与最后一位平台管理员。</p></div><el-button type="primary" :disabled="busy" @click="creating = true">新增管理员</el-button></div>
    <AdministratorAccountTable :rows="rows" :busy="busy" @update="update" @reset="reset" />
    <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next, total" @current-change="load" />
    <el-dialog v-model="creating" title="新增管理员" width="440px" destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
      <AdministratorCreateForm :busy="busy" @submit="create" @cancel="creating = false" />
    </el-dialog>
  </section>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.toolbar h3 { margin: 0 0 8px; }
.toolbar p { color: var(--ink-mute); font-size: 13px; }
.administrator-panel { padding: 20px; background: var(--paper, #fff); border: 1px solid var(--line); }
</style>
