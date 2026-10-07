<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listStudents,
  listVolunteerQualifications,
  upsertVolunteerQualification,
  issueBindingToken,
  listRoleTargets,
  createStudent,
  type StudentItem,
  type VolunteerQualificationItem,
  type BindingTokenResult,
  type RoleTargetUser
} from '../api/academic'
import { listTasks, type InspectionTaskItem } from '../api/tasks'
import { request } from '../api/http'
import { exportBindingTokensExcel } from '../api/auth'
import AppIcon from '../components/AppIcon.vue'

const sessionStore = useSessionStore()

const loading = ref(false)
const students = ref<StudentItem[]>([])
const volunteerQuals = ref<VolunteerQualificationItem[]>([])
const roleTargets = ref<RoleTargetUser[]>([])
const searchQuery = ref('')
const filterOnlyVolunteers = ref(false)

// 绑定码弹窗
const tokenDialogVisible = ref(false)
const currentTokenInfo = ref<{
  studentName: string
  studentNo: string
  tokenResult: BindingTokenResult | null
}>({
  studentName: '',
  studentNo: '',
  tokenResult: null
})

// 分配任务弹窗
const assignDialogVisible = ref(false)
const assignTargetStudent = ref<StudentItem | null>(null)
const assignTargetUser = ref<RoleTargetUser | null>(null)
const unassignedTasks = ref<InspectionTaskItem[]>([])
const assigning = ref(false)

// 添加志愿者/学生弹窗
const addDialogVisible = ref(false)
const addMode = ref<'existing' | 'new'>('existing')
const selectedStudentId = ref<string>('')
const newStudentForm = ref({
  student_no: '',
  name: '',
  set_as_volunteer: true,
  issue_token_now: true
})
const adding = ref(false)

// 批量导出绑定码弹窗状态
const batchExportDialogVisible = ref(false)
const batchExportDays = ref(30)
const batchExportScope = ref<'all' | 'volunteers'>('all')
const batchExporting = ref(false)

