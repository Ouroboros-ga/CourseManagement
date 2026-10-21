<script setup lang="ts">
import { useDisplayPage } from '../../composables/useDisplayPage'
import AppPagination from '../../components/AppPagination.vue'
import { confirmGroupAssignment } from '../../composables/confirmGroupAssignment'
import { formatBeijingTime } from '@/utils/datetime'
import { assignmentWarnings } from '../../utils/assignmentWarnings'
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import {
  listStudents,
  listVolunteerQualifications,
  upsertVolunteerQualification,
  issueBindingToken,
  listRoleTargets,
  createStudent,
  administrativeClassOptions,
  createAdministrativeClass,
  updateAdministrativeClass,
  deleteAdministrativeClass,
  deleteStudent,
  batchDeleteStudents,
  type StudentItem,
  type VolunteerQualificationItem,
  type BindingTokenResult,
  type RoleTargetUser,
  type AdministrativeClassItem
} from '../../api/academic'
import { listTasks, type InspectionTaskItem } from '../../api/tasks'
import { request } from '../../api/workspaceHttp'
import { isAcademicScoped } from '../../api/workspaceHttp'
import { exportBindingTokensExcel, resetStudentBinding } from '../../api/auth'
import { downloadExcel } from '../../utils/download'
import AppIcon from '../../components/AppIcon.vue'
import { ContextEpoch } from '../../utils/contextEpoch'
import { formatPeriodText } from '../../utils/period'
import StudentGroupEnrollment from './StudentGroupEnrollment.vue'
import VolunteerEnrollmentDialog from './VolunteerEnrollmentDialog.vue'
import type { MemberCandidate } from '../../api/groupMembers'

const props = withDefaults(defineProps<{ mode?: 'legacy' | 'students' | 'qualifications' }>(), { mode: 'legacy' })
const showsQualification = computed(() => props.mode !== 'students')
const sessionStore = useSessionStore()

const directoryEpoch = new ContextEpoch(() => JSON.stringify([sessionStore.currentUser?.id, sessionStore.workspaceCollegeId,
  showsQualification.value ? sessionStore.currentSemesterId : '', currentPage.value, pageSize.value, selectedAdminClassId.value, searchQuery.value, filterOnlyVolunteers.value]))
onUnmounted(() => directoryEpoch.invalidate())
const canManageStudents = computed(() => sessionStore.hasPermission('student.manage') || (!sessionStore.workspaceMode && sessionStore.hasPermission('academic.manage')))
const canManageClasses = computed(() => sessionStore.hasPermission('academic.manage'))
const canBind = computed(() => sessionStore.hasPermission('identity.binding.manage'))
const canQualify = computed(() => sessionStore.hasPermission('volunteer.manage'))
const enrollmentVisible = ref(false), enrollmentStudent = ref<MemberCandidate | null>(null)
const canEnroll = computed(() => sessionStore.workspaceMode && sessionStore.campusRuntime?.business_scoped && sessionStore.hasPermission('volunteer.member.manage') && sessionStore.hasPermission('volunteer.group.read'))
const loading = ref(false)
const students = ref<StudentItem[]>([])
const volunteerQuals = ref<VolunteerQualificationItem[]>([])
const volunteerCount = ref(0)
const roleTargets = ref<RoleTargetUser[]>([])
const adminClasses = ref<AdministrativeClassItem[]>([])

// 服务端分页与筛选状态
const currentPage = ref(1)
const pageSize = ref(50)
const totalStudents = ref(0)
const allStudentsCount = ref(0)
const searchQuery = ref('')
const selectedAdminClassId = ref<string>('')
const filterOnlyVolunteers = ref(props.mode === 'qualifications')

// 学生多选与批量删除状态
const selectedStudentIds = ref<string[]>([])

const isAllCurrentPageSelected = computed(() => {
  if (students.value.length === 0) return false
  return students.value.every(s => selectedStudentIds.value.includes(String(s.id)))
})

const isIndeterminate = computed(() => {
  const currentCount = students.value.filter(s => selectedStudentIds.value.includes(String(s.id))).length
  return currentCount > 0 && currentCount < students.value.length
})

function toggleSelectAllCurrentPage(val: boolean) {
  if (val) {
    const idsToAdd = students.value.map(s => String(s.id)).filter(id => !selectedStudentIds.value.includes(id))
    selectedStudentIds.value = [...selectedStudentIds.value, ...idsToAdd]
  } else {
    const pageIds = new Set(students.value.map(s => String(s.id)))
    selectedStudentIds.value = selectedStudentIds.value.filter(id => !pageIds.has(id))
  }
}

function toggleSelectStudent(studentId: string, val: boolean) {
  if (val) {
    if (!selectedStudentIds.value.includes(studentId)) {
      selectedStudentIds.value.push(studentId)
    }
  } else {
    selectedStudentIds.value = selectedStudentIds.value.filter(id => id !== studentId)
  }
}

