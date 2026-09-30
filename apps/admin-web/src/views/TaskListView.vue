<script setup lang="ts">
import { ref, reactive } from 'vue'
import TaskStatusTag from '../components/TaskStatusTag.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import type { InspectionTaskItem } from '../api/tasks'
import { ElMessage } from 'element-plus'

const drawerVisible = ref(false)
const activeTask = ref<InspectionTaskItem | null>(null)

const tasks = reactive<InspectionTaskItem[]>([
  {
    id: 'TASK-042',
    task_key: 'key-042',
    semester_id: '1',
    inspection_type: 'COURSE',
    inspection_date: '2026-09-28',
    start_period: 1,
    end_period: 2,
    status: 'REVIEWED',
    deadline_assessment: null,
    course_name: '数据结构与算法',
    course_code: 'CS201',
    classroom_name: '13号楼 302教室',
    teaching_class_name: '计科2301-2302合班 (68人)',
    assigned_volunteer_id: 'vol-001',
    assigned_volunteer_name: '刘晨 (2023001)',
    lock_version: 2,
    created_at: '2026-09-28 07:30:00'
  },
  {
    id: 'TASK-045',
    task_key: 'key-045',
    semester_id: '1',
    inspection_type: 'COURSE',
    inspection_date: '2026-09-28',
    start_period: 3,
    end_period: 4,
    status: 'NOT_STARTED',
    deadline_assessment: null,
    course_name: '操作系统原理',
    course_code: 'CS204',
    classroom_name: '14号楼 205教室',
    teaching_class_name: '软工2401班 (34人)',
    assigned_volunteer_id: null,
    assigned_volunteer_name: null,
    lock_version: 0,
    created_at: '2026-09-28 07:30:00'
  },
  {
    id: 'TASK-039',
    task_key: 'key-039',
    semester_id: '1',
    inspection_type: 'COURSE',
    inspection_date: '2026-09-27',
    start_period: 7,
    end_period: 8,
    status: 'REVIEWED',
    deadline_assessment: 'OVERDUE_UNEXECUTED',
    course_name: '软件工程导论',
    course_code: 'SE101',
    classroom_name: '15号楼 401教室',
    teaching_class_name: '软工2301班 (35人)',
    assigned_volunteer_id: 'vol-045',
    assigned_volunteer_name: '周亮 (2023045)',
    lock_version: 1,
    created_at: '2026-09-27 12:00:00'
  }
])

function openTaskDetail(task: InspectionTaskItem) {
  activeTask.value = task
  drawerVisible.value = true
}

function handleReassign(task: InspectionTaskItem) {
  ElMessage.info(`打开人工改派对话框: 任务 ${task.id}`)
}
</script>

<template>
  <div>
    <header class="page-head">
      <div class="crumb">
        <span>TASKS</span><em>●</em><span>第 4 周</span><em>●</em><span>09月28日 — 10月04日</span>
      </div>
      <h1>查课任务与排班</h1>
      <p class="sub">
        本周全部查课任务总览，保留任务唯一分配与失效历史。未分配任务附带标准原因码，支持人工指定。
      </p>
    </header>

    <!-- 统计分栏 -->
    <div class="stat-row">
      <div class="stat-cell">
        <div class="label">本周计划总任务</div>
        <div class="value">115</div>
        <div class="note">覆盖 6 个专业年级</div>
      </div>
      <div class="stat-cell">
        <div class="label">自动排班成功</div>
        <div class="value" style="color: var(--green)">75</div>
        <div class="note"><span class="trend trend-up">65.2%</span> 自动分配率</div>
      </div>
      <div class="stat-cell">
        <div class="label">待人工微调</div>
        <div class="value" style="color: var(--amber)">40</div>
        <div class="note">已附带标准原因码</div>
      </div>
      <div class="stat-cell">
        <div class="label">已审核完成</div>
        <div class="value" style="color: var(--blue)">18</div>
        <div class="note"><span class="trend trend-up">97.4%</span> 平均到课率</div>
      </div>
    </div>

    <!-- 任务表 -->
    <div class="tbl-wrap">
      <div class="tbl-head">
        <div>
          <h3>任务总览</h3>
          <div class="meta">按检查日期与节次排序</div>
        </div>
        <div class="tbl-tools">
          <input type="text" class="input" style="width: 220px" placeholder="搜索课程 / 志愿者 / 教室…" />
          <button class="btn btn-sm">筛选</button>
        </div>
      </div>

      <table class="tbl">
        <thead>
          <tr>
            <th>任务 ID</th>
            <th>时间与地点</th>
            <th>课程与教学班</th>
            <th>受派志愿者</th>
            <th>状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td class="cell-mono tid">{{ task.id }}</td>
            <td>
              <div class="cell-main">{{ task.inspection_date }} 第 {{ task.start_period }}-{{ task.end_period }} 节</div>
              <div class="cell-sub">{{ task.classroom_name }}</div>
            </td>
            <td>
              <div class="cell-main">{{ task.course_name }}</div>
              <div class="cell-sub">{{ task.teaching_class_name }}</div>
            </td>
            <td>
              <template v-if="task.assigned_volunteer_name">
                <div class="cell-main">{{ task.assigned_volunteer_name }}</div>
                <div class="cell-sub cell-mono">{{ task.assigned_volunteer_id }}</div>
              </template>
              <template v-else>
                <div class="unassigned">未分配（可指定）</div>
                <div class="cell-sub cell-mono">SELF_CLASS_AVOID</div>
              </template>
            </td>
            <td>
              <TaskStatusTag :status="task.status" :deadline-assessment="task.deadline_assessment" />
            </td>
            <td style="text-align: right">
              <button v-if="!task.assigned_volunteer_id" class="btn btn-sm" @click="handleReassign(task)">人工改派</button>
              <button v-else class="btn btn-ghost btn-sm" @click="openTaskDetail(task)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <TaskDrawer
      v-model:visible="drawerVisible"
      :task="activeTask"
      @reassign="handleReassign"
    />
  </div>
</template>

<style scoped>
.stat-row { margin-bottom: 40px; }
.tid { font-weight: 600; color: var(--blue); }
.unassigned { color: var(--amber); font-weight: 600; }
</style>
