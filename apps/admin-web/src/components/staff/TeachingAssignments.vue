<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import {
  createTeachingAssignment,
  endTeachingAssignment,
  getScopedRow,
  listScopedOptions,
  listStaff,
  listTeachingAssignments,
  type ScopedAcademicRow,
  type StaffAnchor,
  type StaffProfile,
  type TeachingAssignmentRow
} from '../../api/staff'

const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()

const contextKey = computed(() => JSON.stringify([
  session.currentUser?.id || '', props.collegeId, session.workspace?.authorization_revision || ''
]))
const teacherFilter = ref('')
const { data: rows, busy, error, load } = useWorkspaceRead(
  () => JSON.stringify([contextKey.value, teacherFilter.value]),
  () => !!props.collegeId,
  () => listTeachingAssignments(props.collegeId, { staff_id: teacherFilter.value || undefined })
)

// 名称投影：档案与教学班名称按需补齐，显示始终附原始 ID 便于核对。
const staffLabelMap = ref<Record<string, string>>({})
const classNameMap = ref<Record<string, string>>({})
watch(rows, () => {
  void resolveNames()
})
async function resolveNames() {
  try {
    const page = await listStaff(props.collegeId, { keyword: '', page_size: 200 })
    for (const staff of Array.isArray(page?.items) ? page.items : []) {
      if (!staffLabelMap.value[staff.id]) staffLabelMap.value[staff.id] = `${staff.staff_no} ${staff.name}`
    }
  } catch { /* 候选不可用时仅展示 ID */ }
  for (const row of Array.isArray(rows.value) ? rows.value : []) {
    if (row.anchor_type === 'LOCAL' && row.teaching_class_id && !classNameMap.value[row.teaching_class_id]) {
      await loadClassName(row.teaching_class_id)
    }
  }
}
async function loadClassName(id: string) {
  try {
    const detail = await getScopedRow(props.collegeId, 'teaching-classes', id)
    classNameMap.value[id] = String(detail.class_code || detail.class_name || '') || '—'
  } catch { classNameMap.value[id] = '' }
}
const staffLabel = (id: string) => staffLabelMap.value[id] || `教职工 ID ${id}`
const anchorText = (row: TeachingAssignmentRow) => row.anchor_type === 'LOCAL' ? '本院教学班' : '共享课程身份'
const targetText = (row: TeachingAssignmentRow) => row.anchor_type === 'LOCAL'
  ? (classNameMap.value[row.teaching_class_id || ''] || '—')
  : `共享身份 ${row.academic_offering_id}`
const semesterLabel = (id: string) => session.semesters.find(item => item.id === id)?.name || id

async function loadStaffOptions(keyword = '', ids: string[] = []) {
  try {
    staffOptions.value = await listStaff(props.collegeId, { keyword: keyword || undefined, page_size: 200 })
    for (const staff of staffOptions.value.items) {
      if (ids.includes(staff.id)) staffLabelMap.value[staff.id] = `${staff.staff_no} ${staff.name}`
    }
  } catch (e) {
    staffError.value = e instanceof Error ? e.message : '教职工候选加载失败'
  }
}
const staffOptions = ref<{ items: StaffProfile[]; total: number; page: number; page_size: number }>({ items: [], total: 0, page: 1, page_size: 200 })
const staffError = ref('')

const createOpen = ref(false)
const createError = ref('')
const createBusy = ref(false)
const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
const createForm = ref({ teacherId: '', semesterId: '', teachingClassId: '', effectiveFrom: '', effectiveTo: '', reason: '' })
const classOptions = ref<ScopedAcademicRow[]>([])
const classLoading = ref(false)
async function openCreate() {
  createForm.value = { teacherId: '', semesterId: session.currentSemesterId || '', teachingClassId: '', effectiveFrom: today(), effectiveTo: '', reason: '' }
  createError.value = ''
  createOpen.value = true
  void loadStaffOptions()
  void loadClassOptions()
}
watch(() => createForm.value.semesterId, () => { void loadClassOptions() })
async function loadClassOptions(keyword = '') {
  const semesterId = createForm.value.semesterId
  if (!semesterId) { classOptions.value = []; return }
  classLoading.value = true
  try {
    const page = await listScopedOptions(props.collegeId, 'teaching-classes', { semester_id: semesterId, keyword, page_size: 200 })
    classOptions.value = (page?.items || []).filter((row: ScopedAcademicRow) => row.status === 'ACTIVE')
    for (const row of classOptions.value) classNameMap.value[row.id] = `${row.class_code || ''} ${row.class_name || ''}`.trim()
  } catch (e) {
    classOptions.value = []
    createError.value = '教学班候选加载失败：' + (e instanceof Error ? e.message : '请重试')
  } finally { classLoading.value = false }
}
async function submitCreate() {
  const form = createForm.value
  if (!form.teacherId || !form.semesterId || !form.teachingClassId) {
    createError.value = '请先明确选择教师、学期和本院教学班；共享身份任命请通过资料准备导入。'
    return
  }
  createBusy.value = true
  createError.value = ''
  const anchor: StaffAnchor = 'LOCAL'
  try {
    await createTeachingAssignment(props.collegeId, {
      staff_id: form.teacherId,
      semester_id: form.semesterId,
      anchor_type: anchor,
      teaching_class_id: form.teachingClassId,
      academic_offering_id: null,
      effective_from: form.effectiveFrom,
      effective_to: form.effectiveTo || null,
      reason: (form.reason || '').trim() || null
    })
    createOpen.value = false
    ElMessage.success('已建立授课任命')
    void load()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '保存失败'
  } finally { createBusy.value = false }
}