// 单条删除学生
async function handleDeleteStudent(stu: StudentItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除学生【${stu.name}】（学号：${stu.student_no}）吗？此操作将彻底删除该学生的基础底册记录。\n注意：若该学生已绑定账号或已产生历史考勤事实将受系统保护无法删除。`,
      '删除学生确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
  } catch {
    return
  }

  try {
    loading.value = true
    await deleteStudent(stu.id, undefined, stu.lock_version)
    ElMessage.success(`学生【${stu.name}】已成功删除`)
    selectedStudentIds.value = selectedStudentIds.value.filter(id => id !== String(stu.id))
    await loadData()
  } catch (err: any) {
    ElMessage.error(err.message || '删除学生失败')
  } finally {
    loading.value = false
  }
}

// 批量删除学生
async function handleBatchDeleteStudents() {
  if (selectedStudentIds.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定彻底删除选中的 ${selectedStudentIds.value.length} 名学生档案底册吗？\n（未绑定且无历史考勤事实的学生将被物理清理；已产生考勤或已绑定微信的学生将被系统安全拦截）`,
      '批量删除学生确认',
      {
        confirmButtonText: `确定删除(${selectedStudentIds.value.length}人)`,
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
  } catch {
    return
  }

  try {
    loading.value = true
    const versions = Object.fromEntries(students.value.filter(row => selectedStudentIds.value.includes(row.id) && row.lock_version !== undefined)
      .map(row => [row.id, row.lock_version!]))
    const res = await batchDeleteStudents(selectedStudentIds.value, undefined, versions)
    ElMessage.success(`已成功删除 ${res.deleted_count} 名学生底册档案`)
    selectedStudentIds.value = []
    await loadData()
  } catch (err: any) {
    ElMessage.error(err.message || '批量删除失败')
  } finally {
    loading.value = false
  }
}

// 行政班管理弹窗与整班删除
const adminClassDialogVisible = ref(false)
const deletingClassId = ref<string | null>(null)

async function handleDeleteAdminClass(cls: AdministrativeClassItem) {
  if (isAcademicScoped()) {
    try {
      await ElMessageBox.confirm(`删除空班级【${cls.class_name}】？存在学籍、名单或历史引用时不会删除，请改为停用。`, '删除行政班', { type: 'warning' })
      await doDeleteAdminClass(cls, false)
    } catch { /* 用户取消确认，不执行删除。 */ }
    return
  }
  try {
    await ElMessageBox({
      title: `删除行政班级：${cls.class_name}`,
      message: `确定要删除该行政班级吗？\n如果这是导入错误的批次，建议点击【连带清空班内学生并删除】一键彻底清理。\n（若班内学生已有考勤或微信绑定事实，系统将严格阻止误删）`,
      showCancelButton: true,
      confirmButtonText: '连带清空班内学生并删除',
      cancelButtonText: '仅删除空班级',
      confirmButtonClass: 'el-button--danger',
      distinguishCancelAndClose: true,
      type: 'warning',
    })
    // 确认：连带删除学生
    await doDeleteAdminClass(cls, true)
  } catch (action) {
    if (action === 'cancel') {
      // 取消按钮：仅删除空班级
      await doDeleteAdminClass(cls, false)
    }
  }
}

async function doDeleteAdminClass(cls: AdministrativeClassItem, cascadeStudents: boolean) {
  try {
    deletingClassId.value = String(cls.id)
    const res = await deleteAdministrativeClass(cls.id, { cascade_students: cascadeStudents, version: cls.ownership_version })
    ElMessage.success(
      cascadeStudents && res.deleted_students_count > 0
        ? `成功删除班级【${cls.class_name}】，并级联清理了 ${res.deleted_students_count} 名名下学生`
        : `成功删除班级【${cls.class_name}】`
    )
    if (selectedAdminClassId.value === String(cls.id)) {
      selectedAdminClassId.value = ''
    }
    await loadClasses()
    await loadData()
  } catch (err: any) {
    ElMessage.error(err.message || '删除班级失败')
  } finally {
    deletingClassId.value = null
  }
}

// 行政班新增 / 编辑表单状态
const adminClassFormVisible = ref(false)
const editingAdminClassId = ref<string | null>(null)
const adminClassForm = ref({
  class_code: '',
  class_name: '',
  grade_year: undefined as number | undefined,
  major_name: '',
  college: sessionStore.workspace?.name || '',
  head_teacher: '',
  counselor: '',
})
const savingAdminClass = ref(false)

function openCreateAdminClassDialog() {
  editingAdminClassId.value = null
  adminClassForm.value = {
    class_code: '',
    class_name: '',
    grade_year: new Date().getFullYear(),
    major_name: '',
    college: sessionStore.workspace?.name || '',
    head_teacher: '',
    counselor: '',
  }
  adminClassFormVisible.value = true
}

function openEditAdminClassDialog(cls: AdministrativeClassItem) {
  editingAdminClassId.value = String(cls.id)
  adminClassForm.value = {
    class_code: cls.class_code || '',
    class_name: cls.class_name || '',
    grade_year: cls.grade_year ?? undefined,
    major_name: cls.major_name || '',
    college: sessionStore.workspaceMode ? sessionStore.workspace?.name || '' : cls.college || '',
    head_teacher: cls.head_teacher || '',
    counselor: cls.counselor || '',
  }
  adminClassFormVisible.value = true
}

async function handleSaveAdminClass() {
  if (!adminClassForm.value.class_name.trim()) {
    ElMessage.warning('请填写班级名称')
    return
  }
  if (!editingAdminClassId.value && !adminClassForm.value.class_code.trim()) {
    ElMessage.warning('请填写班级代码')
    return
  }
  savingAdminClass.value = true
  try {
    if (editingAdminClassId.value) {
      await updateAdministrativeClass(editingAdminClassId.value, {
        ownership_version: adminClasses.value.find(row => row.id === editingAdminClassId.value)?.ownership_version,
        class_name: adminClassForm.value.class_name.trim(),
        grade_year: adminClassForm.value.grade_year ? Number(adminClassForm.value.grade_year) : undefined,
        major_name: adminClassForm.value.major_name.trim() || undefined,
        college: adminClassForm.value.college.trim() || undefined,
        head_teacher: adminClassForm.value.head_teacher.trim() || undefined,
        counselor: adminClassForm.value.counselor.trim() || undefined,
        reason: '管理端手动修改行政班信息',
      })
      ElMessage.success(`行政班【${adminClassForm.value.class_name}】信息已更新！`)
    } else {
      await createAdministrativeClass({
        class_code: adminClassForm.value.class_code.trim(),
        class_name: adminClassForm.value.class_name.trim(),
        grade_year: adminClassForm.value.grade_year ? Number(adminClassForm.value.grade_year) : undefined,
        major_name: adminClassForm.value.major_name.trim() || undefined,
        college: adminClassForm.value.college.trim() || undefined,
        head_teacher: adminClassForm.value.head_teacher.trim() || undefined,
        counselor: adminClassForm.value.counselor.trim() || undefined,
        reason: '管理端手动新建行政班',
      })
      ElMessage.success(`行政班【${adminClassForm.value.class_name}】创建成功！`)
    }
    adminClassFormVisible.value = false
    await loadClasses()
    await loadData()
  } catch (err: any) {
    ElMessage.error(err.message || '保存行政班失败')
  } finally {
    savingAdminClass.value = false
  }
}

