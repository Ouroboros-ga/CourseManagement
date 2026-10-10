<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { InspectionTaskItem } from '../api/tasks'
import { getTaskRoster, listManagementSubmissions, type RosterStudentItem, type ManagementSubmissionItem } from '../api/submissions'
import { listAttendance, correctAttendanceRecord, type AttendanceRecord, type AttendanceType } from '../api/attendance'
import { useSessionStore } from '../stores/session'
import TaskStatusTag from './TaskStatusTag.vue'
import AppIcon from './AppIcon.vue'
import { formatPeriodText } from '../utils/period'
import { ElMessage } from 'element-plus'

interface Props {
  visible: boolean
  task: InspectionTaskItem | null
}
const props = defineProps<Props>()

const emit = defineEmits<{
  'update:visible': [val: boolean]
  reassign: [task: InspectionTaskItem]
  delete: [task: InspectionTaskItem]
  corrected: []
}>()

const sessionStore = useSessionStore()

const loadingData = ref(false)
const students = ref<RosterStudentItem[]>([])
const rosterVersion = ref<number>(1)
const totalStudents = ref<number>(0)

const submission = ref<ManagementSubmissionItem | null>(null)
const attendanceRecords = ref<AttendanceRecord[]>([])

// 管理端二次更正弹窗
const correctDialogVisible = ref(false)
const correctingRecord = ref<AttendanceRecord | null>(null)
const correctTargetType = ref<AttendanceType>('NORMAL')
const correctReason = ref('')
const correctSubmitting = ref(false)

const canCorrectAttendance = computed(() => {
  return (
    sessionStore.hasPermission('attendance.correct') ||
    sessionStore.hasAnyRole('SUPER_ADMIN', 'TEACHER_ADMIN', 'STUDENT_AFFAIRS_MANAGER')
  )
})

// 考勤按类型统计
const attendanceStats = computed(() => {
  const records = attendanceRecords.value
  if (!records.length) return null
  const total = records.length
  const normal = records.filter(r => r.effective_type === 'NORMAL').length
  const leave = records.filter(r => r.effective_type === 'LEAVE').length
  const late = records.filter(r => r.effective_type === 'LATE').length
  const absent = records.filter(r => r.effective_type === 'ABSENT').length
  const rate = total > 0 ? ((normal / total) * 100).toFixed(1) + '%' : '—'
  return { total, normal, leave, late, absent, rate }
})

// 综合名单视图：关联点名册与实际考勤状态
interface EnrichedRosterItem {
  student_id: string
  student_no: string
  name: string
  class_name: string
  effective_type?: AttendanceType
  attendance_record_id?: string
  current_version?: number
}

const enrichedStudents = computed<EnrichedRosterItem[]>(() => {
  const attMap = new Map<string, AttendanceRecord>()
  for (const r of attendanceRecords.value) {
    attMap.set(String(r.student_id), r)
  }

  return students.value.map(stu => {
    const att = attMap.get(String(stu.student_id))
    return {
      student_id: String(stu.student_id),
      student_no: stu.student_no,
      name: stu.name,
      class_name: stu.class_name_snapshot || stu.administrative_class_name || '—',
      effective_type: att?.effective_type,
      attendance_record_id: att?.id,
      current_version: att?.current_version
    }
  })
})

async function loadTaskDetails(newTask: InspectionTaskItem) {
  loadingData.value = true
  try {
    // 1. 点名册
    const rosterRes = await getTaskRoster(newTask.id)
    students.value = rosterRes.items || rosterRes.students || []
    rosterVersion.value = rosterRes.roster_version || 1
    totalStudents.value = rosterRes.total_students || students.value.length

    // 2. 查课提交信息（若已提交）
    try {
      const subRes = await listManagementSubmissions({
        task_id: String(newTask.id),
        page_size: 1
      })
      submission.value = subRes.items && subRes.items.length > 0 ? subRes.items[0] : null
    } catch {
      submission.value = null
    }

    // 3. 实际考勤认定（若已生成考勤）
    try {
      const attRes = await listAttendance({
        task_id: Number(newTask.id),
        page_size: 200
      })
      attendanceRecords.value = attRes.items || []
    } catch {
      attendanceRecords.value = []
    }
  } catch {
    students.value = []
    attendanceRecords.value = []
    submission.value = null
  } finally {
    loadingData.value = false
  }
}

watch(
  () => props.task,
  (newTask) => {
    if (newTask && props.visible) {
      loadTaskDetails(newTask)
    } else {
      students.value = []
      attendanceRecords.value = []
      submission.value = null
    }
  },
  { immediate: true }
)

watch(
  () => props.visible,
  (visible) => {
    if (visible && props.task) {
      loadTaskDetails(props.task)
    }
  }
)