const endOpen = ref(false)
const endRow = ref<TeachingAssignmentRow | null>(null)
const endForm = ref({ effectiveTo: today(), reason: '' })
const endError = ref('')
const endBusy = ref(false)
function startEnd(row: TeachingAssignmentRow) {
  endRow.value = row
  endForm.value = { effectiveTo: today(), reason: '' }
  endError.value = ''
  endOpen.value = true
}
async function submitEnd() {
  const row = endRow.value
  if (!row) return
  if (!endForm.value.effectiveTo) { endError.value = '请选择结束日期（当日仍任教，次日不是该班）'; return }
  endBusy.value = true
  endError.value = ''
  try {
    await endTeachingAssignment(props.collegeId, row.id, {
      effective_to: endForm.value.effectiveTo,
      lock_version: row.lock_version,
      reason: (endForm.value.reason || '').trim() || null
    })
    endOpen.value = false
    ElMessage.success('任命已结束')
    void load()
  } catch (e) {
    endError.value = e instanceof Error ? e.message : '结束失败'
  } finally { endBusy.value = false }
}

</script>

<template>
  <section aria-label="任课教师与授课关系">
    <el-alert title="授课关系是明确的资源授权：本院档案 + 学期 + 教学班，有效期任选中。共享课程身份与批量任命请通过「资料准备」导入；姓名相同不等于授权。" type="info" :closable="false" />
    <div class="filters">
      <el-select v-model="teacherFilter" filterable clearable placeholder="按教师筛选" style="max-width: 240px">
        <el-option v-for="staff in staffOptions.items" :key="staff.id" :value="staff.id" :label="`${staff.staff_no} ${staff.name}`" />
      </el-select>
      <el-button :loading="busy" @click="void load()">刷新</el-button>
      <el-button type="primary" :disabled="busy || !!error" @click="openCreate">建立授课任命</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="staffError" :title="staffError" type="warning" :closable="false" />
    <el-table :data="rows || []" v-loading="busy" empty-text="当前学院暂无授课任命记录">
      <el-table-column label="教师" min-width="160"><template #default="{ row }">{{ staffLabel(row.staff_id) }}</template></el-table-column>
      <el-table-column label="学期" min-width="120"><template #default="{ row }">{{ semesterLabel(row.semester_id) }}</template></el-table-column>
      <el-table-column label="锚点" min-width="120"><template #default="{ row }">{{ anchorText(row) }}</template></el-table-column>
      <el-table-column label="教学班 / 共享身份" min-width="220"><template #default="{ row }">{{ targetText(row) }}</template></el-table-column>
      <el-table-column prop="effective_from" label="生效日" min-width="110" />
      <el-table-column label="截止日" min-width="110"><template #default="{ row }">{{ row.effective_to || '长期' }}</template></el-table-column>
      <el-table-column label="操作" min-width="90" fixed="right">
        <template #default="{ row }"><el-button link @click="startEnd(row)">结束</el-button></template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createOpen" title="建立授课任命" width="560px" :close-on-click-modal="false">
      <el-form label-width="112px">
        <el-form-item label="教师" required>
          <el-select v-model="createForm.teacherId" filterable remote :remote-method="loadStaffOptions" placeholder="选择本院教职工（按档案，不按姓名）" style="width: 100%">
            <el-option v-for="staff in staffOptions.items.filter(item => item.status === 'ACTIVE')" :key="staff.id" :value="staff.id" :label="`${staff.staff_no} ${staff.name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="学期" required>
          <el-select v-model="createForm.semesterId" placeholder="选择学期" style="width: 100%">
            <el-option v-for="semester in session.semesters" :key="semester.id" :value="semester.id" :label="semester.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="本院教学班" required>
          <el-select v-model="createForm.teachingClassId" filterable remote :remote-method="loadClassOptions" :loading="classLoading" placeholder="选择该学期的本院教学班" style="width: 100%">
            <el-option v-for="row in classOptions" :key="row.id" :value="row.id" :label="`${row.class_code || ''} ${row.class_name || ''}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="生效区间" required>
          <el-date-picker v-model="createForm.effectiveFrom" type="date" value-format="YYYY-MM-DD" :clearable="false" aria-label="生效日" />
          <el-date-picker v-model="createForm.effectiveTo" type="date" value-format="YYYY-MM-DD" clearable aria-label="截止日（可留空）" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="createForm.reason" type="textarea" :rows="2" maxlength="512" /></el-form-item>
      </el-form>
      <el-alert v-if="createError" :title="createError" type="error" :closable="false" />
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="createBusy" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="endOpen" title="结束授课任命" width="480px" :close-on-click-modal="false">
      <p v-if="endRow">教师 <strong>{{ staffLabel(endRow.staff_id) }}</strong> 的该任命在结束日当天仍有效。</p>
      <el-form label-width="112px">
        <el-form-item label="结束日期" required><el-date-picker v-model="endForm.effectiveTo" type="date" value-format="YYYY-MM-DD" :clearable="false" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="endForm.reason" type="textarea" :rows="2" maxlength="512" /></el-form-item>
      </el-form>
      <el-alert v-if="endError" :title="endError" type="error" :closable="false" />
      <template #footer>
        <el-button @click="endOpen = false">取消</el-button>
        <el-button type="primary" :loading="endBusy" @click="submitEnd">确认结束</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }
</style>
