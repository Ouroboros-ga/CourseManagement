<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../../stores/session'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import {
  createResponsibility,
  endResponsibility,
  getScopedRow,
  listResponsibilities,
  listScopedOptions,
  listStaff,
  responsibilityHandover,
  type ResponsibilityRow,
  type ScopedAcademicRow,
  type StaffDuty,
  type StaffProfile
} from '../../api/staff'

const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()

const contextKey = computed(() => JSON.stringify([
  session.currentUser?.id || '', props.collegeId, session.workspace?.authorization_revision || ''
]))
const staffFilter = ref('')
const { data: rows, busy, error, load } = useWorkspaceRead(
  () => JSON.stringify([contextKey.value, staffFilter.value]),
  () => !!props.collegeId,
  () => listResponsibilities(props.collegeId, { staff_id: staffFilter.value || undefined })
)

const dutyLabelMap: Record<string, string> = { HEAD_TEACHER: '班主任', COUNSELOR: '辅导员' }
const dutyLabel = (duty: string) => dutyLabelMap[duty] || duty
const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())

const staffLabelMap = ref<Record<string, string>>({})
const classNameMap = ref<Record<string, string>>({})
const staffOptions = ref<StaffProfile[]>([])
watch(rows, () => { void resolveNames() })
async function resolveNames() {
  try {
    const page = await listStaff(props.collegeId, { keyword: '', page_size: 200 })
    staffOptions.value = page.items
    for (const staff of page.items) {
      if (!staffLabelMap.value[staff.id]) staffLabelMap.value[staff.id] = `${staff.staff_no} ${staff.name}`
    }
  } catch { /* 名称缺失时显示原始 ID */ }
  for (const row of Array.isArray(rows.value) ? rows.value : []) {
    if (!classNameMap.value[row.administrative_class_id]) await loadClassName(row.administrative_class_id)
  }
}
async function loadClassName(id: string) {
  try {
    const detail = await getScopedRow(props.collegeId, 'administrative-classes', id)
    classNameMap.value[id] = String(detail.class_name || detail.class_code || '') || '—'
  } catch { classNameMap.value[id] = '' }
}
const staffLabel = (id: string) => staffLabelMap.value[id] || `教职工 ID ${id}`
const classLabel = (id: string) => classNameMap.value[id] || `行政班 ID ${id}`

const createOpen = ref(false)
const createError = ref('')
const createBusy = ref(false)
const createForm = ref({ staffId: '', classId: '', duty: '' as '' | StaffDuty, effectiveFrom: '', effectiveTo: '', reason: '' })
const classOptions = ref<ScopedAcademicRow[]>([])
const classLoading = ref(false)
async function openCreate() {
  createForm.value = { staffId: '', classId: '', duty: '', effectiveFrom: today(), effectiveTo: '', reason: '' }
  createError.value = ''
  createOpen.value = true
  try {
    const page = await listStaff(props.collegeId, { keyword: '', page_size: 200 })
    staffOptions.value = page.items
    for (const staff of page.items) staffLabelMap.value[staff.id] = `${staff.staff_no} ${staff.name}`
  } catch { staffOptions.value = [] }
  void loadClassOptions()
}
async function loadClassOptions(keyword = '') {
  classLoading.value = true
  try {
    const page = await listScopedOptions(props.collegeId, 'administrative-classes', { keyword, page_size: 200 })
    classOptions.value = (page?.items || []).filter((row: ScopedAcademicRow) => row.status === 'ACTIVE')
    for (const row of classOptions.value) classNameMap.value[row.id] = String(row.class_name || row.class_code || '')
  } catch (e) {
    classOptions.value = []
    createError.value = '行政班候选加载失败：' + (e instanceof Error ? e.message : '请重试')
  } finally { classLoading.value = false }
}
async function submitCreate() {
  const form = createForm.value
  if (!form.staffId || !form.classId || !form.duty) {
    createError.value = '请先明确选择教职工、行政班和职责（班主任/辅导员）；责任列为空或缺失人员时不撤销既有任职。'
    return
  }
  createBusy.value = true
  createError.value = ''
  try {
    await createResponsibility(props.collegeId, {
      staff_id: form.staffId,
      administrative_class_id: form.classId,
      duty: form.duty,
      effective_from: form.effectiveFrom,
      effective_to: form.effectiveTo || null,
      reason: (form.reason || '').trim() || null
    })
    createOpen.value = false
    ElMessage.success('已建立班级责任任命')
    void load()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '保存失败'
  } finally { createBusy.value = false }
}

