<script setup lang="ts">
import { ref, watch } from 'vue'
import type { InspectionTaskItem } from '../api/tasks'
import { getTaskRoster, type RosterStudentItem } from '../api/submissions'
import TaskStatusTag from './TaskStatusTag.vue'
import { formatPeriodText } from '../utils/period'

interface Props {
  visible: boolean
  task: InspectionTaskItem | null
}
const props = defineProps<Props>()

const emit = defineEmits<{
  'update:visible': [val: boolean]
  reassign: [task: InspectionTaskItem]
}>()

const loadingRoster = ref(false)
const students = ref<RosterStudentItem[]>([])
const rosterVersion = ref<number>(1)
const totalStudents = ref<number>(0)

watch(
  () => props.task,
  async (newTask) => {
    if (!newTask) {
      students.value = []
      return
    }
    loadingRoster.value = true
    try {
      const res = await getTaskRoster(newTask.id)
      students.value = res.students || []
      rosterVersion.value = res.roster_version || 1
      totalStudents.value = res.total_students || students.value.length
    } catch {
      students.value = []
      totalStudents.value = 0
    } finally {
      loadingRoster.value = false
    }
  },
  { immediate: true }
)

const close = () => {
  emit('update:visible', false)
}
</script>

<template>
  <el-drawer
    :model-value="visible"
    title="查课任务详情与点名册"
    direction="rtl"
    size="520px"
    destroy-on-close
    @close="close"
  >
    <div v-if="task" class="drawer-body">
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
            <p class="d-value">{{ formatPeriodText(task.start_period, task.end_period, true) }}</p>
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

      <!-- 任务点名名单 -->
      <section class="d-section">
        <div class="d-heading-row">
          <h4 class="d-heading">任务点名学生名单（应到 {{ totalStudents }} 人 · 名单版本 v{{ rosterVersion }}）</h4>
        </div>
        <div v-loading="loadingRoster">
          <div v-if="students.length > 0" class="roster-table-wrap">
            <table class="tbl tbl-compact">
              <thead>
                <tr>
                  <th>学号</th>
                  <th>姓名</th>
                  <th>行政班</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="stu in students" :key="stu.student_id">
                  <td class="cell-mono">{{ stu.student_no }}</td>
                  <td class="font-bold">{{ stu.name }}</td>
                  <td class="cell-sub">{{ stu.administrative_class_name || '—' }}</td>
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

    <template #footer>
      <div class="d-footer">
        <button class="btn" @click="close">关闭</button>
        <button v-if="task" class="btn btn-dark" @click="emit('reassign', task)">人工指派 / 改派</button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-body { display: flex; flex-direction: column; gap: 24px; }

.d-section {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}
.d-section:last-child { border-bottom: none; padding-bottom: 0; }

.d-id { font-size: 11px; color: var(--ink-mute); margin-bottom: 8px; }
.d-course { font-size: 18px; font-weight: 700; margin-bottom: 10px; }

.d-heading {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 14px;
}
.d-heading-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.d-heading-row .d-heading { margin-bottom: 0; }

.d-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 12px;
}
.d-label { font-size: 11px; color: var(--ink-mute); display: block; margin-bottom: 4px; }
.d-value { font-size: 13px; font-weight: 600; color: var(--ink); }

.d-volunteer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  background: var(--green-soft);
  border-left: 2px solid var(--green);
}
.d-empty {
  padding: 12px 14px;
  background: var(--amber-soft);
  border-left: 2px solid var(--amber);
  font-size: 12px;
  color: var(--amber);
}

.roster-table-wrap {
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid var(--line);
}
.tbl-compact th, .tbl-compact td { padding: 6px 12px; font-size: 12px; }

.d-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
