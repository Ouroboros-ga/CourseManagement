<script setup lang="ts">
import type { InspectionTaskItem } from '../api/tasks'
import TaskStatusTag from './TaskStatusTag.vue'

defineProps<{
  visible: boolean
  task: InspectionTaskItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'reassign', task: InspectionTaskItem): void
}>()

const close = () => {
  emit('update:visible', false)
}
</script>

<template>
  <el-drawer
    :model-value="visible"
    title="查课任务详情"
    direction="rtl"
    size="480px"
    destroy-on-close
    @close="close"
  >
    <div v-if="task" class="drawer-body">
      <!-- 任务概览 -->
      <section class="d-section">
        <div class="d-id font-mono">任务 ID：{{ task.id }} · lock_version: {{ task.lock_version }}</div>
        <div class="d-course font-serif">{{ task.course_name || '未命名课程' }}</div>
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
            <p class="d-value">第 {{ task.start_period }}-{{ task.end_period }} 节</p>
          </div>
          <div>
            <span class="d-label">上课教室</span>
            <p class="d-value">{{ task.classroom_name || '未指定教室' }}</p>
          </div>
          <div>
            <span class="d-label">教学班级</span>
            <p class="d-value">{{ task.teaching_class_name || '未指定教学班' }}</p>
          </div>
        </div>
      </section>

      <!-- 受派志愿者 -->
      <section class="d-section">
        <div class="d-heading-row">
          <h4 class="d-heading">当前受派志愿者</h4>
          <button class="btn btn-ghost btn-sm" @click="emit('reassign', task)">调整 / 改派</button>
        </div>
        <div v-if="task.assigned_volunteer_id" class="d-volunteer">
          <div>
            <div class="d-value">{{ task.assigned_volunteer_name || '志愿者' }}</div>
            <div class="d-label font-mono">用户 ID：{{ task.assigned_volunteer_id }}</div>
          </div>
          <span class="tag tag-green">有效受派</span>
        </div>
        <div v-else class="d-empty">
          尚未分配志愿者。可通过自动排班或手动指定分配。
        </div>
      </section>

      <!-- 截止考核事实 -->
      <section class="d-section">
        <h4 class="d-heading">截止与考核审计事实</h4>
        <p class="d-fact">
          截止考核结果：<strong class="font-mono">{{ task.deadline_assessment || '未截止 / 正常完成' }}</strong>
        </p>
        <p class="d-note">
          根据业务规则：允许截止后补交，但截止时「逾期未执行」事实不可被补交或更正覆盖。
        </p>
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
.drawer-body { display: flex; flex-direction: column; gap: 28px; }

.d-section {
  padding-bottom: 24px;
  border-bottom: 1px solid var(--line);
}
.d-section:last-child { border-bottom: none; padding-bottom: 0; }

.d-id { font-size: 11px; color: var(--ink-mute); margin-bottom: 8px; }
.d-course { font-size: 20px; font-weight: 700; margin-bottom: 12px; }

.d-heading {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 16px;
}
.d-heading-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.d-heading-row .d-heading { margin-bottom: 0; }

.d-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 12px;
}
.d-label { font-size: 11px; color: var(--ink-mute); display: block; margin-bottom: 4px; }
.d-value { font-size: 13px; font-weight: 600; color: var(--ink); }

.d-volunteer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  background: var(--green-soft);
  border-left: 2px solid var(--green);
}
.d-empty {
  padding: 14px 16px;
  background: var(--amber-soft);
  border-left: 2px solid var(--amber);
  font-size: 12px;
  color: var(--amber);
}

.d-fact { font-size: 12px; color: var(--ink-soft); margin-bottom: 8px; }
.d-fact strong { color: var(--ink); }
.d-note { font-size: 11px; color: var(--ink-mute); line-height: 1.7; }

.d-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
