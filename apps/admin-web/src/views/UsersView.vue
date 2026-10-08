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
  updateUserRoles,
  listOptionalPermissionTargets,
  updateOptionalPermission,
  type TeacherAccountItem,
  type RoleAssignmentTarget,
  type OptionalPermissionTargetItem
} from '../api/accounts'
import AppIcon from '../components/AppIcon.vue'

const sessionStore = useSessionStore()

const activeTab = ref<'teachers' | 'managers'>('teachers')
const loading = ref(false)

// ==================== 1. 教工与管理员账号 ====================
const teachers = ref<TeacherAccountItem[]>([])
const totalTeachers = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')
const selectedStatus = ref('')

const isSuperAdmin = computed(() => {
  return sessionStore.hasAnyRole('SUPER_ADMIN')
})

const roleNameMap: Record<string, string> = {
  SUPER_ADMIN: '系统管理员',
  TEACHER_ADMIN: '教师管理员',
  STUDENT_AFFAIRS_MANAGER: '学生工作负责人',
  COUNSELOR: '专职辅导员',
  VOLUNTEER: '查课志愿者',
  STUDENT: '学生'
}

function getRoleLabel(code: string): string {
  return roleNameMap[code] || code
}

function getRoleTagClass(code: string): string {
  if (code === 'SUPER_ADMIN') return 'tag-red'
  if (code === 'TEACHER_ADMIN') return 'tag-blue'
  if (code === 'STUDENT_AFFAIRS_MANAGER') return 'tag-amber'
  if (code === 'VOLUNTEER') return 'tag-green'
  return 'tag-gray'
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
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取教工列表失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

// 仅展示教工（SUPER_ADMIN / TEACHER_ADMIN）在第一栏
const facultyAccounts = computed(() => {
  return teachers.value.filter(t => {
    const roles = t.roles || []
    return roles.includes('SUPER_ADMIN') || roles.includes('TEACHER_ADMIN') || roles.length === 0
  })
})

// ==================== 2. 学生工作负责人与授权 ====================
const roleTargets = ref<RoleAssignmentTarget[]>([])
const assignableRoles = ref<string[]>([])
const optionalTargets = ref<OptionalPermissionTargetItem[]>([])
const managersLoading = ref(false)

async function fetchManagersAndRoles() {
  managersLoading.value = true
  try {
    const [targetsRes, optRes] = await Promise.all([
      listRoleTargets(),
      listOptionalPermissionTargets().catch(() => ({ items: [], configurable_codes: [] }))
    ])
    roleTargets.value = targetsRes.items || []
    assignableRoles.value = targetsRes.assignable_roles || []
    optionalTargets.value = optRes.items || []
  } catch (err: unknown) {
    console.warn('获取授权目标与可选权限列表失败:', err)
  } finally {
    managersLoading.value = false
  }
}

// 筛选出已经是学生负责人，或者有绑定学号的学生候选列表
const studentAffairsManagers = computed(() => {
  return roleTargets.value.filter(u => u.roles.includes('STUDENT_AFFAIRS_MANAGER'))
})

const eligibleStudentsForManager = computed(() => {
  return roleTargets.value.filter(u => !u.roles.includes('STUDENT_AFFAIRS_MANAGER') && !!u.student_id)
})

// 查找用户的可选权限状态映射
function getOptionalPermState(userId: string, code: string): boolean {
  const target = optionalTargets.value.find(t => t.id === userId)
  if (!target) return false
  const p = target.permissions.find(perm => perm.code === code)
  return p ? p.enabled : false
}

function getOptionalTargetVersion(userId: string): number {
  const target = optionalTargets.value.find(t => t.id === userId)
  return target ? target.lock_version : 0
}

// 切换学生负责人的可选权限（异议初审 / 统计查阅）
async function handleToggleOptionalPermission(manager: RoleAssignmentTarget, code: string, currentVal: boolean) {
  const targetVersion = getOptionalTargetVersion(manager.id)
  const codeName = code === 'objection.initial_review' ? '考勤异议初核' : '数据统计查阅'
  const nextVal = !currentVal
  try {
    await updateOptionalPermission(manager.id, code, {
      enabled: nextVal,
      lock_version: targetVersion,
      reason: `管理员${nextVal ? '开启' : '关闭'}学生工作负责人【${manager.display_name}】的${codeName}权限`
    })
    ElMessage.success(`已${nextVal ? '开启' : '关闭'}【${manager.display_name}】的${codeName}权限！`)
    await fetchManagersAndRoles()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '更新权限失败'
    ElMessage.error(msg)
  }
}

// 委任/撤销“学生工作负责人”角色
async function handleToggleManagerRole(user: RoleAssignmentTarget, makeManager: boolean) {
  const actionText = makeManager ? '委任为学生工作负责人' : '撤销学生工作负责人角色'
  try {
    await ElMessageBox.confirm(
      `确定将【${user.display_name}（${user.username || '学号/绑定账号'}）】${actionText}吗？`,
      '角色调整确认',
      {
        confirmButtonText: `确认${actionText}`,
        cancelButtonText: '取消',
        type: makeManager ? 'info' : 'warning'
      }
    )

    const nextRoles = makeManager
      ? Array.from(new Set([...user.roles, 'STUDENT_AFFAIRS_MANAGER']))
      : user.roles.filter(r => r !== 'STUDENT_AFFAIRS_MANAGER')

    await updateUserRoles(user.id, {
      roles: nextRoles,
      lock_version: user.lock_version,
      reason: `管理员${actionText}`
    })

    ElMessage.success(`操作成功：已${actionText}！`)
    await fetchManagersAndRoles()
    await fetchTeachers()
  } catch {}
}

// ==================== 统计指标 ====================
const stats = computed(() => {
  const teachersCount = facultyAccounts.value.length
  const managersCount = studentAffairsManagers.value.length
  const initialReviewCount = studentAffairsManagers.value.filter(m => getOptionalPermState(m.id, 'objection.initial_review')).length
  const statsReadCount = studentAffairsManagers.value.filter(m => getOptionalPermState(m.id, 'statistics.read')).length
  return {
    teachersCount,
    managersCount,
    initialReviewCount,
    statsReadCount
  }
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
  const uname = createForm.value.username.trim()
  const dname = createForm.value.display_name.trim()
  const pwd = (createForm.value.initial_password || '').trim() || 'Teacher@123456'

  if (!uname) {
    ElMessage.warning('请填写教工工号/登录账号')
    return
  }
  if (!dname) {
    ElMessage.warning('请填写教工真实姓名')
    return
  }
  if (pwd.length < 6) {
    ElMessage.warning('初始密码长度至少需要 6 位字符（推荐默认 Teacher@123456）')
    return
  }
  createSubmitting.value = true
  try {
    await createTeacherAccount({
      username: uname,
      display_name: dname,
      initial_password: pwd
    })
    ElMessage.success(`成功创建教工账号【${dname}】！初始密码已设置。`)
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
      await resetTeacherPassword(teacher.id, {
        new_password: newPwd.trim(),
        lock_version: teacher.lock_version
      })
      ElMessage.success(`教工【${teacher.display_name}】密码重置成功！已生效。`)
      await fetchTeachers()
    }
  } catch (err: unknown) {
    if (err && typeof err === 'object' && 'message' in err) {
      ElMessage.error(String(err.message))
    }
  }
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

// ==================== 全体人员：修改本人密码 ====================
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

// 委任学生工作负责人弹窗
const showAppointDialog = ref(false)
const selectedStudentToAppoint = ref<RoleAssignmentTarget | null>(null)

function openAppointDialog() {
  selectedStudentToAppoint.value = null
  showAppointDialog.value = true
}

async function confirmAppoint() {
  if (!selectedStudentToAppoint.value) {
    ElMessage.warning('请选择要委任的学生')
    return
  }
  await handleToggleManagerRole(selectedStudentToAppoint.value, true)
  showAppointDialog.value = false
}

onMounted(async () => {
  await fetchTeachers()
  await fetchManagersAndRoles()
})
</script>

<template>
  <div v-loading="loading">
    <!-- 纸面秩序标准页面头 -->
    <header class="page-head">
      <div class="crumb font-mono">
        <span>ACCOUNT & PERMISSION</span>
        <em>●</em>
        <span>人员与权限管理</span>
        <em>●</em>
        <span>教师管理员与学生负责人全景维护</span>
      </div>
      <div class="head-row">
        <div>
          <h1 class="font-serif">人员与权限管理</h1>
          <p class="sub">
            统一维护学院教师管理员、超级管理员以及学生工作负责人（学生负责人）。支持教师角色运维与学生负责人权限精细化赋权。
          </p>
        </div>

        <div class="head-actions">
          <button class="btn btn-ghost" @click="openChangePwdDialog">
            <AppIcon name="edit" :size="14" />
            <span>修改我的密码</span>
          </button>
          <button
            v-if="isSuperAdmin && activeTab === 'teachers'"
            class="btn btn-dark"
            @click="openCreateDialog"
          >
            <AppIcon name="plus" :size="14" />
            <span>+ 新增教师账号</span>
          </button>
          <button
            v-if="activeTab === 'managers'"
            class="btn btn-dark"
            @click="openAppointDialog"
          >
            <AppIcon name="plus" :size="14" />
            <span>+ 委任学生工作负责人</span>
          </button>
        </div>
      </div>
    </header>

    <!-- 核心统计指标分栏 (纸面秩序标准 stat-row) -->
    <div class="stat-row font-mono mb-6">
      <div class="stat-cell">
        <div class="label">教工与管理员</div>
        <div class="value">{{ stats.teachersCount }} <span class="text-xs font-normal text-[var(--ink-mute)]">位</span></div>
        <div class="note">在册专任教师及系统管理账号</div>
      </div>
      <div class="stat-cell">
        <div class="label">学生工作负责人</div>
        <div class="value" style="color: var(--amber)">{{ stats.managersCount }} <span class="text-xs font-normal text-[var(--ink-mute)]">人</span></div>
        <div class="note">协助开展查课、排班与考勤协同</div>
      </div>
      <div class="stat-cell">
        <div class="label">考勤异议初核权</div>
        <div class="value" style="color: var(--blue)">{{ stats.initialReviewCount }} <span class="text-xs font-normal text-[var(--ink-mute)]">人</span></div>
        <div class="note">已赋权初审学生异议申请</div>
      </div>
      <div class="stat-cell">
        <div class="label">数据统计查阅权</div>
        <div class="value" style="color: var(--green)">{{ stats.statsReadCount }} <span class="text-xs font-normal text-[var(--ink-mute)]">人</span></div>
        <div class="note">已开通学院全景统计看板</div>
      </div>
    </div>

    <!-- 顶部 Tab 切换 -->
    <div class="tab-nav mb-6">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'teachers' }"
        @click="activeTab = 'teachers'"
      >
        <AppIcon name="users" :size="14" />
        <span>教工与系统管理员 ({{ stats.teachersCount }})</span>
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'managers' }"
        @click="activeTab = 'managers'"
      >
        <AppIcon name="shield" :size="14" />
        <span>学生工作负责人与授权 ({{ stats.managersCount }})</span>
      </button>
    </div>

    <!-- ==================== Tab 1: 教工与系统管理员 ==================== -->
    <div v-if="activeTab === 'teachers'" class="space-y-4">
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div>
            <h3>全校教工及系统管理员名册</h3>
            <div class="meta">
              教师管理员可查看在册人员及角色；超级管理员可直接新增教工、管理启停状态与重置登录凭证。
            </div>
          </div>
          <div class="tbl-tools">
            <input
              v-model="searchQuery"
              class="input w-48"
              placeholder="搜索工号或姓名…"
              @keyup.enter="fetchTeachers"
            />
            <select v-model="selectedStatus" class="input" @change="fetchTeachers">
              <option value="">全部状态</option>
              <option value="ACTIVE">正常 (ACTIVE)</option>
              <option value="DISABLED">已停用 (DISABLED)</option>
            </select>
            <button class="btn btn-sm btn-ghost" @click="fetchTeachers">⟳ 刷新</button>
          </div>
        </div>

        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 140px;">教工工号</th>
              <th style="width: 160px;">姓名</th>
              <th>系统角色</th>
              <th style="width: 120px;">账号状态</th>
              <th style="width: 200px; text-align: right;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="teacher in facultyAccounts" :key="teacher.id">
              <td class="cell-mono font-bold">{{ teacher.username }}</td>
              <td class="cell-main">{{ teacher.display_name }}</td>
              <td>
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span
                    v-for="role in (teacher.roles || ['TEACHER_ADMIN'])"
                    :key="role"
                    class="tag"
                    :class="getRoleTagClass(role)"
                  >
                    {{ getRoleLabel(role) }}
                  </span>
                </div>
              </td>
              <td>
                <span class="tag" :class="teacher.status === 'ACTIVE' ? 'tag-green' : 'tag-gray'">
                  {{ teacher.status === 'ACTIVE' ? '正常运行' : '已停用' }}
                </span>
              </td>
              <td style="text-align: right;">
                <div class="flex items-center justify-end gap-3">
                  <template v-if="isSuperAdmin">
                    <button class="btn-text text-xs text-blue-700 hover:underline" @click="handleResetPassword(teacher)">
                      重置密码
                    </button>
                    <button
                      class="btn-text text-xs hover:underline"
                      :class="teacher.status === 'ACTIVE' ? 'text-amber-700' : 'text-green-700'"
                      @click="handleToggleStatus(teacher)"
                    >
                      {{ teacher.status === 'ACTIVE' ? '停用账号' : '启用账号' }}
                    </button>
                  </template>
                  <span v-else class="text-xs text-[var(--ink-mute)]">由超管统一维护</span>
                </div>
              </td>
            </tr>
            <tr v-if="facultyAccounts.length === 0">
              <td colspan="5" class="text-center py-8 text-xs text-[var(--ink-mute)]">
                暂未找到符合条件的教工账号
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ==================== Tab 2: 学生工作负责人与授权 ==================== -->
    <div v-if="activeTab === 'managers'" class="space-y-4">
      <!-- 业务机制横幅 -->
      <div class="banner">
        <div>
          <div class="b-title">学生工作负责人（STUDENT_AFFAIRS_MANAGER）职责与授权机制</div>
          <div class="b-desc">
            学生工作负责人由教师管理员或系统管理员在已完成微信认证的学生中委任，协助开展学院日常查课与核验工作。
            除基础排班与课表协同权外，【考勤异议初核】与【数据统计查阅】两项高阶权限由教师按需逐人开启。
          </div>
        </div>
        <button class="btn btn-sm btn-dark shrink-0" @click="openAppointDialog">
          + 委任学生工作负责人
        </button>
      </div>

      <!-- 学生负责人列表表格 -->
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div>
            <h3>当前在册学生工作负责人名录 ({{ studentAffairsManagers.length }} 人)</h3>
            <div class="meta">
              点击对应权限状态即可为该学生负责人直接开关【考勤异议初核】或【数据统计查阅】。
            </div>
          </div>
          <div class="tbl-tools">
            <button class="btn btn-sm btn-ghost" @click="fetchManagersAndRoles">⟳ 刷新授权状态</button>
          </div>
        </div>

        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 140px;">学生学号/用户名</th>
              <th style="width: 140px;">姓名</th>
              <th style="width: 130px;">微信绑定状态</th>
              <th>当前持有角色</th>
              <th style="width: 180px;">考勤异议初核权</th>
              <th style="width: 180px;">数据统计查阅权</th>
              <th style="width: 150px; text-align: right;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="manager in studentAffairsManagers" :key="manager.id">
              <td class="cell-mono font-bold">{{ manager.username || '—' }}</td>
              <td class="cell-main">{{ manager.display_name }}</td>
              <td>
                <span class="tag" :class="manager.has_wechat ? 'tag-green' : 'tag-gray'">
                  {{ manager.has_wechat ? '已绑定微信' : '未绑定' }}
                </span>
              </td>
              <td>
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span
                    v-for="role in manager.roles"
                    :key="role"
                    class="tag"
                    :class="getRoleTagClass(role)"
                  >
                    {{ getRoleLabel(role) }}
                  </span>
                </div>
              </td>
              <td>
                <div class="flex items-center gap-2">
                  <span
                    class="tag cursor-pointer"
                    :class="getOptionalPermState(manager.id, 'objection.initial_review') ? 'tag-blue' : 'tag-gray'"
                    title="点击切换初核权限"
                    @click="handleToggleOptionalPermission(manager, 'objection.initial_review', getOptionalPermState(manager.id, 'objection.initial_review'))"
                  >
                    {{ getOptionalPermState(manager.id, 'objection.initial_review') ? '已开通初核' : '未开启' }}
                  </span>
                  <button
                    class="btn-text text-xs text-blue-700 hover:underline"
                    @click="handleToggleOptionalPermission(manager, 'objection.initial_review', getOptionalPermState(manager.id, 'objection.initial_review'))"
                  >
                    {{ getOptionalPermState(manager.id, 'objection.initial_review') ? '关闭' : '开启' }}
                  </button>
                </div>
              </td>
              <td>
                <div class="flex items-center gap-2">
                  <span
                    class="tag cursor-pointer"
                    :class="getOptionalPermState(manager.id, 'statistics.read') ? 'tag-green' : 'tag-gray'"
                    title="点击切换统计看板查阅权限"
                    @click="handleToggleOptionalPermission(manager, 'statistics.read', getOptionalPermState(manager.id, 'statistics.read'))"
                  >
                    {{ getOptionalPermState(manager.id, 'statistics.read') ? '已开通看板' : '未开启' }}
                  </span>
                  <button
                    class="btn-text text-xs text-blue-700 hover:underline"
                    @click="handleToggleOptionalPermission(manager, 'statistics.read', getOptionalPermState(manager.id, 'statistics.read'))"
                  >
                    {{ getOptionalPermState(manager.id, 'statistics.read') ? '关闭' : '开启' }}
                  </button>
                </div>
              </td>
              <td style="text-align: right;">
                <button
                  class="btn-text text-xs text-amber-800 hover:underline"
                  @click="handleToggleManagerRole(manager, false)"
                >
                  撤销负责人角色
                </button>
              </td>
            </tr>
            <tr v-if="studentAffairsManagers.length === 0">
              <td colspan="7" class="text-center py-8 text-xs text-[var(--ink-mute)]">
                当前暂无学生工作负责人，可点击上方“+ 委任学生工作负责人”在已绑定学生中快速添加。
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 弹窗 1: 超管专属新增教师 -->
    <el-dialog v-model="createDialogVisible" title="新增教师管理员账号" width="480px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">教工工号 (作为登录账号) *</label>
          <input
            v-model="createForm.username"
            class="input w-full font-mono"
            placeholder="例如: T2026001 或 100234"
          />
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">真实姓名 *</label>
          <input
            v-model="createForm.display_name"
            class="input w-full"
            placeholder="例如: 张老师"
          />
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">初始登录密码</label>
          <input
            v-model="createForm.initial_password"
            type="text"
            class="input w-full font-mono"
            placeholder="默认 Teacher@123456"
          />
          <p class="text-[11px] text-[var(--ink-mute)] mt-1">初始密码将提供给教师首次登录，登录后教师可自行修改。</p>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="createDialogVisible = false">取消</button>
          <button class="btn btn-dark" :disabled="createSubmitting" @click="handleCreateTeacher">
            {{ createSubmitting ? '正在创建…' : '确认创建教师账号' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2: 全员修改本人密码 -->
    <el-dialog v-model="changePwdDialogVisible" title="修改我的登录密码" width="440px">
      <div class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">当前旧密码 *</label>
          <input
            v-model="changePwdForm.old_password"
            type="password"
            class="input w-full font-mono"
            placeholder="请输入当前旧密码"
          />
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">设定新密码 *</label>
          <input
            v-model="changePwdForm.new_password"
            type="password"
            class="input w-full font-mono"
            placeholder="至少 6 位密码"
          />
        </div>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">确认新密码 *</label>
          <input
            v-model="changePwdForm.confirm_password"
            type="password"
            class="input w-full font-mono"
            placeholder="请再次输入新密码"
          />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="changePwdDialogVisible = false">取消</button>
          <button class="btn btn-dark" :disabled="changePwdSubmitting" @click="handleChangeMyPassword">
            {{ changePwdSubmitting ? '正在修改…' : '确认修改密码' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 3: 委任学生工作负责人 -->
    <el-dialog v-model="showAppointDialog" title="委任学生工作负责人" width="520px">
      <div class="space-y-4">
        <p class="text-xs text-[var(--ink-soft)] leading-relaxed">
          从已在系统内绑定学生身份的用户中，选择并委任为<b>学生工作负责人（STUDENT_AFFAIRS_MANAGER）</b>：
        </p>
        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">选择候选学生账号 *</label>
          <select v-model="selectedStudentToAppoint" class="input w-full">
            <option :value="null" disabled>请选择候选学生…</option>
            <option v-for="stu in eligibleStudentsForManager" :key="stu.id" :value="stu">
              {{ stu.display_name }} (学号: {{ stu.username || '未登记' }}) — {{ stu.has_wechat ? '已绑定微信' : '未绑定' }}
            </option>
          </select>
          <p class="text-[11px] text-[var(--ink-mute)] mt-1.5">
            * 仅列出已完成学生绑定的账号。委任后该学生将拥有管理端访问权限与学院业务协助权限。
          </p>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost" @click="showAppointDialog = false">取消</button>
          <button class="btn btn-dark" :disabled="!selectedStudentToAppoint" @click="confirmAppoint">
            确认委任
          </button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}
.tab-nav {
  display: flex;
  gap: 8px;
  border-bottom: 2px solid var(--line);
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-mute);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.tab-btn:hover { color: var(--ink); }
.tab-btn.active { color: var(--ink); border-bottom-color: var(--ink); }

.btn-text {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-weight: 500;
}
</style>