// 候选学生列表（用于添加志愿者弹窗远程搜索）
const candidateStudents = ref<StudentItem[]>([])
const searchingCandidate = ref(false)

async function searchCandidates(query = '') {
  searchingCandidate.value = true
  try {
    const res = await listStudents({ keyword: query.trim() || undefined, page_size: 50 })
    candidateStudents.value = res.items || []
  } catch (err) {
    console.error('搜索学生候选人失败:', err)
  } finally {
    searchingCandidate.value = false
  }
}

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
const addMode = ref<'existing' | 'new'>(props.mode === 'students' ? 'new' : 'existing')
const selectedStudentId = ref<string>('')
const newStudentForm = ref({
  student_no: '',
  name: '',
  administrative_class_id: '' as string | number,
  set_as_volunteer: showsQualification.value,
  issue_token_now: canBind.value
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
    let studentIds: string[] | undefined = undefined
    if (batchExportScope.value === 'volunteers') {
      const qualificationExport = await listVolunteerQualifications(sessionStore.currentSemesterId)
      const volStudentIds = qualificationExport.items.filter(q => q.enabled).map(q => String(q.student_id))
      studentIds = volStudentIds
    }
    const blob = await exportBindingTokensExcel({
      days_valid: batchExportDays.value,
      student_ids: studentIds,
      reason: `管理员批量生成${batchExportScope.value === 'volunteers' ? '志愿者' : '在校学生'}绑定码`
    })
    downloadExcel(blob, `学生6位绑定码_${new Date().toISOString().slice(0, 10)}.xlsx`)
    ElMessage.success('批量生成 6 位绑定码并导出 Excel 成功！')
    batchExportDialogVisible.value = false
  } catch (err: any) {
    ElMessage.error(err.message || '导出绑定码失败')
  } finally {
    batchExporting.value = false
  }
}

async function loadClasses() {
  try {
    const res = await administrativeClassOptions()
    adminClasses.value = res.items || []
  } catch (e) {
    console.warn('获取行政班级列表失败:', e)
  }
}

async function loadData() {
  const ticket = directoryEpoch.begin()
  if (showsQualification.value && !sessionStore.currentSemesterId) return
  loading.value = true
  try {
    // 1. 获取行政班级列表（如尚未加载）
    if (adminClasses.value.length === 0) {
      await loadClasses()
    }

    // 2. 获取学生列表（带服务端分页与过滤）
    const stuRes = await listStudents({
      page: currentPage.value,
      page_size: pageSize.value,
      administrative_class_id: selectedAdminClassId.value ? selectedAdminClassId.value : undefined,
      keyword: searchQuery.value.trim() || undefined,
      is_volunteer: filterOnlyVolunteers.value ? true : undefined,
      semester_id: filterOnlyVolunteers.value ? sessionStore.currentSemesterId : undefined
    })
    if (!ticket.isCurrent()) return
    students.value = stuRes.items || []
    totalStudents.value = stuRes.total || 0

    // 若无任何过滤条件，记录全校在籍学生总数
    if (!selectedAdminClassId.value && !searchQuery.value.trim() && !filterOnlyVolunteers.value) {
      allStudentsCount.value = stuRes.total || 0
    }

    // 3. 获取当前学期志愿者资质列表
    if (showsQualification.value && sessionStore.hasPermission('volunteer.read')) {
      const volRes = await listVolunteerQualifications(sessionStore.currentSemesterId, students.value.map(s => s.id))
      if (!ticket.isCurrent()) return
      volunteerQuals.value = volRes.items || []
      const counts = await listStudents({ is_volunteer: true, semester_id: sessionStore.currentSemesterId, page_size: 1 })
      if (!ticket.isCurrent()) return
      volunteerCount.value = counts.total
    }

    // 4. 获取用户账号列表（仅持角色管理权限的管理员/教师加载，避免无权时触发 403）
    if (sessionStore.hasPermission('role.assign')) {
      try {
        const userRes = await listRoleTargets(students.value.map(s => s.id))
        if (!ticket.isCurrent()) return
        roleTargets.value = userRes.items || []
      } catch (e) {
        console.warn('获取用户账号列表失败:', e)
      }
    }
  } catch (err: unknown) {
    if (ticket.isCurrent()) ElMessage.error(err instanceof Error ? err.message : '学生资料读取失败')
  } finally {
    if (ticket.isLatest()) loading.value = false
  }
}

function handleFilterChange() {
  selectedStudentIds.value = []
  currentPage.value = 1
  loadData()
}

function handleResetFilters() {
  selectedAdminClassId.value = ''
  searchQuery.value = ''
  filterOnlyVolunteers.value = props.mode === 'qualifications'
  currentPage.value = 1
  loadData()
}

