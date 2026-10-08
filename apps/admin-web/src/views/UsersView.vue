<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listTeacherAccounts,
  createTeacherAccount,
  updateTeacherAccount,
  resetTeacherPassword,
  changeMyPassword,
  listRoleTargets,
  type TeacherAccountItem,
  type RoleAssignmentTarget
} from '../api/accounts'
import AppIcon from '../components/AppIcon.vue'

const sessionStore = useSessionStore()

const loading = ref(false)
const teachers = ref<TeacherAccountItem[]>([])
const totalTeachers = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')
const selectedStatus = ref('')

const isSuperAdmin = computed(() => {
  return sessionStore.hasAnyRole('SUPER_ADMIN')
})

const roleTargetsMap = ref<Record<string, RoleAssignmentTarget>>({})

const roleNameMap: Record<string, string> = {
  SUPER_ADMIN: '系统管理员',
  TEACHER_ADMIN: '教师管理员',
  COLLEGE_ADMIN: '学院管理员',
  COUNSELOR: '专职辅导员',
  STUDENT_AFFAIRS_MANAGER: '学生工作负责人',
  VOLUNTEER: '查课志愿者',
  STUDENT: '学生'
}

async function fetchTeachers() {
  loading.value = true
  try {
    const res = await listTeacherAccounts({
      page: currentPage.value,
      page_size: pageSize.value,
      query: searchQuery.value || undefined,
      status: selectedStatus.value || undefined
    })
    teachers.value = res.items || []
    totalTeachers.value = res.total || 0

    // 加载角色映射
    try {
      const targetsRes = await listRoleTargets()
      const map: Record<string, RoleAssignmentTarget> = {}
      for (const t of targetsRes.items || []) {
        map[t.user_id] = t
      }
      roleTargetsMap.value = map
    } catch (e) {
      console.warn('获取角色目标列表失败:', e)
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取教工列表失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchTeachers()
})

// ==================== 超管专属：新增教师 ====================
const createDialogVisible = ref(false)
const createSubmitting = ref(false)
const createForm = ref({
  username: '',
  display_name: '',
  initial_password: 'Teacher@123456'
})

function openCreateDialog() {
  createForm.value = {
    username: '',
    display_name: '',
    initial_password: 'Teacher@123456'
  }
  createDialogVisible.value = true
}

async function handleCreateTeacher() {
  if (!createForm.value.username.trim() || !createForm.value.display_name.trim()) {
    ElMessage.warning('请填写教工工号和真实姓名')
    return
  }
  createSubmitting.value = true
  try {
    await createTeacherAccount({
      username: createForm.value.username.trim(),
      display_name: createForm.value.display_name.trim(),
      initial_password: createForm.value.initial_password || 'Teacher@123456'
    })
    ElMessage.success(`成功创建教工账号【${createForm.value.display_name}】！初始密码已设置。`)
    createDialogVisible.value = false
    await fetchTeachers()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '创建教工账号失败'
    ElMessage.error(msg)
  } finally {
    createSubmitting.value = false
  }
}

// ==================== 超管专属：重置密码 ====================
async function handleResetPassword(teacher: TeacherAccountItem) {
  try {
    const { value: newPwd } = await ElMessageBox.prompt(
      `确定为教工【${teacher.display_name}（工号：${teacher.username}）】重置登录密码？请输入新密码：`,
      '重置教工密码',
      {
        confirmButtonText: '确定重置',
        cancelButtonText: '取消',
        inputValue: 'Teacher@123456',
        inputPattern: /\S{6,}/,
        inputErrorMessage: '密码长度至少6位'
      }
    )
    if (newPwd) {
      await resetTeacherPassword(teacher.id, { new_password: newPwd })
      ElMessage.success(`教工【${teacher.display_name}】密码重置成功！已生效。`)
    }
  } catch {}
}

// ==================== 超管专属：切换账号状态 ====================
async function handleToggleStatus(teacher: TeacherAccountItem) {
  const nextStatus = teacher.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE'
  const actionText = nextStatus === 'ACTIVE' ? '启用' : '停用'
  try {
    await ElMessageBox.confirm(
      `确定${actionText}教工账号【${teacher.display_name}（工号：${teacher.username}）】吗？${nextStatus === 'DISABLED' ? '停用后该教工将无法登录管理端。' : ''}`,
      `${actionText}教工账号确认`,
      {
        confirmButtonText: `确认${actionText}`,
        cancelButtonText: '取消',
        type: nextStatus === 'ACTIVE' ? 'info' : 'warning'
      }
    )
    await updateTeacherAccount(teacher.id, {
      status: nextStatus,
      lock_version: teacher.lock_version
    })
    ElMessage.success(`教工账号已成功${actionText}！`)
    await fetchTeachers()
  } catch {}
}

// ==================== 全体教工：修改本人密码 ====================
const changePwdDialogVisible = ref(false)
const changePwdSubmitting = ref(false)
const changePwdForm = ref({
  old_password: '',
  new_password: '',
  confirm_password: ''
})

function openChangePwdDialog() {
  changePwdForm.value = {
    old_password: '',
    new_password: '',
    confirm_password: ''
  }
  changePwdDialogVisible.value = true
}

async function handleChangeMyPassword() {
  if (!changePwdForm.value.old_password) {
    ElMessage.warning('请输入当前旧密码')
    return
  }
  if (!changePwdForm.value.new_password || changePwdForm.value.new_password.length < 6) {
    ElMessage.warning('新密码长度不能少于 6 位')
    return
  }
  if (changePwdForm.value.new_password !== changePwdForm.value.confirm_password) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }

  changePwdSubmitting.value = true
  try {
    await changeMyPassword({
      old_password: changePwdForm.value.old_password,
      new_password: changePwdForm.value.new_password
    })
    ElMessage.success('密码修改成功！请妥善保管新密码。')
    changePwdDialogVisible.value = false
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '修改密码失败，请核对原密码'
    ElMessage.error(msg)
  } finally {
    changePwdSubmitting.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>ACCOUNT & PERMISSION</span>
        <em>●</em>
        <span>教工账号管理</span>
        <em>●</em>
        <span>在册教工 {{ totalTeachers }} 位</span>
      </div>
      <div class="head-row">
        <div>
          <h1>教工与权限管理</h1>
          <p class="sub">
            学院教师管理员与教工账号全景管理。教师可查看在册教工与所属角色；超级管理员可直接新增教工、管理账号状态及重置登录密码。
          </p>
        </div>

        <div class="head-tools">
          <button class="btn btn-outline" @click="openChangePwdDialog">
            <AppIcon name="edit" :size="14" />
            <span>修改我的密码</span>
          </button>
          <button
            v-if="isSuperAdmin"
            class="btn btn-dark"
            @click="openCreateDialog"
          >
            <AppIcon name="plus" :size="14" />
            <span>新增教师账号</span>
          </button>
          <button class="btn btn-ghost" @click="fetchTeachers">⟳ 刷新</button>
        </div>
      </div>
    </header>

    <!-- 过滤器 -->
    <div class="filter-bar">
      <div class="filter-inputs">
        <input
          v-model="searchQuery"
          type="text"
          class="input search-input"
          placeholder="搜索工号 / 教师真实姓名…"
          @keyup.enter="fetchTeachers"
        />
        <select v-model="selectedStatus" class="input" @change="fetchTeachers">
          <option value="">全部状态</option>
          <option value="ACTIVE">正常活跃</option>
          <option value="DISABLED">已停用</option>
        </select>
        <button class="btn btn-sm btn-ghost" @click="fetchTeachers">筛选</button>
      </div>

      <div class="count-tag font-mono">
        显示 {{ teachers.length }} / 共 {{ totalTeachers }} 位教工
      </div>
    </div>

    <!-- 教工表格 -->
    <div class="panel">
      <table class="tbl">
        <thead>
          <tr>
            <th>教工工号 / 账号</th>
            <th>真实姓名</th>
            <th>系统角色</th>
            <th>账号状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in teachers" :key="t.id">
            <td class="cell-mono font-semibold">
              {{ t.username }}
            </td>
            <td>
              <span class="cell-main">{{ t.display_name }}</span>
              <span v-if="t.username === sessionStore.currentUser?.username" class="tag tag-blue" style="margin-left: 6px">当前登录</span>
            </td>
            <td>
              <div class="roles-wrap">
                <template v-if="roleTargetsMap[t.id]?.roles?.length">
                  <span
                    v-for="r in roleTargetsMap[t.id].roles"
                    :key="r"
                    class="tag"
                    :class="{ 'tag-red': r === 'SUPER_ADMIN', 'tag-blue': r === 'TEACHER_ADMIN' }"
                  >
                    {{ roleNameMap[r] || r }}
                  </span>
                </template>
                <template v-else>
                  <span class="tag tag-blue">教师管理员</span>
                </template>
              </div>
            </td>
            <td>
              <span
                class="tag"
                :class="{ 'tag-green': t.status === 'ACTIVE', 'tag-mute': t.status !== 'ACTIVE' }"
              >
                {{ t.status === 'ACTIVE' ? '正常活跃' : '已停用' }}
              </span>
            </td>
            <td style="text-align: right">
              <template v-if="isSuperAdmin">
                <button
                  class="btn btn-ghost btn-sm"
                  title="重置该教工密码"
                  @click="handleResetPassword(t)"
                >
                  重置密码
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  :class="{ 'text-accent': t.status === 'ACTIVE' }"
                  @click="handleToggleStatus(t)"
                >
                  {{ t.status === 'ACTIVE' ? '停用账号' : '启用账号' }}
                </button>
              </template>
              <template v-else>
                <span class="cell-sub font-mono" style="font-size: 11px">在籍教师</span>
              </template>
            </td>
          </tr>
          <tr v-if="teachers.length === 0">
            <td colspan="5" style="text-align: center; padding: 40px; color: var(--ink-mute);">
              暂无匹配的教师账号记录
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 弹窗：超管新增教师账号 -->
    <el-dialog
      v-model="createDialogVisible"
      title="新增教师管理员账号"
      width="480px"
      destroy-on-close
    >
      <div class="form-body">
        <div class="field">
          <label>教工工号 / 登录用户名 <span class="text-accent">*</span></label>
          <input
            v-model="createForm.username"
            type="text"
            class="input"
            placeholder="例如：10023 或 teacher_zhang"
          />
        </div>
        <div class="field">
          <label>真实姓名 <span class="text-accent">*</span></label>
          <input
            v-model="createForm.display_name"
            type="text"
            class="input"
            placeholder="例如：张建国 老师"
          />
        </div>
        <div class="field">
          <label>初始登录密码</label>
          <input
            v-model="createForm.initial_password"
            type="text"
            class="input font-mono"
            placeholder="默认：Teacher@123456"
          />
          <p class="field-hint cell-sub">
            账号创建后将默认赋予【教师管理员】权限。首次登录后建议立即修改初始密码。
          </p>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="createDialogVisible = false">取消</button>
        <button class="btn btn-dark" :disabled="createSubmitting" @click="handleCreateTeacher">
          {{ createSubmitting ? '正在创建…' : '确认创建账号' }}
        </button>
      </template>
    </el-dialog>

    <!-- 弹窗：修改本人密码 -->
    <el-dialog
      v-model="changePwdDialogVisible"
      title="修改我的登录密码"
      width="440px"
      destroy-on-close
    >
      <div class="form-body">
        <div class="field">
          <label>当前原密码 <span class="text-accent">*</span></label>
          <input
            v-model="changePwdForm.old_password"
            type="password"
            class="input"
            placeholder="请输入当前密码"
          />
        </div>
        <div class="field">
          <label>新密码 <span class="text-accent">*</span></label>
          <input
            v-model="changePwdForm.new_password"
            type="password"
            class="input"
            placeholder="至少 6 位新密码"
          />
        </div>
        <div class="field">
          <label>确认新密码 <span class="text-accent">*</span></label>
          <input
            v-model="changePwdForm.confirm_password"
            type="password"
            class="input"
            placeholder="再次输入新密码"
          />
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="changePwdDialogVisible = false">取消</button>
        <button class="btn btn-dark" :disabled="changePwdSubmitting" @click="handleChangeMyPassword">
          {{ changePwdSubmitting ? '正在修改…' : '确认修改' }}
        </button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}
.head-tools { display: flex; align-items: center; gap: 10px; }
.crumb em { margin: 0 8px; color: var(--ink-mute); }

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.filter-inputs { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.search-input { width: 240px; }
.count-tag { font-size: 11px; color: var(--ink-mute); }

.roles-wrap { display: flex; gap: 6px; flex-wrap: wrap; }

.form-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 0;
}
.field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-soft);
  margin-bottom: 6px;
}
.field-hint { font-size: 11px; margin-top: 4px; }

.text-accent { color: var(--accent); }
.tag-mute { background: #f3f4f6; color: #6b7280; }
.tag-blue { background: #eff6ff; color: #1d4ed8; }
.tag-red { background: #fef2f2; color: #dc2626; font-weight: 600; }
</style>