async function handleBatchExport() {
  batchExporting.value = true
  try {
    let studentIds: number[] | undefined = undefined
    if (batchExportScope.value === 'volunteers') {
      const volStudentIds = volunteerQuals.value.filter(q => q.enabled).map(q => Number(q.student_id))
      studentIds = volStudentIds
    }
    const blob = await exportBindingTokensExcel({
      days_valid: batchExportDays.value,
      student_ids: studentIds,
      reason: `管理员批量生成${batchExportScope.value === 'volunteers' ? '志愿者' : '在校学生'}绑定码`
    })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `学生6位绑定码_${new Date().toISOString().slice(0, 10)}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success('批量生成 6 位绑定码并导出 Excel 成功！')
    batchExportDialogVisible.value = false
  } catch (err: any) {
    ElMessage.error(err.message || '导出绑定码失败')
  } finally {
    batchExporting.value = false
  }
}

async function loadData() {
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  try {
    // 1. 获取学生列表
    const stuRes = await listStudents({ page_size: 100 })
    students.value = stuRes.items || []

    // 2. 获取当前学期志愿者资质列表
    const volRes = await listVolunteerQualifications(sessionStore.currentSemesterId)
    volunteerQuals.value = volRes.items || []

    // 3. 获取用户账号列表（查看小程序绑定状态及 UID）
    try {
      const userRes = await listRoleTargets()
      roleTargets.value = userRes.items || []
    } catch (e) {
      console.warn('获取用户账号列表失败（可能权限受限）:', e)
    }
  } catch (err: unknown) {
    console.error('加载学生与志愿者列表失败:', err)
  } finally {
    loading.value = false
  }
}

watch(
  () => sessionStore.currentSemesterId,
  () => {
    loadData()
  }
)

onMounted(() => {
  loadData()
})

// 映射学生是否有志愿者资格
const volunteerMap = computed(() => {
  const map = new Map<string, boolean>()
  volunteerQuals.value.forEach(q => {
    if (q.enabled) map.set(q.student_id, true)
  })
  return map
})

// 映射学生绑定的小程序用户账号
const boundUserMap = computed(() => {
  const map = new Map<string, RoleTargetUser>()
  roleTargets.value.forEach(u => {
    if (u.student_id) {
      map.set(String(u.student_id), u)
    }
  })
  return map
})

// 统计数据
const stats = computed(() => {
  const total = students.value.length
  const volunteers = students.value.filter(s => volunteerMap.value.get(s.id)).length
  const boundCount = students.value.filter(s => boundUserMap.value.has(s.id)).length
  return { total, volunteers, boundCount }
})

// 过滤后的学生列表
const filteredStudents = computed(() => {
  return students.value.filter(s => {
    if (filterOnlyVolunteers.value && !volunteerMap.value.get(s.id)) {
      return false
    }
    if (!searchQuery.value.trim()) return true
    const q = searchQuery.value.trim().toLowerCase()
    return s.name.toLowerCase().includes(q) || s.student_no.toLowerCase().includes(q)
  })
})

// 切换志愿者资质
async function handleToggleVolunteer(student: StudentItem, enabled: boolean) {
  try {
    await upsertVolunteerQualification({
      semester_id: Number(sessionStore.currentSemesterId),
      student_id: Number(student.id),
      enabled,
      reason: '管理端手动配置资格'
    })
    ElMessage.success(`${student.name} 已${enabled ? '开通' : '取消'}本学期志愿者资质`)
    // 重新拉取资质
    const volRes = await listVolunteerQualifications(sessionStore.currentSemesterId)
    volunteerQuals.value = volRes.items || []
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '操作失败'
    ElMessage.error(msg)
  }
}

// 签发绑定码
async function handleIssueToken(student: StudentItem) {
  try {
    const res = await issueBindingToken(student.id, `为 ${student.name}(${student.student_no}) 生成一次性绑定码`)
    currentTokenInfo.value = {
      studentName: student.name,
      studentNo: student.student_no,
      tokenResult: res
    }
    tokenDialogVisible.value = true
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '签发绑定码失败'
    ElMessage.error(msg)
  }
}

// 复制绑定信息
function copyBindingInfo() {
  if (!currentTokenInfo.value.tokenResult) return
  const text = `【查课小程序学生绑定】\n姓名：${currentTokenInfo.value.studentName}\n学号：${currentTokenInfo.value.studentNo}\n一次性绑定码：${currentTokenInfo.value.tokenResult.plaintext_code}\n有效截止：${currentTokenInfo.value.tokenResult.expires_at.substring(0, 19).replace('T', ' ')}\n请在微信小程序登录后输入学号与绑定码完成身份认证。`
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制绑定信息到剪贴板，可直接发送给学生！')
  }).catch(() => {
    ElMessage.info('请手动选中文本进行复制')
  })
}

// 打开分配任务弹窗
async function openAssignDialog(student: StudentItem) {
  const boundUser = boundUserMap.value.get(student.id)
  if (!boundUser) {
    ElMessageBox.alert(
      `学生【${student.name}】（学号：${student.student_no}）尚未在微信小程序中完成账号绑定（暂未生成系统账号 UID）。\n\n请先点击【生成绑定码】将绑定码发放给该学生，由其在微信小程序登录后输入学号与绑定码完成绑定。绑定完成后即可直接为其分配课程。`,
      '尚未绑定小程序账号',
      { type: 'warning', confirmButtonText: '我知道了' }
    )
    return
  }

  assignTargetStudent.value = student
  assignTargetUser.value = boundUser
  assignDialogVisible.value = true
  try {
    const taskRes = await listTasks({
      semester_id: sessionStore.currentSemesterId,
      week_no: sessionStore.currentWeekNo,
      page_size: 50
    })
    // 过滤出未取消且未指派的任务
    unassignedTasks.value = (taskRes.items || []).filter(t => !t.assigned_volunteer_id && !(t as any).assignment && t.status !== 'CANCELED' && t.status !== '已取消')
  } catch (err) {
    console.error('获取未分配任务失败:', err)
  }
}

// 确认给学生分配指定任务
async function assignTaskToStudent(task: InspectionTaskItem) {
  if (!assignTargetStudent.value || !assignTargetUser.value) return
  assigning.value = true
  try {
    await request(`/api/v1/inspection-tasks/${task.id}/assignment`, {
      method: 'PUT',
      body: JSON.stringify({
        volunteer_user_id: Number(assignTargetUser.value.id),
        lock_version: task.lock_version || 0
      })
    })
    ElMessage.success(`已成功将任务 #${task.id} (${task.course_name_snapshot || '查课'}) 指派给 ${assignTargetStudent.value.name} (UID: ${assignTargetUser.value.id})！`)
    assignDialogVisible.value = false
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '指派失败'
    ElMessage.error(msg)
  } finally {
    assigning.value = false
  }
}