function handlePageChange(page: number) {
  selectedStudentIds.value = []
  currentPage.value = page
  loadData()
}



watch(
  () => sessionStore.currentSemesterId,
  () => {
    if (showsQualification.value) loadData()
  }
)

onMounted(() => {
  loadData()
})

// 映射班级 ID 到名称与实体
const adminClassMap = computed(() => {
  const map = new Map<string, string>()
  adminClasses.value.forEach(c => {
    map.set(String(c.id), c.class_name)
  })
  return map
})

const adminClassObjMap = computed(() => {
  const map = new Map<string, AdministrativeClassItem>()
  adminClasses.value.forEach(c => {
    map.set(String(c.id), c)
  })
  return map
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
  const total = allStudentsCount.value || totalStudents.value
  const volunteers = volunteerCount.value
  const boundCount = roleTargets.value.filter(u => u.student_id).length
  return { total, volunteers, boundCount }
})

// 切换志愿者资质
async function handleToggleVolunteer(student: StudentItem, enabled: boolean) {
  const context = () => JSON.stringify([sessionStore.currentUser?.id, sessionStore.workspaceCollegeId, sessionStore.currentSemesterId, sessionStore.workspace?.authorization_revision])
  const captured = context(), semesterId = sessionStore.currentSemesterId
  if (enabled && sessionStore.workspaceMode && !canEnroll.value) {
    ElMessage.warning('请由具有组织成员维护权限的管理员选择所属组后开通志愿者')
    return
  }
  if (enabled && canEnroll.value) {
    enrollmentStudent.value = { id: String(student.id), student_no: student.student_no, name: student.name }
    enrollmentVisible.value = true
    return
  }
  if (!enabled) {
    try {
      await ElMessageBox.confirm(`取消 ${student.name} 的本学期志愿者资格？这会影响其所有组织的新排班；已有任务需另行核对与改派。只需调整某个组时，请在组织内维护成员。`, '取消本学期资格', { type: 'warning', confirmButtonText: '确认取消资格', cancelButtonText: '返回' })
      if (captured !== context() || !canQualify.value || sessionStore.currentSemester?.status !== 'ACTIVE') return
    } catch { return }
  }
  try {
    await upsertVolunteerQualification({
      semester_id: semesterId,
      student_id: student.id,
      student_lock_version: student.lock_version,
      enabled,
      reason: '管理端手动配置资格'
    })
    if (captured !== context()) return
    ElMessage.success(`${student.name} 已${enabled ? '开通' : '取消'}本学期志愿者资质`)
    await loadData()
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
  const expireStr = formatBeijingTime(currentTokenInfo.value.tokenResult.expires_at)
  const text = `【查课小程序学生绑定】\n姓名：${currentTokenInfo.value.studentName}\n学号：${currentTokenInfo.value.studentNo}\n一次性绑定码：${currentTokenInfo.value.tokenResult.plaintext_code}\n有效截止：${expireStr}\n请在微信小程序登录后输入学号与绑定码完成身份认证。`
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制绑定信息到剪贴板，可直接发送给学生！')
  }).catch(() => {
    ElMessage.info('请手动选中文本进行复制')
  })
}