const endOpen = ref(false)
const endRow = ref<ResponsibilityRow | null>(null)
const endForm = ref({ effectiveTo: today(), reason: '' })
const endError = ref('')
const endBusy = ref(false)
function startEnd(row: ResponsibilityRow) {
  endRow.value = row
  endForm.value = { effectiveTo: today(), reason: '' }
  endError.value = ''
  endOpen.value = true
}
async function submitEnd() {
  const row = endRow.value
  if (!row) return
  if (!endForm.value.effectiveTo) { endError.value = '请选择结束日期（结束日当天不再负责该班）'; return }
  endBusy.value = true
  endError.value = ''
  try {
    await endResponsibility(props.collegeId, row.id, {
      effective_to: endForm.value.effectiveTo,
      lock_version: row.lock_version,
      reason: (endForm.value.reason || '').trim() || null
    })
    endOpen.value = false
    ElMessage.success('任职已结束')
    void load()
  } catch (e) {
    endError.value = e instanceof Error ? e.message : '结束失败'
  } finally { endBusy.value = false }
}

const handoverOpen = ref(false)
const handoverRow = ref<ResponsibilityRow | null>(null)
const handoverForm = ref({ successorId: '', effectiveOn: today(), reason: '' })
const handoverError = ref('')
const handoverBusy = ref(false)
function startHandover(row: ResponsibilityRow) {
  handoverRow.value = row
  handoverForm.value = { successorId: '', effectiveOn: today(), reason: '' }
  handoverError.value = ''
  handoverOpen.value = true
  void loadStaffForHandover()
}
async function loadStaffForHandover() {
  try {
    const page = await listStaff(props.collegeId, { keyword: '', page_size: 200 })
    staffOptions.value = page.items
    for (const staff of page.items) staffLabelMap.value[staff.id] = `${staff.staff_no} ${staff.name}`
  } catch { staffOptions.value = [] }
}
async function submitHandover() {
  const row = handoverRow.value
  if (!row) return
  if (!handoverForm.value.successorId || !handoverForm.value.effectiveOn) {
    handoverError.value = '请明确选择接班教职工并填写交接生效日；交接日即旧任命结束日。'
    return
  }
  handoverBusy.value = true
  handoverError.value = ''
  try {
    await responsibilityHandover(props.collegeId, row.id, {
      successor_staff_id: handoverForm.value.successorId,
      effective_on: handoverForm.value.effectiveOn,
      lock_version: row.lock_version,
      reason: (handoverForm.value.reason || '').trim() || null
    })
    handoverOpen.value = false
    ElMessage.success('交接完成：旧任命同时结束，新任命同日起生效')
    void load()
  } catch (e) {
    handoverError.value = e instanceof Error ? e.message : '交接失败'
  } finally { handoverBusy.value = false }
}
</script>

