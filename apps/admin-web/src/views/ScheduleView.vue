<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listTasks,
  queryCourseOccurrences,
  generateExactTasks,
  triggerAutoAssign,
  type CourseOccurrence,
  type InspectionTaskItem
} from '../api/tasks'
import { listTeachingClasses, type TeachingClassItem } from '../api/academic'
import TaskStatusTag from '../components/TaskStatusTag.vue'

const sessionStore = useSessionStore()

const loading = ref(false)
const dispatchLoading = ref(false)
const teachingClasses = ref<TeachingClassItem[]>([])
const selectedClassId = ref<string>('')

// 课次列表 (从后端加载)
const occurrences = ref<CourseOccurrence[]>([])
const weekTasks = ref<InspectionTaskItem[]>([])
const selectedKeys = ref<string[]>([])
const selectionRevision = ref<string>('')
const selectionScope = ref<Record<string, unknown>>({})

const hasData = computed(() => occurrences.value.length > 0 || weekTasks.value.length > 0)

async function loadData() {
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  selectedKeys.value = []
  try {
    // 1. 加载本周已有的查课任务
    const taskRes = await listTasks({
      semester_id: sessionStore.currentSemesterId,
      week_no: sessionStore.currentWeekNo,
      page_size: 50
    })
    weekTasks.value = taskRes.items || []

    // 2. 加载当前学期的教学班
    if (teachingClasses.value.length === 0) {
      const clsRes = await listTeachingClasses(sessionStore.currentSemesterId)
      teachingClasses.value = clsRes.items || []
    }

    // 3. 查询当周排课课次 (如果有配置日期范围和教学班)
    if (sessionStore.weekDateRange.start && sessionStore.weekDateRange.end && teachingClasses.value.length > 0) {
      const classIds = selectedClassId.value 
        ? [Number(selectedClassId.value)] 
        : teachingClasses.value.map(c => Number(c.id)).slice(0, 50)

      try {
        const occRes = await queryCourseOccurrences({
          semester_id: sessionStore.currentSemesterId,
          date_from: sessionStore.weekDateRange.start,
          date_to: sessionStore.weekDateRange.end,
          teaching_class_ids: classIds
        })
        occurrences.value = occRes.items || []
        selectionRevision.value = occRes.selection_revision
        selectionScope.value = occRes.selection_scope || {}
      } catch {
        occurrences.value = []
      }
    } else {
      occurrences.value = []
    }
  } catch (err: unknown) {
    console.error('加载排班数据失败:', err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [sessionStore.currentSemesterId, sessionStore.currentWeekNo, selectedClassId.value],
  () => {
    loadData()
  }
)

onMounted(() => {
  loadData()
})

function toggleSelect(key: string) {
  const index = selectedKeys.value.indexOf(key)
  if (index > -1) {
    selectedKeys.value.splice(index, 1)
  } else {
    selectedKeys.value.push(key)
  }
}

async function triggerDispatch() {
  if (selectedKeys.value.length === 0) {
    ElMessage.warning('请勾选需要下发的课次')
    return
  }

  dispatchLoading.value = true
  try {
    const selectedItems = occurrences.value.filter(o => 
      selectedKeys.value.includes(`${o.course_schedule_id}_${o.inspection_date}`)
    )

    // 调用后端生成查课任务接口
    const genRes = await generateExactTasks({
      semester_id: sessionStore.currentSemesterId,
      inspection_type: 'COURSE',
      selection_revision: selectionRevision.value || 'rev_1',
      selection_scope: selectionScope.value,
      occurrences: selectedItems.map(o => ({
        course_schedule_id: o.course_schedule_id,
        inspection_date: o.inspection_date
      }))
    })

    // 如果生成了新任务，尝试触发自动排班求解器
    let assignMsg = ''
    if (genRes.assignable_task_ids && genRes.assignable_task_ids.length > 0) {
      try {
        const assignRes = await triggerAutoAssign({
          task_ids: genRes.assignable_task_ids
        })
        assignMsg = `<br/>3. <b>求解器自动排班</b>：已排定 ${assignRes.assigned_count} 个任务，待人工处理 ${assignRes.unassigned_count} 个。`
      } catch {
        assignMsg = '<br/>3. <b>自动排班</b>：暂无可用志愿者或无需自动分配。'
      }
    }

    ElMessageBox.alert(
      `下发完成！<br/><br/>
      1. <b>任务生成</b>：成功生成 ${genRes.created} 个新查课任务<br/>
      2. <b>已有任务</b>：跳过 ${genRes.existed} 个已存在的重复任务
      ${assignMsg}`,
      '下发与排班完成',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '确定'
      }
    )

    // 重新加载数据
    await loadData()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '下发失败'
    ElMessage.error(msg)
  } finally {
    dispatchLoading.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>{{ sessionStore.currentSemesterName }}</span>
        <em>●</em>
        <span>第 {{ sessionStore.currentWeekNo }} 周</span>
        <em>●</em>
        <span>{{ sessionStore.weekDateRange.text }}</span>
      </div>
      <h1>课次勾选与下发</h1>
      <p class="sub">
        按当前自然周调取课程课次，真实原子下发至后端数据库并触发排班求解器分配志愿者。已下发任务可直接在任务列表中查看。
      </p>
      <div class="head-actions">
        <span class="sel-info">
          已选 <strong class="font-mono">{{ selectedKeys.length }}</strong> 个待下发课次
        </span>
        <button class="btn btn-dark" :disabled="dispatchLoading || selectedKeys.length === 0" @click="triggerDispatch">
          {{ dispatchLoading ? '正在下发…' : '⚡ 确认下发并排班' }}
        </button>
      </div>
    </header>

    <div class="tbl-wrap">
      <!-- 筛选条 -->
      <div class="filter-bar">
        <div class="fgroup">
          <label>当前周次日期范围</label>
          <span class="cell-mono font-bold">{{ sessionStore.weekDateRange.start }} 至 {{ sessionStore.weekDateRange.end }}</span>
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>教学班过滤</label>
          <select v-model="selectedClassId" class="input">
            <option value="">全部教学班（{{ teachingClasses.length }} 个）</option>
            <option v-for="c in teachingClasses" :key="c.id" :value="c.id">
              {{ c.class_name }}
            </option>
          </select>
        </div>
        <div class="fsep"></div>
        <button class="btn btn-ghost btn-sm" @click="loadData">⟳ 刷新数据</button>
      </div>

      <!-- 课次列表 (待下发课次) -->
      <div v-if="occurrences.length > 0">
        <div class="section-title">本周待下发排课课次</div>
        <table class="tbl">
          <thead>
            <tr>
              <th style="width: 48px"></th>
              <th>课次时间</th>
              <th>课程信息</th>
              <th>教学班与规模</th>
              <th>上课地点</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in occurrences"
              :key="`${item.course_schedule_id}_${item.inspection_date}`"
              :class="{ 'row-disabled': !item.selectable }"
            >
              <td>
                <input
                  type="checkbox"
                  class="chk"
                  :checked="selectedKeys.includes(`${item.course_schedule_id}_${item.inspection_date}`)"
                  :disabled="!item.selectable"
                  @change="toggleSelect(`${item.course_schedule_id}_${item.inspection_date}`)"
                />
              </td>
              <td>
                <div class="cell-main">{{ item.inspection_date }}</div>
                <div class="cell-sub cell-mono">第 {{ item.start_period }}-{{ item.end_period }} 节</div>
              </td>
              <td>
                <div class="cell-main">
                  <span v-if="item.course_code" class="cell-mono code">{{ item.course_code }}</span>
                  {{ item.course_name }}
                </div>
                <div class="cell-sub">{{ item.teacher_name ? '任课教师：' + item.teacher_name : '未填任课教师' }}</div>
              </td>
              <td>
                <div class="cell-main">{{ item.teaching_class_name }}</div>
                <div class="cell-sub">应到 {{ item.student_count }} 人</div>
              </td>
              <td>
                <div class="cell-main">{{ item.classroom_name || '未指定教室' }}</div>
              </td>
              <td>
                <span v-if="item.existing_task_id" class="tag tag-green">已下发任务</span>
                <span v-else-if="!item.selectable" class="tag tag-amber" :title="item.disabled_reason || ''">
                  {{ item.disabled_reason || '不可下发' }}
                </span>
                <span v-else class="tag tag-gray">待下发</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 本周已生成的任务清单 -->
      <div v-if="weekTasks.length > 0" style="margin-top: 24px;">
        <div class="section-title">本周数据库中已有查课任务（共 {{ weekTasks.length }} 条）</div>
        <table class="tbl">
          <thead>
            <tr>
              <th>任务编号</th>
              <th>查课日期</th>
              <th>节次</th>
              <th>课程</th>
              <th>教学班</th>
              <th>教室</th>
              <th>任务状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in weekTasks" :key="t.id">
              <td class="cell-mono code">#{{ t.id }}</td>
              <td>{{ t.inspection_date }}</td>
              <td class="cell-mono">第 {{ t.start_period }}-{{ t.end_period }} 节</td>
              <td>{{ t.course_name_snapshot || '—' }}</td>
              <td>{{ t.class_name_snapshot || '—' }}</td>
              <td>{{ t.classroom_snapshot || '—' }}</td>
              <td>
                <TaskStatusTag :status="t.status" :deadline-assessment="t.deadline_assessment" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && !hasData" class="empty-box">
        <div class="empty-icon">📂</div>
        <div class="empty-text">当前周次（第 {{ sessionStore.currentWeekNo }} 周）暂无可下发课次及已有任务</div>
        <div class="empty-sub">您可以切换顶栏周次或学期查看其他教学周</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sel-info { font-size: 13px; color: var(--ink-mute); }
.sel-info strong { color: var(--ink); font-size: 15px; }

.section-title {
  padding: 14px 24px 6px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  background: var(--paper);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
  font-size: 12px;
  flex-wrap: wrap;
}
.fgroup { display: flex; align-items: center; gap: 8px; }
.fgroup label { color: var(--ink-mute); font-weight: 500; }
.fsep { width: 1px; height: 16px; background: var(--line-strong); }

.code { color: var(--blue); font-weight: 600; }
.row-disabled { opacity: 0.45; }

.empty-box {
  padding: 60px 20px;
  text-align: center;
  color: var(--ink-mute);
}
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 14px; font-weight: 600; color: var(--ink-soft); margin-bottom: 4px; }
.empty-sub { font-size: 12px; }
</style>
