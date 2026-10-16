<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useSessionStore } from '../../stores/session'
import {
  listAdministrativeClasses,
  getMasterTimetable,
  type AdministrativeClassItem,
  type MasterTimetableItem
} from '../../api/academic'
import {
  DEFAULT_PERIODS,
  getWeekDateHeaders,
  computeDayLayoutBlocks,
  formatWeeksText,
  MORANDI_PALETTE,
  getCourseColorIndex,
  type DayCourseInput,
  type LayoutBlock,
  type DateHeaderItem
} from '../../utils/studentTimetableLayout'
import AppIcon from '../AppIcon.vue'
import { formatPeriodText } from '../../utils/period'

const props = defineProps<{
  collegeId: string
  semesterId?: string
}>()

const sessionStore = useSessionStore()

// ---- 状态定义 ----
const loadingClasses = ref(false)
const loadingTimetable = ref(false)
const adminClasses = ref<AdministrativeClassItem[]>([])
const selectedClassId = ref<string>('')
const selectedWeek = ref<number>(sessionStore.currentWeekNo || 1)
const showWeekend = ref(false)

// 当学期全量排课（按选定行政班缓存，支持秒切周次）
const semesterCourses = ref<MasterTimetableItem[]>([])

// 课程卡片详情弹窗
const showCourseDetail = ref(false)
const activeCourse = ref<MasterTimetableItem | null>(null)

// 学期总周数与首周一
const totalWeeks = computed(() => sessionStore.totalWeeks || 20)
const currentWeekNo = computed(() => sessionStore.currentWeekNo || 1)
const firstMonday = computed(() => sessionStore.currentSemester?.first_monday || sessionStore.currentSemester?.start_date || '2026-09-14')
const currentSemesterId = computed(() => props.semesterId || sessionStore.currentSemesterId || '')

// 年份文本
const yearText = computed(() => {
  const fm = firstMonday.value
  return fm ? fm.split('-')[0] : '2026'
})

// ---- 加载行政班级列表 ----
async function loadClasses() {
  if (!props.collegeId) return
  loadingClasses.value = true
  try {
    const res = await listAdministrativeClasses({
      college: props.collegeId,
      page_size: 100
    })
    adminClasses.value = res.items || []
    if (adminClasses.value.length > 0 && !selectedClassId.value) {
      selectedClassId.value = String(adminClasses.value[0].id)
    }
  } catch (err) {
    console.error('加载行政班失败:', err)
  } finally {
    loadingClasses.value = false
  }
}

// ---- 加载选定行政班的学期总课表 ----
async function loadClassTimetable() {
  if (!currentSemesterId.value || !selectedClassId.value) {
    semesterCourses.value = []
    return
  }
  loadingTimetable.value = true
  try {
    const res = await getMasterTimetable({
      semester_id: currentSemesterId.value,
      administrative_class_id: selectedClassId.value
    })
    semesterCourses.value = res.items || []

    // 若本班包含周末课程，自动开启周末视图
    const hasWeekendCourse = semesterCourses.value.some(c => c.weekday >= 6)
    if (hasWeekendCourse) {
      showWeekend.value = true
    }
  } catch (err) {
    console.error('加载班级课表失败:', err)
    semesterCourses.value = []
  } finally {
    loadingTimetable.value = false
  }
}

// 监听学院与班级变化
watch(() => props.collegeId, () => {
  selectedClassId.value = ''
  void loadClasses()
}, { immediate: true })

watch([selectedClassId, currentSemesterId], () => {
  void loadClassTimetable()
})

// 当前选中班级对象
const currentAdminClass = computed(() => {
  return adminClasses.value.find(c => String(c.id) === String(selectedClassId.value)) || null
})

// 过滤当周开课的排课条目
const currentWeekCourses = computed(() => {
  const w = selectedWeek.value
  return semesterCourses.value.filter(item => {
    return Array.isArray(item.weeks) && item.weeks.includes(w)
  })
})

// 表头日期（周一至周五，或周一至周日）
const dateHeaders = computed<DateHeaderItem[]>(() => {
  return getWeekDateHeaders(firstMonday.value, selectedWeek.value, showWeekend.value)
})

// 每天对应的布局卡片
interface DayColumnData {
  weekday: number
  name: string
  dateHeader: DateHeaderItem
  blocks: LayoutBlock[]
}