// 解除学生微信绑定
async function handleUnbindStudent(stu: StudentItem) {
  const boundUser = boundUserMap.value.get(stu.id)
  if (!boundUser) {
    ElMessage.warning('该学生未绑定微信用户')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要解除学生【${stu.name}】（学号：${stu.student_no}）与当前微信账号（UID: ${boundUser.id}）的绑定关系吗？\n解绑后该学生可使用新微信重新绑定，旧会话将立即撤销。`,
      '解除绑定确认',
      {
        confirmButtonText: '确定解绑',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await resetStudentBinding(String(boundUser.id), { reason: `管理员在底册解绑学生 ${stu.name}` })
    ElMessage.success(`学生【${stu.name}】已成功解除绑定！`)
    if (sessionStore.hasPermission('role.assign')) {
      const userRes = await listRoleTargets(students.value.map(s => s.id))
      roleTargets.value = userRes.items || []
    }
  } catch (err: unknown) {
    if (err !== 'cancel') {
      const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '解绑失败'
      ElMessage.error(msg)
    }
  }
}

// 打开分配任务弹窗
async function openAssignDialog(student: StudentItem) {
  let boundUser = boundUserMap.value.get(student.id)
  if (!boundUser) {
    try {
      await upsertVolunteerQualification({
        semester_id: sessionStore.currentSemesterId,
        student_id: student.id,
      student_lock_version: student.lock_version,
        enabled: true,
        reason: '分配查课任务时确保系统账号就绪'
      })
      if (sessionStore.hasPermission('role.assign')) {
        const userRes = await listRoleTargets(students.value.map(s => s.id))
        roleTargets.value = userRes.items || []
      }
      boundUser = boundUserMap.value.get(student.id)
    } catch (e) {
      console.error('自动初始化志愿者系统账号失败:', e)
    }
  }

  if (!boundUser) {
    ElMessage.error('无法为该志愿者初始化系统账号')
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
    const assigned = task.group_id ? await confirmGroupAssignment(task, assignTargetUser.value.id) : await request<InspectionTaskItem>(`/api/v1/inspection-tasks/${task.id}/assignment`, {
      method: 'PUT',
      body: JSON.stringify({
        volunteer_user_id: assignTargetUser.value.id,
        lock_version: task.lock_version || 0
      })
    })
    if (!assigned) return
    if (assigned.operation_warning_codes?.length) ElMessage.warning(assignmentWarnings(assigned.operation_warning_codes))
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
  if (showsQualification.value && sessionStore.workspaceMode && !canEnroll.value) {
    ElMessage.warning('添加志愿者需要组织成员维护权限；新增学籍请到“学生与班级”')
    return
  }
  if (showsQualification.value && canEnroll.value) {
    enrollmentStudent.value = null; enrollmentVisible.value = true
    return
  }
  selectedStudentId.value = ''
  newStudentForm.value = {
    student_no: '',
    name: '',
    administrative_class_id: selectedAdminClassId.value || '',
    set_as_volunteer: true,
    issue_token_now: canBind.value
  }
  searchCandidates('')
  addDialogVisible.value = true
}

// 确认添加
async function handleAddConfirm() {
  adding.value = true
  try {
    if (showsQualification.value && addMode.value === 'existing') {
      if (!selectedStudentId.value) {
        ElMessage.warning('请选择要设为志愿者的学生')
        return
      }
      await upsertVolunteerQualification({
        semester_id: sessionStore.currentSemesterId,
        student_id: selectedStudentId.value,
        student_lock_version: candidateStudents.value.find(row => row.id === selectedStudentId.value)?.lock_version,
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
        administrative_class_id: newStudentForm.value.administrative_class_id ? newStudentForm.value.administrative_class_id : undefined,
        reason: '管理端手动录入'
      })

      // 2. 如果勾选设为志愿者
      if (showsQualification.value && newStudentForm.value.set_as_volunteer) {
        await upsertVolunteerQualification({
          semester_id: sessionStore.currentSemesterId,
          student_id: newStu.id,
          student_lock_version: newStu.lock_version,
          enabled: true,
          reason: '新建学生时设为志愿者'
        })
      }

      ElMessage.success(`学生 ${newStu.name} 录入成功！`)
      addDialogVisible.value = false
      await loadData()

      // 3. 如果勾选立即签发绑定码
      if (canBind.value && newStudentForm.value.issue_token_now) {
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
const { page: classPage, rows: classRows, total: classTotal } = useDisplayPage(() => adminClasses.value)
</script>

<template>
  <div class="student-directory-container">
    <VolunteerEnrollmentDialog v-if="canEnroll" v-model="enrollmentVisible" :initial-student="enrollmentStudent" @saved="loadData" />
    <header class="page-head">
      <div class="title-row">
        <div>
          <h2>{{ showsQualification ? '本学期志愿者名册' : '当前学生档案与行政班' }}</h2>
          <p class="sub">
            {{ showsQualification ? '从已有学籍开通本学期资格并选择所属组织；同一人可加入多个组。' : '维护当前档案、班级和绑定；不随学期切换重建学生。' }}
          </p>
        </div>
        <div class="head-actions flex items-center gap-2">
          <router-link to="/dashboard/tasks" class="btn btn-ghost inline-flex items-center gap-1.5 text-xs text-slate-700">
            <AppIcon name="external-link" :size="13" />
            <span>前往查课安排</span>
          </router-link>
          <button v-if="canBind" class="btn btn-primary inline-flex items-center gap-1.5" @click="batchExportDialogVisible = true">
            <AppIcon name="download" :size="14" />
            <span>批量生成绑定码并导出 Excel</span>
          </button>
          <button v-if="showsQualification ? canQualify : canManageStudents" class="btn btn-dark inline-flex items-center gap-1.5" @click="openAddDialog">
            <AppIcon name="plus" :size="14" />
            <span>{{ showsQualification ? '添加志愿者并选组' : '添加学生' }}</span>
          </button>
        </div>
      </div>
    </header>

    <!-- 流程全景指引卡片 -->
    <div v-if="props.mode === 'legacy'" class="guide-banner">
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
    <div v-loading="loading" class="tbl-wrap">
      <div class="tbl-head">
        <div>
          <h3>{{ showsQualification ? '志愿者名册' : '学生名册' }}（共 {{ totalStudents }} 条）</h3>
          <div class="meta">{{ showsQualification ? `${sessionStore.currentSemesterName} 志愿者资格` : '当前有效学生档案，跨学期持续保留' }}</div>
        </div>
        <div class="tbl-tools flex items-center gap-2 flex-wrap">
          <!-- 批量操作栏（有选中时显示） -->
          <div
            v-if="!showsQualification && selectedStudentIds.length > 0"
            class="batch-bar flex items-center gap-2 bg-rose-50 border border-rose-200 text-rose-800 px-3 py-1 rounded"
          >
            <span class="text-xs font-bold font-mono">已选中 {{ selectedStudentIds.length }} 人</span>
            <button
              class="btn btn-sm bg-rose-600 hover:bg-rose-700 text-white font-semibold py-0.5 px-2.5 rounded shadow-sm inline-flex items-center gap-1"
              @click="handleBatchDeleteStudents"
            >
              <AppIcon name="trash" :size="12" />
              <span>批量删除学生</span>
            </button>
            <button class="btn btn-xs btn-ghost text-rose-700" @click="selectedStudentIds = []">
              取消选择
            </button>
          </div>

          <!-- 行政班级筛选 -->
          <el-select
            v-model="selectedAdminClassId"
            placeholder="全部行政班级"
            clearable
            filterable
            style="width: 175px"
            @change="handleFilterChange"
            @clear="handleFilterChange"
          >
            <el-option label="全部行政班级" value="" />
            <el-option
              v-for="c in adminClasses"
              :key="c.id"
              :label="c.class_name"
              :value="String(c.id)"
            />
          </el-select>

          <!-- 班级管理按钮 -->
          <button
            class="btn btn-sm btn-ghost border border-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
            v-if="!showsQualification"
            title="查看所有行政班级，支持整班清理"
            @click="adminClassDialogVisible = true"
          >
            <AppIcon name="folder" :size="13" />
            <span>班级管理</span>
          </button>

          <button
            v-if="!showsQualification && selectedAdminClassId && canManageClasses"
            class="btn btn-sm text-rose-700 bg-rose-50 border border-rose-200 hover:bg-rose-100 inline-flex items-center gap-1"
            title="整班删除选中的行政班及其名下学生"
            @click="() => { const cls = adminClasses.find(c => String(c.id) === selectedAdminClassId); if (cls) handleDeleteAdminClass(cls) }"
          >
            <AppIcon name="trash" :size="12" />
            <span>整班删除此班</span>
          </button>

          <!-- 仅看志愿者 -->
          <label v-if="props.mode === 'legacy'" class="filter-chk font-mono">
            <input type="checkbox" v-model="filterOnlyVolunteers" @change="handleFilterChange" />
            <span>仅看志愿者 ({{ stats.volunteers }})</span>
          </label>

          <!-- 关键字搜索 -->
          <div class="search-input-wrap">
            <input
              v-model="searchQuery"
              type="text"
              class="input"
              style="width: 160px"
              placeholder="姓名 / 学号回车…"
              @keyup.enter="handleFilterChange"
            />
            <button class="btn btn-sm btn-ghost" @click="handleFilterChange">搜索</button>
          </div>

          <button
            v-if="selectedAdminClassId || searchQuery || filterOnlyVolunteers"
            class="btn btn-sm btn-ghost text-amber-700"
            @click="handleResetFilters"
          >
            重置
          </button>
          <button class="btn btn-sm btn-ghost" @click="loadData">⟳ 刷新</button>
        </div>
      </div>

      <table class="tbl">
        <thead>
          <tr>
            <th style="width: 44px; text-align: center">
              <input
                type="checkbox"
                :checked="isAllCurrentPageSelected"
                :indeterminate="isIndeterminate"
                @change="(e: any) => toggleSelectAllCurrentPage(e.target.checked)"
              />
            </th>
            <th>学号</th>
            <th>姓名</th>
            <th>行政班级</th>
            <th>小程序微信绑定状态</th>
            <th v-if="showsQualification">志愿者资质（本学期）</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="stu in students" :key="stu.id">
            <td style="text-align: center" @click.stop>
              <input
                type="checkbox"
                :checked="selectedStudentIds.includes(String(stu.id))"
                @change="(e: any) => toggleSelectStudent(String(stu.id), e.target.checked)"
              />
            </td>
            <td class="cell-mono font-bold">{{ stu.student_no }}</td>
            <td class="cell-main font-bold">{{ stu.name }}</td>
            <td class="cell-sub">
              <div v-if="stu.administrative_class_name || adminClassMap.get(String(stu.administrative_class_id))" class="space-y-1">
                <span class="class-badge">
                  {{ stu.administrative_class_name || adminClassMap.get(String(stu.administrative_class_id)) }}
                </span>
                <div
                  v-if="adminClassObjMap.get(String(stu.administrative_class_id)) && (adminClassObjMap.get(String(stu.administrative_class_id))?.head_teacher || adminClassObjMap.get(String(stu.administrative_class_id))?.counselor)"
                  class="text-[11px] text-gray-500 flex items-center gap-1.5 flex-wrap"
                >
                  <span
                    v-if="adminClassObjMap.get(String(stu.administrative_class_id))?.head_teacher"
                    class="text-emerald-700 bg-emerald-50 px-1 py-0.2 rounded border border-emerald-100"
                    title="行政班班主任"
                  >
                    班主任: {{ adminClassObjMap.get(String(stu.administrative_class_id))?.head_teacher }}
                  </span>
                  <span
                    v-if="adminClassObjMap.get(String(stu.administrative_class_id))?.counselor"
                    class="text-blue-700 bg-blue-50 px-1 py-0.2 rounded border border-blue-100"
                    title="责任区辅导员"
                  >
                    辅导员: {{ adminClassObjMap.get(String(stu.administrative_class_id))?.counselor }}
                  </span>
                </div>
              </div>
              <span v-else-if="stu.administrative_class_id" class="text-xs text-slate-400 font-mono">
                行政班 #{{ stu.administrative_class_id }}
              </span>
              <span v-else class="text-xs text-slate-400 italic">
                未指定班级
              </span>
            </td>
            <td>
              <span v-if="boundUserMap.get(stu.id)?.has_wechat" class="tag tag-green inline-flex items-center gap-1">
                <AppIcon name="check-circle" :size="12" class="text-emerald-600" />
                <span>微信已绑定</span>
              </span>
              <span
                v-else-if="boundUserMap.has(stu.id)"
                class="tag tag-amber inline-flex items-center gap-1"
                title="该学生已有系统账号，尚未在微信小程序完成绑定；受派仍需符合资格与规则"
              >
                <AppIcon name="warning" :size="12" class="text-amber-600" />
                <span>尚未绑定微信</span>
              </span>
              <span v-else class="tag tag-gray inline-flex items-center gap-1">
                <AppIcon name="close" :size="10" class="text-slate-400" />
                <span>未绑定微信小程序</span>
              </span>
            </td>
            <td v-if="showsQualification">
              <div class="vol-switch-wrap">
                <el-switch v-if="props.mode !== 'qualifications'"
                  :disabled="!canQualify" :model-value="volunteerMap.get(stu.id) || false"
                  active-text="志愿者"
                  inactive-text="普通学生"
                  @change="(val: boolean) => handleToggleVolunteer(stu, val)"
                />
                <template v-if="props.mode === 'qualifications'">
                  <el-tag :type="volunteerMap.get(stu.id) ? 'success' : 'info'">{{ volunteerMap.get(stu.id) ? '本学期有效' : '本学期未开通' }}</el-tag>
                  <el-button v-if="canQualify && volunteerMap.get(stu.id)" :disabled="sessionStore.currentSemester?.status !== 'ACTIVE'" link @click="handleToggleVolunteer(stu, false)">取消本学期资格</el-button>
                </template>
                <StudentGroupEnrollment v-if="volunteerMap.get(String(stu.id)) && sessionStore.campusRuntime?.business_scoped && sessionStore.hasPermission('volunteer.member.manage') && sessionStore.hasPermission('volunteer.group.read')" :student-id="String(stu.id)" :name="stu.name" />
              </div>
            </td>
            <td style="text-align: right">
              <div class="action-btns flex items-center justify-end gap-1.5">
                <button v-if="props.mode === 'legacy' && showsQualification && sessionStore.hasPermission('assignment.manage') && volunteerMap.get(stu.id)" class="btn btn-sm" @click="openAssignDialog(stu)">分配任务</button>
                <button v-if="canBind" class="btn btn-sm inline-flex items-center gap-1" @click="handleIssueToken(stu)">
                  <AppIcon name="key" :size="12" />
                  <span>生成绑定码</span>
                </button>

                <button
                  v-if="canBind && boundUserMap.get(stu.id)"
                  class="btn btn-sm btn-ghost text-amber-600 hover:bg-amber-50 inline-flex items-center gap-0.5"
                  title="解除微信小程序的账号绑定"
                  @click="handleUnbindStudent(stu)"
                >
                  <AppIcon name="ban" :size="12" />
                  <span>解绑</span>
                </button>
                <button
                  class="btn btn-sm btn-ghost text-rose-600 hover:bg-rose-50 inline-flex items-center gap-0.5"
                  v-if="!showsQualification && canManageStudents" title="删除此学生底册档案"
                  @click="handleDeleteStudent(stu)"
                >
                  <AppIcon name="trash" :size="12" />
                  <span>删除</span>
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="students.length === 0">
            <td :colspan="showsQualification ? 7 : 6" class="empty-tip">未找到匹配的学生记录</td>
          </tr>
        </tbody>
      </table>

      <AppPagination v-model:current-page="currentPage" :total="totalStudents" @current-change="handlePageChange" />
    </div>

    <!-- 弹窗 1：一次性绑定码发放 -->
    <el-dialog
      v-model="tokenDialogVisible"
      title="一次性小程序绑定码已签发"
      width="540px"
      append-to-body
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
            有效截止时间：<span class="font-mono">{{ formatBeijingTime(currentTokenInfo.tokenResult?.expires_at) }}</span>（超时自动失效）
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
      append-to-body
      destroy-on-close
    >
      <div v-loading="assigning" class="assign-dialog-body">
        <p class="dialog-tip">
          志愿者系统查课账号已就绪（系统 UID: {{ assignTargetUser?.id }}）。可从本周（第 {{ sessionStore.currentWeekNo }} 周）未分配的查课任务中直接指派；无论志愿者是否已登录微信小程序均可排班，学生后续在小程序登录后即可查收执行：
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
                {{ t.inspection_date }} {{ formatPeriodText(t.start_period, t.end_period) }} · {{ t.classroom_snapshot || '教室' }}
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
      append-to-body
      destroy-on-close
    >
      <div v-loading="adding" class="add-dialog-body">
        <div v-if="showsQualification" class="tab-switch">
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
              remote
              :remote-method="searchCandidates"
              :loading="searchingCandidate"
              placeholder="请输入姓名或学号搜索全校学生…"
              style="width: 100%"
            >
              <el-option
                v-for="s in candidateStudents"
                :key="s.id"
                :label="`${s.name} (${s.student_no}) - ${s.administrative_class_name || adminClassMap.get(String(s.administrative_class_id)) || '未分配班级'}`"
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
          <div class="form-item">
            <label class="form-label">所属行政班：</label>
            <select v-model="newStudentForm.administrative_class_id" class="input">
              <option value="">未指定班级</option>
              <option v-for="c in adminClasses" :key="c.id" :value="c.id">
                {{ c.class_name }} {{ c.head_teacher ? `(班主任: ${c.head_teacher})` : '' }}
              </option>
            </select>
          </div>
          <div class="form-options">
            <label class="chk-label">
              <input type="checkbox" v-model="newStudentForm.set_as_volunteer" :disabled="!showsQualification" />
              <span>{{ showsQualification ? `同时开通本学期（${sessionStore.currentSemesterName}）志愿者资质` : '志愿者资格请到“志愿者组织”维护' }}</span>
            </label>
            <label class="chk-label">
              <input type="checkbox" v-model="newStudentForm.issue_token_now" :disabled="!canBind" />
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
      append-to-body
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

    <!-- 行政班管理与整班删除弹窗 -->
    <el-dialog
      v-model="adminClassDialogVisible"
      title="行政班级管理与责任人配置"
      width="780px"
      append-to-body
    >
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div class="p-2.5 bg-amber-50 border border-amber-200 rounded text-xs text-amber-900 leading-relaxed flex-1 mr-3">
            <b>责任区与整班管理说明</b>：支持手动维护各行政班的班主任与责任区辅导员，或整班清理底册数据。<br />
            若班内学生已有正式考勤记录，系统将严格阻止误删保护历史数据。
          </div>
          <button
            class="btn btn-sm btn-dark shrink-0 inline-flex items-center gap-1.5"
            @click="openCreateAdminClassDialog"
          >
            <AppIcon name="plus" :size="13" />
            <span>新增行政班</span>
          </button>
        </div>

        <div class="max-h-[420px] overflow-y-auto border border-slate-200 rounded">
          <table class="w-full text-left text-sm">
            <thead class="bg-slate-50 border-b border-slate-200 text-xs text-slate-500 uppercase font-mono">
              <tr>
                <th class="p-2.5">班级名称</th>
                <th class="p-2.5">班级代码</th>
                <th class="p-2.5">班主任</th>
                <th class="p-2.5">辅导员</th>
                <th class="p-2.5">年级/学院</th>
                <th class="p-2.5 text-right" style="min-width: 140px;">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="cls in classRows" :key="cls.id" class="hover:bg-slate-50">
                <td class="p-2.5 font-bold text-slate-800">{{ cls.class_name }}</td>
                <td class="p-2.5 font-mono text-xs text-slate-600">{{ cls.class_code }}</td>
                <td class="p-2.5 text-xs">
                  <span v-if="cls.head_teacher" class="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-100 font-medium">
                    {{ cls.head_teacher }}
                  </span>
                  <span v-else class="text-slate-400 italic">未指定</span>
                </td>
                <td class="p-2.5 text-xs">
                  <span v-if="cls.counselor" class="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-100 font-medium">
                    {{ cls.counselor }}
                  </span>
                  <span v-else class="text-slate-400 italic">未指定</span>
                </td>
                <td class="p-2.5 text-xs text-slate-500">{{ cls.college || '默认' }} {{ cls.grade_year ? `(${cls.grade_year}级)` : '' }}</td>
                <td class="p-2.5 text-right space-x-1.5">
                  <button
                    class="btn btn-xs btn-ghost border border-slate-200 inline-flex items-center gap-1 text-slate-700 hover:bg-slate-100"
                    @click="openEditAdminClassDialog(cls)"
                  >
                    <AppIcon name="edit" :size="11" />
                    <span>编辑</span>
                  </button>
                  <button
                    class="btn btn-xs text-rose-600 hover:bg-rose-50 border border-rose-200 inline-flex items-center gap-1"
                    :disabled="deletingClassId === String(cls.id)"
                    @click="handleDeleteAdminClass(cls)"
                  >
                    <AppIcon name="trash" :size="11" />
                    <span>{{ deletingClassId === String(cls.id) ? '正在删除…' : '删除' }}</span>
                  </button>
                </td>
              </tr>
              <tr v-if="adminClasses.length === 0">
                <td colspan="6" class="p-4 text-center text-slate-400">暂无行政班级数据</td>
              </tr>
            </tbody>
          </table>
          <AppPagination v-model:current-page="classPage" :total="classTotal" />
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <button class="btn btn-ghost" @click="adminClassDialogVisible = false">关闭</button>
        </div>
      </template>
    </el-dialog>

    <!-- 弹窗：新建 / 编辑行政班级 -->
    <el-dialog
      v-model="adminClassFormVisible"
      :title="editingAdminClassId ? '编辑行政班级信息与责任人' : '新建行政班级'"
      width="500px"
      append-to-body
    >
      <div v-loading="savingAdminClass" class="space-y-3.5">
        <div class="form-item">
          <label class="form-label">班级名称 *：</label>
          <input
            v-model="adminClassForm.class_name"
            type="text"
            class="input"
            placeholder="例如：24人工智能1班"
          />
        </div>
        <div class="form-item">
          <label class="form-label">班级代码 *：</label>
          <input
            v-model="adminClassForm.class_code"
            type="text"
            class="input font-mono"
            :disabled="!!editingAdminClassId"
            placeholder="例如：24AI01"
          />
          <div v-if="editingAdminClassId" class="text-[11px] text-slate-400 mt-1">班级唯一代码不可修改</div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="form-item">
            <label class="form-label">班主任：</label>
            <input
              v-model="adminClassForm.head_teacher"
              type="text"
              class="input"
              placeholder="例如：李老师"
            />
          </div>
          <div class="form-item">
            <label class="form-label">责任区辅导员：</label>
            <input
              v-model="adminClassForm.counselor"
              type="text"
              class="input"
              placeholder="例如：王老师"
            />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="form-item">
            <label class="form-label">所属二级学院：</label>
            <input
              v-model="adminClassForm.college"
              type="text"
              class="input"
              placeholder="例如：人工智能学院"
            />
          </div>
          <div class="form-item">
            <label class="form-label">入学年份 (年级)：</label>
            <input
              v-model.number="adminClassForm.grade_year"
              type="number"
              class="input font-mono"
              placeholder="例如：2024"
            />
          </div>
        </div>
        <div class="form-item">
          <label class="form-label">专业名称：</label>
          <input
            v-model="adminClassForm.major_name"
            type="text"
            class="input"
            placeholder="例如：人工智能技术应用"
          />
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <button class="btn btn-ghost" @click="adminClassFormVisible = false">取消</button>
          <button class="btn btn-dark" :disabled="savingAdminClass" @click="handleSaveAdminClass">
            {{ savingAdminClass ? '正在保存…' : '确认保存' }}
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
  margin-top: 0;
}
.head-actions {
  display: flex;
  gap: 10px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.stat-cell {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 12px 18px;
}
.stat-cell .label {
  font-size: 11px;
  color: var(--ink-mute);
  text-transform: uppercase;
  margin-bottom: 4px;
}
.stat-cell .value {
  font-size: 24px;
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
  margin-top: 4px;
}

.guide-banner {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  padding: 14px 20px;
  margin-bottom: 16px;
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

.tbl-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: var(--paper-deep);
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
  gap: 12px;
}
.pagination-info {
  font-size: 12px;
  color: var(--ink-mute);
}
.class-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #f1f5f9;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
}
.search-input-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