function openCorrectDialog(item: EnrichedRosterItem) {
  if (!item.attendance_record_id || item.current_version === undefined) return
  const record = attendanceRecords.value.find(r => String(r.id) === String(item.attendance_record_id))
  if (!record) return
  correctingRecord.value = record
  correctTargetType.value = record.effective_type || 'NORMAL'
  correctReason.value = '补交假条，辅导员已签批'
  correctDialogVisible.value = true
}

async function handleConfirmCorrect() {
  if (!correctingRecord.value) return
  if (!correctReason.value.trim()) {
    ElMessage.warning('请输入更正理由以留痕审计')
    return
  }
  correctSubmitting.value = true
  try {
    await correctAttendanceRecord(correctingRecord.value.id, {
      attendance_type: correctTargetType.value,
      reason: correctReason.value.trim(),
      current_version: correctingRecord.value.current_version
    })
    ElMessage.success(`已成功更正为「${formatType(correctTargetType.value)}」并完成审计留痕！`)
    correctDialogVisible.value = false
    emit('corrected')
    if (props.task) {
      await loadTaskDetails(props.task)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '更正考勤失败')
  } finally {
    correctSubmitting.value = false
  }
}

function formatType(t?: AttendanceType): string {
  switch (t) {
    case 'NORMAL': return '正常出勤'
    case 'LEAVE': return '请假'
    case 'LATE': return '迟到'
    case 'ABSENT': return '旷课'
    default: return '未定'
  }
}

function formatTypeTag(t?: AttendanceType): { label: string; cls: string } {
  switch (t) {
    case 'NORMAL': return { label: '正常', cls: 'tag-green' }
    case 'LEAVE': return { label: '请假', cls: 'tag-amber' }
    case 'LATE': return { label: '迟到', cls: 'tag-amber' }
    case 'ABSENT': return { label: '旷课', cls: 'tag-red' }
    default: return { label: '待考勤', cls: 'tag-gray' }
  }
}

const close = () => {
  emit('update:visible', false)
}
</script>