const dayColumns = computed<DayColumnData[]>(() => {
  const headers = dateHeaders.value
  const courses = currentWeekCourses.value

  return headers.map(header => {
    const dayCourseInputs: DayCourseInput[] = courses
      .filter(c => c.weekday === header.weekday)
      .map(c => ({
        id: c.id,
        courseName: c.course_name,
        courseCode: c.course_code,
        teacherName: c.teacher_name,
        classroom: c.classroom,
        startPeriod: c.start_period || 1,
        endPeriod: c.end_period || (c.start_period || 1),
        weeks: c.weeks || [],
        teachingClassName: c.teaching_class_name,
        administrativeClasses: c.administrative_classes,
        enrolledStudentCount: c.enrolled_student_count,
        isPhysicalEducation: c.is_physical_education,
        isInspectable: c.is_inspectable
      }))

    const blocks = computeDayLayoutBlocks(dayCourseInputs, DEFAULT_PERIODS.length)
    return {
      weekday: header.weekday,
      name: header.dayName,
      dateHeader: header,
      blocks
    }
  })
})

// 周次切换操作
function prevWeek() {
  if (selectedWeek.value > 1) {
    selectedWeek.value -= 1
  }
}

function nextWeek() {
  if (selectedWeek.value < totalWeeks.value) {
    selectedWeek.value += 1
  }
}

function backToCurrentWeek() {
  selectedWeek.value = currentWeekNo.value
}

// 打开课程卡片详情
function handleCourseClick(block: LayoutBlock) {
  const raw = semesterCourses.value.find(c => c.id === block.id)
  if (raw) {
    activeCourse.value = raw
  } else {
    activeCourse.value = {
      id: block.id,
      semester_id: currentSemesterId.value,
      course_id: block.id,
      course_code: block.courseCode || '',
      course_name: block.courseName,
      teaching_class_id: '',
      teaching_class_name: block.teachingClassName || '',
      teacher_name: block.teacherName,
      weekday: 1,
      start_period: block.startPeriod,
      end_period: block.endPeriod,
      classroom: block.classroom,
      weeks: block.weeks,
      status: 'ACTIVE',
      enrolled_student_count: block.enrolledStudentCount || 0,
      is_physical_education: !!block.isPhysicalEducation,
      is_inspectable: block.isInspectable !== false,
      administrative_classes: block.administrativeClasses || [],
      teaching_class_code: null,
      head_teacher: null,
      counselor: null,
      administrative_classes_details: []
    }
  }
  showCourseDetail.value = true
}

onMounted(() => {
  if (sessionStore.currentWeekNo) {
    selectedWeek.value = sessionStore.currentWeekNo
  }
})
</script>