// 打开添加对话框
function openAddDialog() {
  selectedStudentId.value = ''
  newStudentForm.value = {
    student_no: '',
    name: '',
    set_as_volunteer: true,
    issue_token_now: true
  }
  addDialogVisible.value = true
}

// 确认添加
async function handleAddConfirm() {
  adding.value = true
  try {
    if (addMode.value === 'existing') {
      if (!selectedStudentId.value) {
        ElMessage.warning('请选择要设为志愿者的学生')
        return
      }
      await upsertVolunteerQualification({
        semester_id: Number(sessionStore.currentSemesterId),
        student_id: Number(selectedStudentId.value),
        enabled: true,
        reason: '管理端选拔志愿者'
      })
      ElMessage.success('已成功为选定学生开通本学期志愿者资格！')
      addDialogVisible.value = false
      await loadData()
    } else {
      if (!newStudentForm.value.student_no.trim() || !newStudentForm.value.name.trim()) {
        ElMessage.warning('请填写学号和姓名')
        return
      }
      // 1. 创建学生
      const newStu = await createStudent({
        student_no: newStudentForm.value.student_no.trim(),
        name: newStudentForm.value.name.trim(),
        reason: '管理端手动录入'
      })

      // 2. 如果勾选设为志愿者
      if (newStudentForm.value.set_as_volunteer) {
        await upsertVolunteerQualification({
          semester_id: Number(sessionStore.currentSemesterId),
          student_id: Number(newStu.id),
          enabled: true,
          reason: '新建学生时设为志愿者'
        })
      }

      ElMessage.success(`学生 ${newStu.name} 录入成功！`)
      addDialogVisible.value = false
      await loadData()

      // 3. 如果勾选立即签发绑定码
      if (newStudentForm.value.issue_token_now) {
        await handleIssueToken(newStu)
      }
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '添加失败'
    ElMessage.error(msg)
  } finally {
    adding.value = false
  }
}

// 智能自动排班
async function handleAutoAssign() {
  try {
    await ElMessageBox.confirm(
      `确定对当前【${sessionStore.currentSemesterName}】第 ${sessionStore.currentWeekNo} 周未分配的查课任务执行智能自动排班？\n系统将自动结合已绑定的有效志愿者进行防冲突排班。`,
      '智能自动排班确认',
      { confirmButtonText: '立即执行', cancelButtonText: '取消', type: 'info' }
    )
    loading.value = true
    const res: any = await request('/api/v1/assignments/auto', {
      method: 'POST',
      body: JSON.stringify({
        semester_id: Number(sessionStore.currentSemesterId),
        date_from: sessionStore.weekDateRange.start || undefined,
        date_to: sessionStore.weekDateRange.end || undefined
      })
    })
    ElMessage.success(`自动排班完成！已分配: ${res.assigned_count ?? 0} 个任务，未分配: ${res.unassigned_count ?? 0} 个`)
  } catch (err: any) {
    if (err !== 'cancel') {
      const msg = err?.message || '自动排班失败'
      ElMessage.error(msg)
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>PREPARATION</span>
        <em>●</em>
        <span>{{ sessionStore.currentSemesterName }}</span>
        <em>●</em>
        <span>第 {{ sessionStore.currentWeekNo }} 周</span>
      </div>
      <div class="title-row">
        <div>
          <h1>志愿者与学生绑定管理</h1>
          <p class="sub">
            业务闭环起点：维护在校学生档案、认定查课志愿者资质、生成小程序一次性绑定码；并支持将课次直接或智能指派给志愿者。
          </p>
        </div>
        <div class="head-actions flex items-center gap-2">
          <button class="btn btn-ghost inline-flex items-center gap-1.5" @click="handleAutoAssign">
            <AppIcon name="sparkles" :size="14" class="text-amber-600" />
            <span>智能自动排班</span>
          </button>
          <button class="btn btn-primary inline-flex items-center gap-1.5" @click="batchExportDialogVisible = true">
            <AppIcon name="download" :size="14" />
            <span>批量生成绑定码并导出 Excel</span>
          </button>
          <button class="btn btn-dark inline-flex items-center gap-1.5" @click="openAddDialog">
            <AppIcon name="plus" :size="14" />
            <span>添加志愿者 / 学生</span>
          </button>
        </div>
      </div>
    </header>

    <!-- 关键指标条 -->
    <div class="stats-row font-mono">
      <div class="stat-cell">
        <div class="label">学生档案库</div>
        <div class="value">{{ stats.total }} <span class="unit">人</span></div>
        <div class="note">全校导入与登记总数</div>
      </div>
      <div class="stat-cell">
        <div class="label">当前学期志愿者</div>
        <div class="value" style="color: var(--blue)">{{ stats.volunteers }} <span class="unit">人</span></div>
        <div class="note">已具备查课排班资格</div>
      </div>
      <div class="stat-cell">
        <div class="label">小程序已绑定账号</div>
        <div class="value" style="color: var(--green)">{{ stats.boundCount }} <span class="unit">人</span></div>
        <div class="note">已生成独立系统 UID</div>
      </div>
    </div>

    <!-- 流程全景指引卡片 -->
    <div class="guide-banner">
      <div class="g-title flex items-center gap-1.5">
        <AppIcon name="info" :size="15" class="text-blue-600" />
        <span>教务查课端到端全流程闭环指引</span>
      </div>
      <div class="g-steps font-mono">
        <div class="g-step current">
          <span class="num">00</span>
          <span class="name">人员与绑定码</span>
          <span class="desc">开通资质并给志愿者发放绑定码</span>
        </div>
        <div class="g-arrow">→</div>
        <router-link to="/dashboard/schedule" class="g-step g-link">
          <span class="num">01</span>
          <span class="name">课次勾选下发</span>
          <span class="desc">勾选课表原子生成查课任务</span>
        </router-link>
        <div class="g-arrow">→</div>
        <router-link to="/dashboard/tasks" class="g-step g-link">
          <span class="num">02</span>
          <span class="name">查课任务排班</span>
          <span class="desc">查看分配状态与改派指派</span>
        </router-link>
        <div class="g-arrow">→</div>
        <div class="g-step">
          <span class="num">03</span>
          <span class="name">小程序查课</span>
          <span class="desc">志愿者现场清点拍照提交</span>
        </div>
        <div class="g-arrow">→</div>
        <router-link to="/dashboard/reviews" class="g-step g-link">
          <span class="num">04</span>
          <span class="name">管理审核</span>
          <span class="desc">教师审核留痕并发布报告</span>
        </router-link>
      </div>
    </div>

    <!-- 主表格区域 -->
    <div class="tbl-wrap">
      <div class="tbl-head">
        <div>
          <h3>学生与志愿者名册（共 {{ filteredStudents.length }} 条）</h3>
          <div class="meta">在校学生档案与 {{ sessionStore.currentSemesterName }} 志愿者资质关联表</div>
        </div>
        <div class="tbl-tools">
          <label class="filter-chk font-mono">
            <input type="checkbox" v-model="filterOnlyVolunteers" />
            <span>仅显示志愿者 ({{ stats.volunteers }})</span>
          </label>
          <input
            v-model="searchQuery"
            type="text"
            class="input"
            style="width: 220px"
            placeholder="搜索姓名 / 学号…"
          />
          <button class="btn btn-sm btn-ghost" @click="loadData">⟳ 刷新</button>
        </div>
      </div>

      <table class="tbl">
        <thead>
          <tr>
            <th>学号</th>
            <th>姓名</th>
            <th>行政班级</th>
            <th>小程序绑定状态</th>
            <th>志愿者资质（本学期）</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="stu in filteredStudents" :key="stu.id">
            <td class="cell-mono font-bold">{{ stu.student_no }}</td>
            <td class="cell-main font-bold">{{ stu.name }}</td>
            <td class="cell-sub">
              {{ stu.administrative_class_id ? `行政班 #${stu.administrative_class_id}` : '未指定班级' }}
            </td>
            <td>
              <span v-if="boundUserMap.has(stu.id)" class="tag tag-green inline-flex items-center gap-1">
                <AppIcon name="check-circle" :size="12" class="text-emerald-600" />
                <span>已绑定 (UID: {{ boundUserMap.get(stu.id)?.id }})</span>
              </span>
              <span v-else class="tag tag-gray inline-flex items-center gap-1">
                <AppIcon name="close" :size="10" class="text-slate-400" />
                <span>未绑定小程序</span>
              </span>
            </td>
            <td>
              <div class="vol-switch-wrap">
                <el-switch
                  :model-value="volunteerMap.get(stu.id) || false"
                  active-text="志愿者"
                  inactive-text="普通学生"
                  @change="(val: boolean) => handleToggleVolunteer(stu, val)"
                />
              </div>
            </td>
            <td style="text-align: right">
              <div class="action-btns flex items-center justify-end gap-1.5">
                <button class="btn btn-sm inline-flex items-center gap-1" @click="handleIssueToken(stu)">
                  <AppIcon name="key" :size="12" />
                  <span>生成绑定码</span>
                </button>
                <button
                  v-if="volunteerMap.get(stu.id)"
                  class="btn btn-dark btn-sm inline-flex items-center gap-1"
                  @click="openAssignDialog(stu)"
                >
                  <AppIcon name="calendar" :size="12" />
                  <span>分配课程</span>
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="filteredStudents.length === 0">
            <td colspan="6" class="empty-tip">未找到匹配的学生记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 弹窗 1：一次性绑定码发放 -->
    <el-dialog
      v-model="tokenDialogVisible"
      title="一次性小程序绑定码已签发"
      width="540px"
      destroy-on-close
    >
      <div class="token-dialog-body">
        <p class="dialog-tip">
          该绑定码具有单次使用时效（默认 7 天）。请将其发送给学生本人，学生在微信小程序登录后输入学号与此绑定码即可完成认证绑定。
        </p>

        <div class="token-card">
          <div class="token-meta">
            <div><span class="label">学生姓名：</span><strong>{{ currentTokenInfo.studentName }}</strong></div>
            <div><span class="label">绑定学号：</span><strong class="font-mono">{{ currentTokenInfo.studentNo }}</strong></div>
          </div>

          <div class="token-box font-mono">
            {{ currentTokenInfo.tokenResult?.plaintext_code }}
          </div>

          <div class="token-expire">
            有效截止时间：<span class="font-mono">{{ currentTokenInfo.tokenResult?.expires_at?.substring(0, 19).replace('T', ' ') }}</span>（超时自动失效）
          </div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <button class="btn" @click="tokenDialogVisible = false">关闭</button>
          <button class="btn btn-dark inline-flex items-center gap-1.5" @click="copyBindingInfo">
            <AppIcon name="copy" :size="14" />
            <span>一键复制绑定信息</span>
          </button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 2：分配课程任务 -->
    <el-dialog
      v-model="assignDialogVisible"
      :title="'为志愿者【' + (assignTargetStudent?.name || '') + '】指派查课任务'"
      width="640px"
      destroy-on-close
    >
      <div v-loading="assigning" class="assign-dialog-body">
        <p class="dialog-tip">
          志愿者已绑定系统账号（UID: {{ assignTargetUser?.id }}）。从本周（第 {{ sessionStore.currentWeekNo }} 周）未分配的查课任务中选择一项直接指派：
        </p>

        <div v-if="unassignedTasks.length > 0" class="task-select-list">
          <div
            v-for="t in unassignedTasks"
            :key="t.id"
            class="task-assign-card"
          >
            <div>
              <div class="t-name font-bold">{{ t.course_name_snapshot || '课程' }} · {{ t.class_name_snapshot || '教学班' }}</div>
              <div class="t-sub font-mono">
                {{ t.inspection_date }} 第 {{ t.start_period }}-{{ t.end_period }} 节 · {{ t.classroom_snapshot || '教室' }}
              </div>
            </div>
            <button class="btn btn-sm btn-dark" @click="assignTaskToStudent(t)">指派此课 →</button>
          </div>
        </div>

        <div v-else class="empty-tip">
          本周暂无可分配的未指派任务。可前往「01 课次勾选与下发」生成新任务。
        </div>
      </div>

      <template #footer>
        <button class="btn" @click="assignDialogVisible = false">关闭</button>
      </template>
    </el-dialog>

    <!-- 弹窗 3：添加志愿者 / 录入学生 -->
    <el-dialog
      v-model="addDialogVisible"
      title="添加志愿者 / 录入学生档案"
      width="520px"
      destroy-on-close
    >
      <div v-loading="adding" class="add-dialog-body">
        <div class="tab-switch">
          <button
            class="tab-btn"
            :class="{ active: addMode === 'existing' }"
            @click="addMode = 'existing'"
          >
            从在籍学生中指定志愿者
          </button>
          <button
            class="tab-btn"
            :class="{ active: addMode === 'new' }"
            @click="addMode = 'new'"
          >
            新建学生档案
          </button>
        </div>

        <!-- 模式 A：从已有学生中选拔 -->
        <div v-if="addMode === 'existing'" class="form-section">
          <p class="dialog-tip">从当前在籍学生档案中选择一名学生，直接开通本学期的查课志愿者资质。</p>
          <div class="form-item">
            <label class="form-label">选择学生：</label>
            <el-select
              v-model="selectedStudentId"
              filterable
              placeholder="请输入姓名或学号搜索…"
              style="width: 100%"
            >
              <el-option
                v-for="s in students"
                :key="s.id"
                :label="`${s.name} (${s.student_no})`"
                :value="s.id"
              />
            </el-select>
          </div>
        </div>

        <!-- 模式 B：录入新学生 -->
        <div v-else class="form-section">
          <p class="dialog-tip">录入新学生档案，可一并设定为查课志愿者并立即签发一次性绑定码。</p>
          <div class="form-item">
            <label class="form-label">学号 *：</label>
            <input
              v-model="newStudentForm.student_no"
              type="text"
              class="input"
              placeholder="例如：S20260012"
            />
          </div>
          <div class="form-item">
            <label class="form-label">姓名 *：</label>
            <input
              v-model="newStudentForm.name"
              type="text"
              class="input"
              placeholder="例如：张三"
            />
          </div>
          <div class="form-options">
            <label class="chk-label">
              <input type="checkbox" v-model="newStudentForm.set_as_volunteer" />
              <span>同时开通本学期（{{ sessionStore.currentSemesterName }}）志愿者资质</span>
            </label>
            <label class="chk-label">
              <input type="checkbox" v-model="newStudentForm.issue_token_now" />
              <span>录入完成后立即弹出生成绑定码</span>
            </label>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <button class="btn" @click="addDialogVisible = false">取消</button>
          <button class="btn btn-dark" @click="handleAddConfirm">确定保存</button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗 4：批量生成绑定码并导出 Excel -->
    <el-dialog
      v-model="batchExportDialogVisible"
      title="批量生成学生 6 位绑定码并导出 Excel"
      width="540px"
      destroy-on-close
    >
      <div v-loading="batchExporting" class="export-dialog-body space-y-4">
        <p class="dialog-tip">
          为学生一键批量签发 6 位大写英文字母与数字组成的友好绑定码（已剔除易混淆字符）。
          导出的 Excel 包含：学号、姓名、行政班级、所属学院、6位绑定码、有效期截止时间、当前绑定状态。
        </p>

        <div class="form-item">
          <label class="form-label font-bold text-xs text-slate-700">绑定码有效期：</label>
          <el-radio-group v-model="batchExportDays">
            <el-radio :value="14">14 天</el-radio>
            <el-radio :value="30">30 天 (推荐)</el-radio>
            <el-radio :value="60">60 天</el-radio>
            <el-radio :value="90">90 天 (本学期有效)</el-radio>
          </el-radio-group>
        </div>

        <div class="form-item">
          <label class="form-label font-bold text-xs text-slate-700">签发范围：</label>
          <el-radio-group v-model="batchExportScope">
            <el-radio value="all">全校在籍学生 (共 {{ stats.total }} 人)</el-radio>
            <el-radio value="volunteers">仅当前学期志愿者 (共 {{ stats.volunteers }} 人)</el-radio>
          </el-radio-group>
        </div>

        <div class="p-3 bg-blue-50/70 border border-blue-200/80 rounded-xl text-xs text-blue-900 flex items-start gap-2">
          <AppIcon name="info" :size="15" class="text-blue-600 shrink-0 mt-0.5" />
          <div class="leading-relaxed">
            <b>说明</b>：微信小程序端仅供学生绑定；获得志愿者资格的学生登录后将自动叠加查课工作台权限。
            导出的 Excel 表格可直接发送至各班级大群或由辅导员分发。
          </div>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <button class="btn btn-ghost" @click="batchExportDialogVisible = false">取消</button>
          <button class="btn btn-primary inline-flex items-center gap-1.5" :disabled="batchExporting" @click="handleBatchExport">
            <AppIcon v-if="!batchExporting" name="download" :size="14" />
            <span v-if="batchExporting" class="inline-block animate-spin mr-1">⟳</span>
            <span>{{ batchExporting ? '正在生成导出…' : '立即生成并下载 Excel' }}</span>
          </button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  margin-top: 6px;
}
.head-actions {
  display: flex;
  gap: 10px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.stat-cell {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 16px 20px;
}
.stat-cell .label {
  font-size: 11px;
  color: var(--ink-mute);
  text-transform: uppercase;
  margin-bottom: 6px;
}
.stat-cell .value {
  font-size: 26px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.2;
}
.stat-cell .unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--ink-mute);
}
.stat-cell .note {
  font-size: 11px;
  color: var(--ink-mute);
  margin-top: 6px;
}

.guide-banner {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 18px 24px;
  margin-bottom: 28px;
}
.g-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 12px;
}
.g-steps {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.g-step {
  display: flex;
  flex-direction: column;
  padding: 10px 14px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 2px;
  min-width: 140px;
  text-decoration: none;
}
.g-step.current {
  border-color: var(--blue);
  background: var(--blue-soft);
}
.g-step.g-link:hover {
  border-color: var(--ink);
}
.g-step .num { font-size: 11px; font-weight: 700; color: var(--blue); margin-bottom: 2px; }
.g-step .name { font-size: 13px; font-weight: 700; color: var(--ink); margin-bottom: 2px; }
.g-step .desc { font-size: 10px; color: var(--ink-mute); }
.g-arrow { font-size: 16px; color: var(--line-strong); }

.filter-chk {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-soft);
  cursor: pointer;
  margin-right: 8px;
}
.vol-switch-wrap { display: flex; align-items: center; }
.action-btns { display: flex; gap: 8px; justify-content: flex-end; }

.dialog-tip { font-size: 12px; color: var(--ink-mute); margin-bottom: 16px; line-height: 1.6; }

.token-card {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 20px;
  text-align: center;
}
.token-meta {
  display: flex;
  justify-content: space-around;
  margin-bottom: 16px;
  font-size: 13px;
}
.token-meta .label { color: var(--ink-mute); }
.token-box {
  background: var(--paper);
  border: 2px dashed var(--blue);
  color: var(--blue);
  padding: 16px;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.1em;
  word-break: break-all;
  margin-bottom: 14px;
  user-select: all;
}
.token-expire { font-size: 11px; color: var(--ink-mute); }

.task-select-list { display: flex; flex-direction: column; gap: 10px; max-height: 360px; overflow-y: auto; }
.task-assign-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
}
.task-assign-card .t-name { font-size: 13px; margin-bottom: 4px; }
.task-assign-card .t-sub { font-size: 11px; color: var(--ink-mute); }
.empty-tip { padding: 30px; text-align: center; color: var(--ink-mute); font-size: 13px; }

.tab-switch {
  display: flex;
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
}
.tab-btn {
  flex: 1;
  padding: 10px 0;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-mute);
  cursor: pointer;
}
.tab-btn.active {
  color: var(--ink);
  border-bottom-color: var(--ink);
}

.form-item {
  margin-bottom: 16px;
}
.form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 6px;
}
.form-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}
.chk-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ink-soft);
  cursor: pointer;
}

.dialog-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