<template>
  <el-drawer
    :model-value="visible"
    title="查课任务详情与点名册"
    direction="rtl"
    size="600px"
    destroy-on-close
    @close="close"
  >
    <div v-if="task" v-loading="loadingData" class="drawer-body">
      <!-- 任务概览 -->
      <section class="d-section">
        <div class="d-id font-mono">任务 ID：#{{ task.id }} · lock_version: {{ task.lock_version }}</div>
        <div class="d-course font-serif">{{ task.course_name_snapshot || task.course_name || '未命名课程' }}</div>
        <TaskStatusTag :status="task.status" :deadline-assessment="task.deadline_assessment" />
      </section>

      <!-- 课次与地点 -->
      <section class="d-section">
        <h4 class="d-heading">课次与地点详情</h4>
        <div class="d-grid">
          <div>
            <span class="d-label">检查日期</span>
            <p class="d-value">{{ task.inspection_date }}</p>
          </div>
          <div>
            <span class="d-label">时间节次</span>
            <p class="d-value">{{ formatPeriodText(task.start_period, task.end_period) }}</p>
          </div>
          <div>
            <span class="d-label">上课教室</span>
            <p class="d-value">{{ task.classroom_snapshot || task.classroom_name || '未指定教室' }}</p>
          </div>
          <div>
            <span class="d-label">教学班级</span>
            <p class="d-value">{{ task.class_name_snapshot || task.teaching_class_name || '未指定教学班' }}</p>
          </div>
        </div>
      </section>

      <!-- 查课执行结果（提交已定稿生效） -->
      <section v-if="attendanceStats || submission" class="d-section">
        <div class="d-heading-row">
          <h4 class="d-heading">查课执行事实（志愿者提交即最终版本）</h4>
          <span class="tag tag-green">已生效定稿</span>
        </div>

        <div v-if="attendanceStats" class="submission-fact-card">
          <div class="fact-stat-grid">
            <div class="fact-cell">
              <span class="fact-label">应到</span>
              <span class="fact-num font-mono">{{ attendanceStats.total }}</span>
            </div>
            <div class="fact-cell">
              <span class="fact-label">实到</span>
              <span class="fact-num font-mono" style="color: var(--green);">{{ attendanceStats.normal }}</span>
            </div>
            <div class="fact-cell">
              <span class="fact-label">旷课</span>
              <span class="fact-num font-mono" :style="{ color: attendanceStats.absent > 0 ? 'var(--accent)' : 'var(--ink)' }">
                {{ attendanceStats.absent }}
              </span>
            </div>
            <div class="fact-cell">
              <span class="fact-label">迟到</span>
              <span class="fact-num font-mono" :style="{ color: attendanceStats.late > 0 ? 'var(--amber)' : 'var(--ink)' }">
                {{ attendanceStats.late }}
              </span>
            </div>
            <div class="fact-cell">
              <span class="fact-label">请假</span>
              <span class="fact-num font-mono" :style="{ color: attendanceStats.leave > 0 ? 'var(--blue)' : 'var(--ink)' }">
                {{ attendanceStats.leave }}
              </span>
            </div>
            <div class="fact-cell">
              <span class="fact-label">出勤率</span>
              <span class="fact-num font-mono font-bold" style="color: var(--green);">{{ attendanceStats.rate }}</span>
            </div>
          </div>

          <div v-if="submission?.note" class="submission-note">
            <span class="note-label">志愿者现场说明：</span>
            <span class="note-text">{{ submission.note }}</span>
          </div>

          <div v-if="submission?.file_ids && submission.file_ids.length > 0" class="submission-photos">
            <div class="photo-title">留痕照片凭证（{{ submission.file_ids.length }} 张）：</div>
            <div class="photo-list">
              <div v-for="fid in submission.file_ids" :key="fid" class="photo-badge font-mono">
                <AppIcon name="camera" :size="12" />
                <span>照片凭证 #{{ fid }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 受派志愿者 -->
      <section class="d-section">
        <div class="d-heading-row">
          <h4 class="d-heading">受派志愿者</h4>
          <button class="btn btn-ghost btn-sm" @click="emit('reassign', task)">调整 / 改派</button>
        </div>
        <div v-if="(task as any).assignment || task.assigned_volunteer_id" class="d-volunteer">
          <div>
            <div class="d-value">
              {{ (task as any).assignment?.volunteer_name || task.assigned_volunteer_name || '志愿者已分配' }}
            </div>
            <div class="d-label font-mono">
              用户 UID：{{ (task as any).assignment?.volunteer_user_id || task.assigned_volunteer_id }}
            </div>
          </div>
          <span class="tag tag-green">有效受派</span>
        </div>
        <div v-else class="d-empty">
          尚未分配志愿者。可通过自动排班或手动指定分配。
        </div>
      </section>

      <!-- 任务点名名单与考勤更正 -->
      <section class="d-section">
        <div class="d-heading-row">
          <h4 class="d-heading">
            学生考勤名单明细（应到 {{ totalStudents }} 人 · 名单版本 v{{ rosterVersion }}）
          </h4>
          <span v-if="canCorrectAttendance && attendanceRecords.length > 0" class="text-xs text-slate-500 font-medium">
            ✦ 允许管理端二次更正
          </span>
        </div>
        <div v-loading="loadingData">
          <div v-if="enrichedStudents.length > 0" class="roster-table-wrap">
            <table class="tbl tbl-compact">
              <thead>
                <tr>
                  <th style="width: 100px;">学号</th>
                  <th style="width: 80px;">姓名</th>
                  <th>行政班</th>
                  <th style="width: 85px; text-align: center;">考勤状态</th>
                  <th v-if="canCorrectAttendance && attendanceRecords.length > 0" style="width: 65px; text-align: right;">更正</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="stu in enrichedStudents" :key="stu.student_id">
                  <td class="cell-mono">{{ stu.student_no }}</td>
                  <td class="font-bold">{{ stu.name }}</td>
                  <td class="cell-sub">{{ stu.class_name }}</td>
                  <td style="text-align: center;">
                    <span
                      class="tag"
                      :class="formatTypeTag(stu.effective_type).cls"
                    >
                      {{ formatTypeTag(stu.effective_type).label }}
                    </span>
                  </td>
                  <td v-if="canCorrectAttendance && attendanceRecords.length > 0" style="text-align: right;">
                    <button
                      v-if="stu.attendance_record_id"
                      class="btn btn-ghost btn-xs text-blue-600 hover:text-blue-800"
                      title="学生负责人及以上权限可再次更正考勤状态"
                      @click="openCorrectDialog(stu)"
                    >
                      更正
                    </button>
                    <span v-else class="text-xs text-slate-300">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="d-empty" style="background: var(--paper-deep); color: var(--ink-mute);">
            点名册学生数据暂未导入或名单为空
          </div>
        </div>
      </section>
    </div>

    <!-- 更正学生考勤状态弹窗 -->
    <el-dialog
      v-model="correctDialogVisible"
      title="更正学生考勤状态（管理端二次修改）"
      width="440px"
      append-to-body
    >
      <div v-if="correctingRecord" class="p-2 space-y-3">
        <div class="p-2.5 rounded bg-blue-50 border border-blue-200 text-blue-900 text-xs leading-relaxed">
          <b>ℹ️ 变更留痕说明：</b>修改后将新增一条版本认定记录（来源为 <code>CORRECTION</code>），并同步刷新本周周报与到课率统计，全过程计入审计日志。
        </div>

        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">目标学生</label>
          <div class="text-sm font-bold text-slate-800">
            {{ correctingRecord.name }} <span class="font-mono text-xs font-normal text-slate-500">({{ correctingRecord.student_no }})</span>
          </div>
        </div>

        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">选择新的考勤状态 *</label>
          <div class="flex gap-2">
            <button
              v-for="t in (['NORMAL', 'LEAVE', 'LATE', 'ABSENT'] as AttendanceType[])"
              :key="t"
              type="button"
              class="btn btn-sm flex-1 text-center justify-center"
              :class="correctTargetType === t ? 'btn-dark font-bold' : 'btn-outline'"
              @click="correctTargetType = t"
            >
              {{ formatType(t) }}
            </button>
          </div>
        </div>

        <div>
          <label class="block text-xs font-bold text-[var(--ink)] mb-1">更正理由 / 审批依据 *</label>
          <select
            class="input w-full mb-1.5"
            @change="(e) => { const v = (e.target as HTMLSelectElement).value; if (v) correctReason = v }"
          >
            <option value="补交假条，辅导员已签批">预设理由：补交假条，辅导员已签批</option>
            <option value="现场误记，核实全勤到课">预设理由：现场误记，核实全勤到课</option>
            <option value="复核漏查，确认为旷课">预设理由：复核漏查，确认为旷课</option>
            <option value="课后核查更正">预设理由：课后核查更正</option>
          </select>
          <input
            v-model="correctReason"
            type="text"
            class="input w-full"
            placeholder="请输入具体更正原因（留痕审计）…"
          />
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <button class="btn btn-ghost" @click="correctDialogVisible = false">取消</button>
          <button
            class="btn btn-dark"
            :disabled="correctSubmitting"
            @click="handleConfirmCorrect"
          >
            {{ correctSubmitting ? '保存中…' : '确认更正' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <template #footer>
      <div class="d-footer" style="display: flex; justify-content: space-between; align-items: center;">
        <button v-if="task" class="btn btn-sm btn-ghost" style="color: #dc2626;" @click="emit('delete', task)">
          删除此任务
        </button>
        <div style="display: flex; gap: 8px;">
          <button class="btn" @click="close">关闭</button>
          <button v-if="task" class="btn btn-dark" @click="emit('reassign', task)">人工指派 / 改派</button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-body { display: flex; flex-direction: column; gap: 20px; }

.d-section {
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.d-section:last-child { border-bottom: none; padding-bottom: 0; }

.d-id { font-size: 11px; color: var(--ink-mute); margin-bottom: 6px; }
.d-course { font-size: 17px; font-weight: 700; margin-bottom: 8px; }

.d-heading {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 12px;
}
.d-heading-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.d-heading-row .d-heading { margin-bottom: 0; }

.d-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.d-label { font-size: 11px; color: var(--ink-mute); display: block; margin-bottom: 3px; }
.d-value { font-size: 13px; font-weight: 600; color: var(--ink); }

.submission-fact-card {
  background: var(--paper-deep);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.fact-stat-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  text-align: center;
}
.fact-cell {
  background: var(--paper);
  padding: 6px 4px;
  border-radius: 4px;
  border: 1px solid var(--line);
}
.fact-label { font-size: 10.5px; color: var(--ink-mute); display: block; margin-bottom: 2px; }
.fact-num { font-size: 13px; font-weight: 600; }

.submission-note {
  font-size: 12px;
  padding: 8px 10px;
  background: var(--paper);
  border-radius: 4px;
  border: 1px solid var(--line);
  color: var(--ink);
}
.note-label { font-weight: 600; color: var(--ink-mute); margin-right: 4px; }
.note-text { color: var(--ink); }

.submission-photos {
  font-size: 12px;
}
.photo-title { font-size: 11px; color: var(--ink-mute); margin-bottom: 6px; font-weight: 600; }
.photo-list { display: flex; flex-wrap: wrap; gap: 6px; }
.photo-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 11px;
  color: var(--ink-soft);
}

.d-volunteer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: var(--green-soft);
  border-left: 2px solid var(--green);
}
.d-empty {
  padding: 10px 12px;
  background: var(--paper-deep);
  border-left: 2px solid var(--line-strong);
  font-size: 12px;
  color: var(--ink-mute);
}

.roster-table-wrap {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--line);
}
.tbl-compact th, .tbl-compact td { padding: 6px 10px; font-size: 12px; }

.btn-xs {
  padding: 2px 6px;
  font-size: 11px;
  border-radius: 3px;
}

.d-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