<template>
  <div class="student-preview-card">
    <!-- 顶栏与控制条 -->
    <div class="preview-header">
      <div class="title-section">
        <div class="flex items-center gap-2">
          <span class="preview-badge font-mono">小程序课表视窗</span>
          <h3 class="font-serif font-bold text-base text-[var(--ink)]">学生端课表高保真预览</h3>
        </div>
        <p class="preview-sub text-xs text-[var(--ink-mute)] mt-1">
          以学生微信小程序视角实时渲染各班级正式课表。可切换行政班及周次进行发布前核验。
        </p>
      </div>

      <!-- 快捷操作区 -->
      <div class="preview-controls flex items-center gap-3 flex-wrap">
        <!-- 切换行政班 -->
        <div class="control-item flex items-center gap-1.5">
          <label class="text-xs font-semibold text-[var(--ink-soft)]">预览班级：</label>
          <el-select
            v-model="selectedClassId"
            placeholder="选择行政班"
            filterable
            class="w-48"
            :loading="loadingClasses"
          >
            <el-option
              v-for="c in adminClasses"
              :key="c.id"
              :label="c.class_name"
              :value="String(c.id)"
            >
              <div class="flex items-center justify-between">
                <span>{{ c.class_name }}</span>
                <span class="text-xs text-gray-400 font-mono">{{ c.class_code }}</span>
              </div>
            </el-option>
          </el-select>
        </div>

        <!-- 切换周次 -->
        <div class="control-item flex items-center gap-1 bg-slate-100 p-1 rounded">
          <button
            class="week-nav-btn"
            :disabled="selectedWeek <= 1"
            title="上一周"
            @click="prevWeek"
          >
            ‹
          </button>
          <el-select
            v-model="selectedWeek"
            class="w-24 week-select"
            size="small"
          >
            <el-option
              v-for="w in totalWeeks"
              :key="w"
              :label="`第 ${w} 周`"
              :value="w"
            />
          </el-select>
          <button
            class="week-nav-btn"
            :disabled="selectedWeek >= totalWeeks"
            title="下一周"
            @click="nextWeek"
          >
            ›
          </button>
          <button
            v-if="selectedWeek !== currentWeekNo"
            class="btn btn-xs btn-dark ml-1 py-0.5 px-2"
            title="回到当前开学自然教学周"
            @click="backToCurrentWeek"
          >
            回本周
          </button>
        </div>

        <!-- 周末开关 -->
        <label class="text-xs text-[var(--ink-soft)] flex items-center gap-1 cursor-pointer select-none">
          <input type="checkbox" v-model="showWeekend" class="rounded" />
          <span>显示周末</span>
        </label>
      </div>
    </div>

    <!-- 课表状态与数据统计栏 -->
    <div class="timetable-meta-bar flex items-center justify-between text-xs px-4 py-2 bg-slate-50 border-y border-[var(--line)]">
      <div class="flex items-center gap-2">
        <span class="font-bold text-slate-700">
          {{ currentAdminClass?.class_name || '未选定班级' }}
        </span>
        <span v-if="currentAdminClass?.head_teacher" class="text-slate-500">
          班主任: {{ currentAdminClass.head_teacher }}
        </span>
        <span v-if="currentAdminClass?.counselor" class="text-slate-500">
          辅导员: {{ currentAdminClass.counselor }}
        </span>
        <span class="text-slate-300">|</span>
        <span class="font-mono text-slate-600">
          第 {{ selectedWeek }} 周（{{ currentWeekCourses.length }} 门课）
        </span>
      </div>
      <div class="text-[var(--ink-mute)] font-mono">
        学期总排课 {{ semesterCourses.length }} 门 · 小程序排版渲染
      </div>
    </div>

    <!-- 核心课表视窗容器 -->
    <div v-loading="loadingTimetable" class="timetable-viewport">
      <!-- 星期与公历日期表头 -->
      <div class="date-header-row">
        <!-- 左上角年份与周次 -->
        <div class="corner-cell">
          <div class="corner-year font-mono">{{ yearText }}</div>
          <div class="corner-week font-bold">{{ selectedWeek }}周</div>
        </div>

        <!-- 各星期列头 -->
        <div
          v-for="col in dayColumns"
          :key="col.weekday"
          class="day-header-cell"
          :class="{ 'is-today': col.dateHeader.isToday }"
        >
          <div class="day-name font-bold">周{{ col.name }}</div>
          <div class="day-date font-mono">{{ col.dateHeader.dateStr }}</div>
        </div>
      </div>

      <!-- 课表纵向网格主体 -->
      <div class="timetable-grid-body">
        <!-- 左侧节次与作息时间轴 (1~11节) -->
        <div class="period-sidebar">
          <div
            v-for="p in DEFAULT_PERIODS"
            :key="p.num"
            class="period-cell"
          >
            <div class="period-num font-mono font-bold">{{ p.num }}</div>
            <div class="period-time font-mono">{{ p.start }}</div>
            <div class="period-time font-mono">{{ p.end }}</div>
          </div>
        </div>

        <!-- 星期课程列容器 -->
        <div class="days-container">
          <div
            v-for="col in dayColumns"
            :key="col.weekday"
            class="day-column"
          >
            <!-- 背景网格虚线层 (11个单元格) -->
            <div class="bg-cells-layer">
              <div
                v-for="p in DEFAULT_PERIODS"
                :key="p.num"
                class="bg-cell"
              />
            </div>

            <!-- 前景课程卡片绝对定位层 -->
            <div class="course-blocks-layer">
              <div
                v-for="block in col.blocks"
                :key="block.id"
                class="course-card"
                :class="{ 'is-conflict': block.isConflict }"
                :style="{
                  top: block.styleTop,
                  height: block.styleHeight,
                  left: block.styleLeft,
                  width: block.styleWidth,
                  backgroundColor: block.color.bg,
                  borderColor: block.isConflict ? '#EF4444' : block.color.border,
                  color: block.color.text
                }"
                :title="`${block.courseName} (${formatPeriodText(block.startPeriod, block.endPeriod)})`"
                @click="handleCourseClick(block)"
              >
                <div class="card-inner">
                  <div class="card-title font-bold">
                    {{ block.courseName }}
                  </div>
                  <div v-if="block.teacherName" class="card-teacher">
                    {{ block.teacherName }}
                  </div>
                  <div v-if="block.classroom" class="card-room">
                    @{{ block.roomBuilding }} {{ block.roomNumber }}
                  </div>
                  <div v-if="block.isConflict" class="conflict-tag">
                    冲突
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 空课表提示 -->
      <div
        v-if="!loadingTimetable && currentWeekCourses.length === 0"
        class="empty-week-overlay"
      >
        <div class="empty-box">
          <AppIcon name="book" :size="32" class="text-slate-300 mb-2" />
          <div class="text-sm font-bold text-slate-600">
            {{ currentAdminClass?.class_name || '当前班级' }}在第 {{ selectedWeek }} 周暂无排课
          </div>
          <div class="text-xs text-slate-400 mt-1">
            该班级在整个学期共安排了 {{ semesterCourses.length }} 门排课，您可以切换周次查看。
          </div>
        </div>
      </div>
    </div>

    <!-- 课程详情弹窗 -->
    <el-dialog
      v-model="showCourseDetail"
      title="课程排课明细与学生端呈现"
      width="540px"
      append-to-body
      destroy-on-close
    >
      <div v-if="activeCourse" class="space-y-3.5 text-sm">
        <div class="p-3 rounded-lg border" :style="{
          backgroundColor: MORANDI_PALETTE[getCourseColorIndex(activeCourse.course_name)]?.bg || '#F8FAFC',
          borderColor: MORANDI_PALETTE[getCourseColorIndex(activeCourse.course_name)]?.border || '#E2E8F0',
          color: MORANDI_PALETTE[getCourseColorIndex(activeCourse.course_name)]?.text || '#1E293B'
        }">
          <div class="text-lg font-bold font-serif">{{ activeCourse.course_name }}</div>
          <div class="text-xs font-mono opacity-80 mt-0.5">代码: {{ activeCourse.course_code || '未设置' }}</div>
        </div>

        <div class="grid grid-cols-2 gap-3 text-xs">
          <div class="bg-slate-50 p-2.5 rounded border border-slate-100">
            <span class="text-slate-400 block mb-0.5">任课教师</span>
            <span class="font-bold text-slate-700">{{ activeCourse.teacher_name || '未指定教师' }}</span>
          </div>
          <div class="bg-slate-50 p-2.5 rounded border border-slate-100">
            <span class="text-slate-400 block mb-0.5">上课地点</span>
            <span class="font-bold text-slate-700">{{ activeCourse.classroom || '未排教室' }}</span>
          </div>
          <div class="bg-slate-50 p-2.5 rounded border border-slate-100">
            <span class="text-slate-400 block mb-0.5">上课时间</span>
            <span class="font-bold text-slate-700">周{{ activeCourse.weekday }} {{ formatPeriodText(activeCourse.start_period, activeCourse.end_period) }}</span>
          </div>
          <div class="bg-slate-50 p-2.5 rounded border border-slate-100">
            <span class="text-slate-400 block mb-0.5">生效周次</span>
            <span class="font-bold font-mono text-slate-700">{{ formatWeeksText(activeCourse.weeks) }}</span>
          </div>
        </div>

        <div class="text-xs space-y-1.5 pt-1">
          <div class="flex items-start gap-2">
            <span class="text-slate-400 shrink-0">所属教学班：</span>
            <span class="font-medium text-slate-700">{{ activeCourse.teaching_class_name }}</span>
          </div>
          <div v-if="activeCourse.administrative_classes && activeCourse.administrative_classes.length > 0" class="flex items-start gap-2">
            <span class="text-slate-400 shrink-0">合班行政班：</span>
            <span class="text-slate-700">{{ activeCourse.administrative_classes.join('、') }}</span>
          </div>
          <div v-if="activeCourse.head_teacher || currentAdminClass?.head_teacher" class="flex items-center gap-2">
            <span class="text-slate-400 shrink-0">班级班主任：</span>
            <span class="text-slate-700">{{ activeCourse.head_teacher || currentAdminClass?.head_teacher }}</span>
          </div>
          <div v-if="activeCourse.counselor || currentAdminClass?.counselor" class="flex items-center gap-2">
            <span class="text-slate-400 shrink-0">年级辅导员：</span>
            <span class="text-slate-700">{{ activeCourse.counselor || currentAdminClass?.counselor }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-slate-400 shrink-0">查课与名单：</span>
            <span v-if="activeCourse.is_physical_education" class="text-slate-500">体育课 · 免查</span>
            <span v-else-if="activeCourse.enrolled_student_count > 0" class="text-emerald-700 font-semibold">
              需查课 · 选课名单已导入 ({{ activeCourse.enrolled_student_count }} 人)
            </span>
            <span v-else class="text-amber-600 font-medium">暂无学生名单（仅排课框架）</span>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-dark" @click="showCourseDetail = false">确定</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.student-preview-card {
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: #ffffff;
  margin-top: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.preview-header {
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  background: var(--paper);
}

.preview-badge {
  font-size: 11px;
  padding: 2px 8px;
  background: #3B82F6;
  color: #ffffff;
  border-radius: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.week-nav-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  font-size: 16px;
  font-weight: bold;
  color: var(--ink-soft);
  cursor: pointer;
  border-radius: 2px;
}
.week-nav-btn:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.06);
  color: var(--ink);
}
.week-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 核心课表视窗 */
.timetable-viewport {
  position: relative;
  background: #ffffff;
  overflow-x: auto;
}