<template>
  <section aria-label="班级负责人">
    <el-alert title="班主任与责任区辅导员按任职区间生效：同班同职责同一时段只有一位主要负责人；交接在同一事务内完成。姓名相同不会被自动授权。" type="info" :closable="false" />
    <div class="filters">
      <el-select v-model="staffFilter" filterable clearable placeholder="按教师筛选" style="max-width: 240px">
        <el-option v-for="staff in staffOptions" :key="staff.id" :value="staff.id" :label="`${staff.staff_no} ${staff.name}`" />
      </el-select>
      <el-button :loading="busy" @click="void load()">刷新</el-button>
      <el-button type="primary" :disabled="busy || !!error" @click="openCreate">建立责任任命</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="rows || []" v-loading="busy" empty-text="当前学院暂无班级责任任命记录">
      <el-table-column label="教职工" min-width="160"><template #default="{ row }">{{ staffLabel(row.staff_id) }}</template></el-table-column>
      <el-table-column label="行政班" min-width="180"><template #default="{ row }">{{ classLabel(row.administrative_class_id) }}</template></el-table-column>
      <el-table-column label="职责" min-width="100"><template #default="{ row }">{{ dutyLabel(row.duty) }}</template></el-table-column>
      <el-table-column prop="effective_from" label="生效日" min-width="110" />
      <el-table-column label="截止日" min-width="110"><template #default="{ row }">{{ row.effective_to || '长期' }}</template></el-table-column>
      <el-table-column label="操作" min-width="150" fixed="right">
        <template #default="{ row }">
          <el-button link @click="startEnd(row)">结束</el-button>
          <el-button v-if="!row.effective_to" link @click="startHandover(row)">交接</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createOpen" title="建立班级责任任命" width="560px" :close-on-click-modal="false">
      <el-form label-width="112px">
        <el-form-item label="教职工" required>
          <el-select v-model="createForm.staffId" filterable placeholder="选择本院教职工档案" style="width: 100%">
            <el-option v-for="staff in staffOptions.filter(item => item.status === 'ACTIVE')" :key="staff.id" :value="staff.id" :label="`${staff.staff_no} ${staff.name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="行政班" required>
          <el-select v-model="createForm.classId" filterable remote :remote-method="loadClassOptions" :loading="classLoading" placeholder="选择本院行政班" style="width: 100%">
            <el-option v-for="row in classOptions" :key="row.id" :value="row.id" :label="String(row.class_name || row.class_code || row.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="职责" required>
          <el-select v-model="createForm.duty" placeholder="选择职责" style="width: 100%">
            <el-option value="HEAD_TEACHER" label="班主任" />
            <el-option value="COUNSELOR" label="辅导员" />
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

    <el-dialog v-model="endOpen" title="结束责任任命" width="480px" :close-on-click-modal="false">
      <p v-if="endRow"><strong>{{ staffLabel(endRow.staff_id) }}</strong> 从结束日起不再负责该班。</p>
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

    <el-dialog v-model="handoverOpen" title="责任交接" width="520px" :close-on-click-modal="false">
      <p v-if="handoverRow">{{ dutyLabel(handoverRow.duty) }}「{{ classLabel(handoverRow.administrative_class_id) }}」由 <strong>{{ staffLabel(handoverRow.staff_id) }}</strong> 移交新责任人；交接在同一事务内结束旧任命并建立新任命。</p>
      <el-form label-width="112px">
        <el-form-item label="接班人" required>
          <el-select v-model="handoverForm.successorId" filterable placeholder="选择接班教职工档案（不自动预选）" style="width: 100%">
            <el-option v-for="staff in staffOptions.filter(item => item.status === 'ACTIVE' && item.id !== handoverRow?.staff_id)" :key="staff.id" :value="staff.id" :label="`${staff.staff_no} ${staff.name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="交接日期" required><el-date-picker v-model="handoverForm.effectiveOn" type="date" value-format="YYYY-MM-DD" :clearable="false" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="handoverForm.reason" type="textarea" :rows="2" maxlength="512" /></el-form-item>
      </el-form>
      <el-alert v-if="handoverError" :title="handoverError" type="error" :closable="false" />
      <template #footer>
        <el-button @click="handoverOpen = false">取消</el-button>
        <el-button type="primary" :loading="handoverBusy" @click="submitHandover">确认交接</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }
</style>