/* 星期与公历表头 */
.date-header-row {
  display: flex;
  border-bottom: 1px solid #E2E8F0;
  background: #F8FAFC;
  position: sticky;
  top: 0;
  z-index: 10;
}

.corner-cell {
  width: 74px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 0;
  border-right: 1px solid #E2E8F0;
  background: #F1F5F9;
}
.corner-year {
  font-size: 10px;
  color: #64748B;
  line-height: 1.1;
}
.corner-week {
  font-size: 11px;
  color: #3B82F6;
  line-height: 1.2;
}

.day-header-cell {
  flex: 1;
  min-width: 110px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 8px 0;
  border-right: 1px solid #F1F5F9;
}
.day-header-cell:last-child {
  border-right: none;
}
.day-header-cell.is-today {
  background: #EFF6FF;
}
.day-header-cell.is-today .day-name,
.day-header-cell.is-today .day-date {
  color: #2563EB;
}
.day-name {
  font-size: 12px;
  color: #1E293B;
}
.day-date {
  font-size: 11px;
  color: #94A3B8;
  margin-top: 2px;
}

/* 网格主体 */
.timetable-grid-body {
  display: flex;
  position: relative;
  min-height: 770px;
}

/* 左侧节次与作息 */
.period-sidebar {
  width: 74px;
  flex-shrink: 0;
  border-right: 1px solid #E2E8F0;
  background: #F8FAFC;
}

.period-cell {
  height: 70px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-bottom: 1px dashed #E2E8F0;
  padding: 2px 0;
  box-sizing: border-box;
}
.period-num {
  font-size: 13px;
  color: #1E293B;
  line-height: 1.2;
}
.period-time {
  font-size: 10px;
  color: #94A3B8;
  line-height: 1.2;
}

/* 右侧星期课程网格列 */
.days-container {
  flex: 1;
  display: flex;
  position: relative;
}

.day-column {
  flex: 1;
  min-width: 110px;
  position: relative;
  border-right: 1px solid #F1F5F9;
  box-sizing: border-box;
}
.day-column:last-child {
  border-right: none;
}

.bg-cells-layer {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.bg-cell {
  height: 70px;
  border-bottom: 1px dashed #F1F5F9;
  box-sizing: border-box;
}

/* 前景课程卡片绝对定位层 */
.course-blocks-layer {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
}

.course-card {
  position: absolute;
  box-sizing: border-box;
  border-radius: 6px;
  border-width: 1px;
  border-style: solid;
  padding: 6px;
  overflow: hidden;
  pointer-events: auto;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: transform 0.12s ease, box-shadow 0.12s ease;
  user-select: none;
}
.course-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
  z-index: 5;
}
.course-card.is-conflict {
  box-shadow: 0 0 0 1px #EF4444;
}

.card-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.card-title {
  font-size: 11px;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  word-break: break-all;
}

.card-teacher {
  font-size: 10px;
  opacity: 0.85;
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-room {
  font-size: 10px;
  opacity: 0.85;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conflict-tag {
  align-self: flex-start;
  font-size: 9px;
  background: #EF4444;
  color: #ffffff;
  padding: 1px 4px;
  border-radius: 2px;
  font-weight: bold;
  margin-top: auto;
}

/* 空课表提示浮层 */
.empty-week-overlay {
  position: absolute;
  top: 60px;
  left: 74px;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(2px);
  pointer-events: none;
}
</style>
