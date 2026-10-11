<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listManagementSubmissions,
  reviewSubmission,
  batchReviewSubmissions,
  type ManagementSubmissionItem
} from '../api/submissions'
import AppIcon from '../components/AppIcon.vue'

const sessionStore = useSessionStore()

const loading = ref(false)
const singleReviewLoading = ref(false)
const batchLoading = ref(false)
const submissions = ref<ManagementSubmissionItem[]>([])
const activeId = ref<string>('')
const statusFilter = ref<string>('PENDING')
const searchQuery = ref<string>('')
const selectedIds = ref<string[]>([])
const queueListRef = ref<HTMLElement | null>(null)

async function fetchSubmissions() {
  loading.value = true
  try {
    const res = await listManagementSubmissions({
      semester_id: sessionStore.currentSemesterId || undefined,
      page_size: 100
    })
    submissions.value = res.items || []

    // 保持或更新当前选中的项
    if (!submissions.value.some(s => s.id === activeId.value)) {
      const firstPending = submissions.value.find(s => s.review_status === 'PENDING')
      activeId.value = firstPending ? firstPending.id : (submissions.value[0]?.id || '')
    }
  } catch (err: unknown) {
    console.error('获取待审核提交列表失败:', err)
  } finally {
    loading.value = false
  }
}

watch(
  () => sessionStore.currentSemesterId,
  () => {
    fetchSubmissions()
  }
)

onMounted(() => {
  fetchSubmissions()
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

// 宏观统计指标
const pendingSubmissions = computed(() => submissions.value.filter(s => s.review_status === 'PENDING'))
const pendingCount = computed(() => pendingSubmissions.value.length)
const pendingNormalCount = computed(() =>
  pendingSubmissions.value.filter(s => s.result === 'NORMAL' && s.abnormal_items.length === 0).length
)
const pendingAbnormalCount = computed(() =>
  pendingSubmissions.value.filter(s => s.result === 'ABNORMAL' || s.abnormal_items.length > 0).length
)
const reviewedCount = computed(() => submissions.value.filter(s => s.review_status !== 'PENDING').length)

// 视图过滤与搜索
const filteredSubmissions = computed(() => {
  let list = submissions.value

  if (statusFilter.value === 'PENDING') {
    list = list.filter(s => s.review_status === 'PENDING')
  } else if (statusFilter.value === 'ABNORMAL') {
    list = list.filter(s => s.result === 'ABNORMAL' || s.abnormal_items.length > 0)
  } else if (statusFilter.value === 'NORMAL') {
    list = list.filter(s => s.result === 'NORMAL' && s.abnormal_items.length === 0)
  } else if (statusFilter.value === 'APPROVED') {
    list = list.filter(s => s.review_status === 'APPROVED')
  } else if (statusFilter.value === 'REJECTED') {
    list = list.filter(s => s.review_status === 'REJECTED')
  }

  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(s => {
      const course = (s.task?.course_name_snapshot || '').toLowerCase()
      const cls = (s.task?.class_name_snapshot || '').toLowerCase()
      const room = (s.task?.classroom_snapshot || '').toLowerCase()
      const vol = String(s.volunteer_user_id || '').toLowerCase()
      const id = String(s.id).toLowerCase()
      return course.includes(q) || cls.includes(q) || room.includes(q) || vol.includes(q) || id.includes(q)
    })
  }

  return list
})

// 当前右侧展示项
const currentSubmission = computed<ManagementSubmissionItem | null>(() => {
  if (filteredSubmissions.value.length === 0) return null
  const found = filteredSubmissions.value.find(s => s.id === activeId.value)
  return found || filteredSubmissions.value[0] || null
})

// 当过滤导致当前项不在视野内时，平滑修正 activeId
watch(filteredSubmissions, (newList) => {
  if (newList.length > 0 && !newList.some(s => s.id === activeId.value)) {
    activeId.value = newList[0].id
  }
})

// 多选管理
const isAllSelected = computed(() => {
  if (filteredSubmissions.value.length === 0) return false
  return filteredSubmissions.value.every(s => selectedIds.value.includes(s.id))
})

const isIndeterminate = computed(() => {
  const count = filteredSubmissions.value.filter(s => selectedIds.value.includes(s.id)).length
  return count > 0 && count < filteredSubmissions.value.length
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    const filteredIdSet = new Set(filteredSubmissions.value.map(s => s.id))
    selectedIds.value = selectedIds.value.filter(id => !filteredIdSet.has(id))
  } else {
    const set = new Set(selectedIds.value)
    filteredSubmissions.value.forEach(s => set.add(s.id))
    selectedIds.value = Array.from(set)
  }
}

function toggleSelect(id: string) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) {
    selectedIds.value.splice(idx, 1)
  } else {
    selectedIds.value.push(id)
  }
}

// 键盘 ↑ / ↓ 方向键无缝切换审核条目
function handleKeyDown(e: KeyboardEvent) {
  const target = e.target as HTMLElement
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  if (filteredSubmissions.value.length <= 1) return

  const curIdx = filteredSubmissions.value.findIndex(s => s.id === activeId.value)
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    const nextIdx = curIdx < filteredSubmissions.value.length - 1 ? curIdx + 1 : 0
    activeId.value = filteredSubmissions.value[nextIdx].id
    scrollActiveIntoView()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    const prevIdx = curIdx > 0 ? curIdx - 1 : filteredSubmissions.value.length - 1
    activeId.value = filteredSubmissions.value[prevIdx].id
    scrollActiveIntoView()
  }
}

function scrollActiveIntoView() {
  nextTick(() => {
    const activeEl = queueListRef.value?.querySelector('.queue-card.active') as HTMLElement
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}

// 单笔通过
async function handleApprove(sub?: ManagementSubmissionItem) {
  const target = sub || currentSubmission.value
  if (!target) return
  singleReviewLoading.value = true
  try {
    await reviewSubmission(target.id, { decision: 'APPROVED' })
    ElMessage.success(`提交 #${target.id} 审核通过！考勤事实已固化入库。`)
    await fetchSubmissions()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '审核失败'
    ElMessage.error(msg)
  } finally {
    singleReviewLoading.value = false
  }
}

// 单笔驳回
async function handleReject(sub?: ManagementSubmissionItem) {
  const target = sub || currentSubmission.value
  if (!target) return
  try {
    const { value: comment } = await ElMessageBox.prompt(
      '请输入驳回理由（该说明将反馈给小程序端志愿者并完整记入审计日志）：',
      `驳回考勤提交 #${target.id}`,
      {
        confirmButtonText: '确认驳回',
        cancelButtonText: '取消',
        inputPattern: /\S+/,
        inputErrorMessage: '驳回理由不能为空'
      }
    )

    if (comment) {
      singleReviewLoading.value = true
      await reviewSubmission(target.id, {
        decision: 'REJECTED',
        comment
      })
      ElMessage.warning(`提交 #${target.id} 已驳回，理由：${comment}`)
      await fetchSubmissions()
    }
  } catch {
    // cancelled
  } finally {
    singleReviewLoading.value = false
  }
}

// ⚡ 一键通过所有全勤正常项（核心推荐加速）
async function handleBatchApproveNormal() {
  const normalPending = pendingSubmissions.value.filter(
    s => s.result === 'NORMAL' && s.abnormal_items.length === 0
  )
  if (normalPending.length === 0) {
    ElMessage.info('当前没有待审核的全勤提交记录')
    return
  }

  try {
    await ElMessageBox.confirm(
      `检测到当前共有 ${normalPending.length} 笔【全员到齐（无异常）】的待审核记录。\n\n• 点击确定将一键批量通过并固化全勤事实；\n• 其余含异常学生名单的提交将安全保留在队列中，供人工重点核查。`,
      '⚡ 一键通过全勤正常提交',
      {
        confirmButtonText: `确认通过 (${normalPending.length} 笔)`,
        cancelButtonText: '取消',
        type: 'success',
        confirmButtonClass: 'el-button--success'
      }
    )

    batchLoading.value = true
    const res = await batchReviewSubmissions({
      submission_ids: normalPending.map(s => s.id),
      decision: 'APPROVED',
      comment: '管理端一键批量通过全勤提交'
    })

    ElMessage.success(`批量处理完成！成功通过 ${res.success_count} 笔全勤考勤提交。`)
    await fetchSubmissions()
  } catch (err: unknown) {
    if (err !== 'cancel') {
      const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '批量审核失败'
      ElMessage.error(msg)
    }
  } finally {
    batchLoading.value = false
  }
}

// 批量通过勾选项
async function handleBatchApproveSelected() {
  const selectedPending = submissions.value.filter(
    s => selectedIds.value.includes(s.id) && s.review_status === 'PENDING'
  )
  if (selectedPending.length === 0) {
    ElMessage.warning('所选记录中没有处于待审核状态的提交')
    return
  }

  const normalCount = selectedPending.filter(s => s.result === 'NORMAL' && s.abnormal_items.length === 0).length
  const abnormalCount = selectedPending.length - normalCount

  const warningText = abnormalCount > 0
    ? `\n\n⚠️ 注意：选中的条目中包含 ${abnormalCount} 笔存在异常学生的考勤记录，通过后将正式固化缺勤事实！`
    : ''

  try {
    await ElMessageBox.confirm(
      `确定要批量通过选中的 ${selectedPending.length} 笔待审核提交吗？（其中全勤到齐 ${normalCount} 笔，含异常 ${abnormalCount} 笔）${warningText}`,
      '批量通过已选提交',
      {
        confirmButtonText: `确认通过 (${selectedPending.length} 笔)`,
        cancelButtonText: '取消',
        type: abnormalCount > 0 ? 'warning' : 'info'
      }
    )

    batchLoading.value = true
    const res = await batchReviewSubmissions({
      submission_ids: selectedPending.map(s => s.id),
      decision: 'APPROVED',
      comment: '管理端批量审核通过'
    })

    ElMessage.success(`批量审核成功！已通过 ${res.success_count} 笔，失败 ${res.failed_count} 笔。`)
    selectedIds.value = []
    await fetchSubmissions()
  } catch (err: unknown) {
    if (err !== 'cancel') {
      const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '批量审核失败'
      ElMessage.error(msg)
    }
  } finally {
    batchLoading.value = false
  }
}

// 一键通过全部待审（包含异常高危警示）
async function handleBatchApproveAllPending() {
  if (pendingSubmissions.value.length === 0) {
    ElMessage.info('当前没有待审核的提交记录')
    return
  }

  const normalCount = pendingNormalCount.value
  const abnormalCount = pendingAbnormalCount.value

  const warningContent = abnormalCount > 0
    ? `⚠️ 高危提示：当前待审队列中包含 ${abnormalCount} 笔【存在异常学生】的查课记录！\n\n一键全部通过后，相关学生的旷课/迟到记录将直接固化记入正式考勤档案。\n\n全勤记录：${normalCount} 笔\n异常记录：${abnormalCount} 笔\n总计通过：${pendingSubmissions.value.length} 笔`
    : `当前待审共 ${pendingSubmissions.value.length} 笔，均为全勤到齐。确认全部通过吗？`

  try {
    await ElMessageBox.confirm(
      warningContent,
      '一键通过全部待审记录',
      {
        confirmButtonText: `确认全部通过 (${pendingSubmissions.value.length} 笔)`,
        cancelButtonText: '取消',
        type: abnormalCount > 0 ? 'warning' : 'info',
        confirmButtonClass: abnormalCount > 0 ? 'el-button--danger' : 'el-button--primary'
      }
    )

    batchLoading.value = true
    const res = await batchReviewSubmissions({
      submission_ids: pendingSubmissions.value.map(s => s.id),
      decision: 'APPROVED',
      comment: '管理端一键全部审核通过'
    })

    ElMessage.success(`全量初审通过！共完成 ${res.success_count} 笔，失败 ${res.failed_count} 笔。`)
    await fetchSubmissions()
  } catch (err: unknown) {
    if (err !== 'cancel') {
      const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '一键全部通过失败'
      ElMessage.error(msg)
    }
  } finally {
    batchLoading.value = false
  }
}

const typeMap: Record<string, string> = {
  'LATE': '迟到',
  'ABSENT': '旷课',
  'LEAVE': '请假'
}
</script>

<template>
  <div v-loading="loading || batchLoading">
    <!-- 页头 -->
    <header class="page-head">
      <div class="crumb font-mono">
        <span>SUBMISSIONS REVIEW</span>
        <em>●</em>
        <span>待初审 {{ pendingCount }} 笔</span>
        <em>●</em>
        <span>总记录 {{ submissions.length }} 笔</span>
      </div>
      <h1>查课提交管理审核</h1>
      <p class="sub">
        双栏审单工作台：左侧快速切换待审队列，右侧深度审查到课清点事实与现场照片。支持快捷键极速连审与一键安全批量通过。
      </p>
    </header>

    <!-- 统计指标卡行 -->
    <div class="stat-row">
      <div class="stat-cell" :class="{ 'stat-focus': pendingCount > 0 }">
        <div class="label">待初审总量</div>
        <div class="value font-mono" :style="{ color: pendingCount > 0 ? 'var(--amber)' : 'var(--ink)' }">
          {{ pendingCount }}
        </div>
        <div class="note">等待管理复核放行</div>
      </div>
      <div class="stat-cell">
        <div class="label">全勤正常待放行</div>
        <div class="value font-mono" style="color: var(--green)">
          {{ pendingNormalCount }}
        </div>
        <div class="note">0异常 · 推荐一键秒放</div>
      </div>
      <div class="stat-cell">
        <div class="label">存在异常需核查</div>
        <div class="value font-mono" :style="{ color: pendingAbnormalCount > 0 ? 'var(--accent)' : 'var(--ink-mute)' }">
          {{ pendingAbnormalCount }}
        </div>
        <div class="note">含旷课/迟到 · 需重点复核</div>
      </div>
      <div class="stat-cell">
        <div class="label">已处理归档</div>
        <div class="value font-mono" style="color: var(--blue)">
          {{ reviewedCount }}
        </div>
        <div class="note">已通过或已驳回入库</div>
      </div>
    </div>

    <!-- 过滤器与操作工具栏 -->
    <div class="toolbar-wrap">
      <div class="filter-tabs">
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'PENDING' }"
          @click="statusFilter = 'PENDING'"
        >
          待审核 ({{ pendingCount }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'ABNORMAL' }"
          @click="statusFilter = 'ABNORMAL'"
        >
          ⚠️ 仅看异常 ({{ pendingAbnormalCount }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'NORMAL' }"
          @click="statusFilter = 'NORMAL'"
        >
          🟢 仅看全勤 ({{ pendingNormalCount }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === '' }"
          @click="statusFilter = ''"
        >
          全部 ({{ submissions.length }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'APPROVED' }"
          @click="statusFilter = 'APPROVED'"
        >
          已通过
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'REJECTED' }"
          @click="statusFilter = 'REJECTED'"
        >
          已驳回
        </button>
      </div>

      <div class="action-tools">
        <div class="search-box">
          <AppIcon name="search" :size="13" class="search-icon" />
          <input
            v-model="searchQuery"
            type="text"
            class="input search-input"
            placeholder="搜索课程 / 班级 / 教室 / 志愿者…"
          />
        </div>

        <!-- ⚡ 一键通过所有全勤待审（主力推荐） -->
        <button
          class="btn btn-sm btn-flash inline-flex items-center gap-1.5 shadow-sm"
          :disabled="pendingNormalCount === 0 || batchLoading"
          title="一键通过所有到课清点全勤（0异常）的待审核提交，其余异常项保留人工复查"
          @click="handleBatchApproveNormal"
        >
          <AppIcon name="sparkles" :size="13" class="text-emerald-300" />
          <span>⚡ 一键通过全勤待审 ({{ pendingNormalCount }})</span>
        </button>

        <!-- 批量通过勾选项 -->
        <button
          v-if="selectedIds.length > 0"
          class="btn btn-sm btn-dark inline-flex items-center gap-1.5"
          :disabled="batchLoading"
          @click="handleBatchApproveSelected"
        >
          <AppIcon name="check" :size="13" />
          <span>批量通过勾选 ({{ selectedIds.length }})</span>
        </button>

        <!-- 一键全部通过（含异常高危弹窗确认） -->
        <button
          v-if="pendingCount > 0"
          class="btn btn-sm btn-ghost inline-flex items-center gap-1 text-xs"
          :disabled="batchLoading"
          title="将当前学期所有待审核提交一次性全额通过（包含异常考勤项）"
          @click="handleBatchApproveAllPending"
        >
          <span>一键通过全部待审</span>
        </button>

        <button class="btn btn-sm btn-ghost" @click="fetchSubmissions">⟳ 刷新</button>
      </div>
    </div>

    <!-- 主从双栏核心工作台 -->
    <div v-if="filteredSubmissions.length > 0" class="master-detail-container">
      <!-- 左栏：待审队列卡片列表 -->
      <aside class="queue-panel">
        <div class="queue-panel-head">
          <label class="select-all-label">
            <input
              type="checkbox"
              :checked="isAllSelected"
              :indeterminate="isIndeterminate"
              class="chk"
              @change="toggleSelectAll"
            />
            <span class="head-title font-mono">待审队列 ({{ filteredSubmissions.length }})</span>
          </label>
          <span class="kbd-hint font-mono">支持 ↑ / ↓ 键连选</span>
        </div>

        <div ref="queueListRef" class="queue-list custom-scroll">
          <div
            v-for="sub in filteredSubmissions"
            :key="sub.id"
            class="queue-card"
            :class="{
              active: currentSubmission?.id === sub.id,
              checked: selectedIds.includes(sub.id)
            }"
            @click="activeId = sub.id"
          >
            <div class="card-left-check">
              <input
                type="checkbox"
                :checked="selectedIds.includes(sub.id)"
                class="chk"
                @click.stop="toggleSelect(sub.id)"
              />
            </div>

            <div class="card-body">
              <div class="card-meta font-mono">
                <span class="sub-id">#{{ sub.id }}</span>
                <span class="sub-date">
                  {{ sub.submitted_at ? sub.submitted_at.substring(5, 16).replace('T', ' ') : '—' }}
                </span>
                <span class="sub-attempt">第 {{ sub.attempt_no }} 轮</span>
              </div>

              <div class="card-course-title font-serif">
                {{ sub.task?.course_name_snapshot || '未命名课程' }}
              </div>

              <div class="card-class-desc">
                {{ sub.task?.class_name_snapshot || '教学班' }}
              </div>

              <div class="card-loc-vol font-mono">
                <span>📍 {{ sub.task?.classroom_snapshot || '教室未填' }}</span>
                <span>👤 UID: {{ sub.volunteer_user_id }}</span>
              </div>

              <div class="card-footer-badges">
                <!-- 审核状态标签 -->
                <span
                  v-if="sub.review_status === 'APPROVED'"
                  class="tag tag-green text-xs"
                >
                  已通过
                </span>
                <span
                  v-else-if="sub.review_status === 'REJECTED'"
                  class="tag tag-red text-xs"
                >
                  已驳回
                </span>
                <span
                  v-else-if="sub.result === 'NORMAL' && sub.abnormal_items.length === 0"
                  class="tag tag-green inline-flex items-center gap-1 text-xs"
                >
                  <AppIcon name="check" :size="10" />
                  <span>全勤到齐</span>
                </span>
                <span
                  v-else
                  class="tag tag-red inline-flex items-center gap-1 text-xs font-bold"
                >
                  <AppIcon name="alert" :size="10" />
                  <span>异常 {{ sub.abnormal_items.length }} 人</span>
                </span>

                <!-- 留痕照片徽标 -->
                <span v-if="sub.file_ids && sub.file_ids.length > 0" class="photo-badge font-mono">
                  <AppIcon name="camera" :size="11" />
                  <span>{{ sub.file_ids.length }} 照片</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右栏：现场事实与管理决策展卷 -->
      <main class="detail-canvas custom-scroll">
        <template v-if="currentSubmission">
          <!-- 详情头信息 -->
          <div class="detail-head">
            <div>
              <div class="flex items-center gap-2 mb-2">
                <span
                  class="tag"
                  :class="{
                    'tag-amber': currentSubmission.review_status === 'PENDING',
                    'tag-green': currentSubmission.review_status === 'APPROVED',
                    'tag-red': currentSubmission.review_status === 'REJECTED'
                  }"
                >
                  {{
                    currentSubmission.review_status === 'PENDING'
                      ? '待初审 SUBMISSION-#' + currentSubmission.id
                      : (currentSubmission.review_status === 'APPROVED' ? '已通过' : '已驳回') + ' SUBMISSION-#' + currentSubmission.id
                  }}
                </span>
                <span v-if="currentSubmission.late_at_submission" class="tag tag-amber font-mono">
                  迟交补录
                </span>
              </div>

              <h2 class="detail-title font-serif">
                {{ currentSubmission.task?.course_name_snapshot || '未命名课程' }}
              </h2>
              <div class="detail-subtitle">
                教学班：{{ currentSubmission.task?.class_name_snapshot || '未指定' }} · 教室：{{ currentSubmission.task?.classroom_snapshot || '—' }}
              </div>
            </div>

            <div class="detail-meta font-mono">
              <div>查课任务 ID：<strong>#{{ currentSubmission.task_id }}</strong></div>
              <div>提交志愿者 UID：<strong>{{ currentSubmission.volunteer_user_id }}</strong></div>
              <div>提交时间：{{ currentSubmission.submitted_at ? currentSubmission.submitted_at.substring(0, 19).replace('T', ' ') : '—' }}</div>
            </div>
          </div>

          <!-- 双列内容排版 -->
          <div class="detail-grid">
            <!-- 左列：到课清点与异常考勤事实 -->
            <section class="facts-section">
              <h4 class="sec-heading">现场提交考勤事实</h4>

              <div class="mini-stats">
                <div class="mini-stat">
                  <div class="l">到课清点结论</div>
                  <div
                    class="v font-mono"
                    :style="{ color: currentSubmission.result === 'NORMAL' ? 'var(--green)' : 'var(--accent)' }"
                  >
                    {{ currentSubmission.result === 'NORMAL' ? '全员到齐' : '存在异常' }}
                  </div>
                </div>
                <div class="mini-stat" :class="{ bad: currentSubmission.abnormal_items.length > 0 }">
                  <div class="l">异常学生记录数</div>
                  <div class="v font-mono">{{ currentSubmission.abnormal_items.length }}</div>
                </div>
                <div class="mini-stat">
                  <div class="l">现场留痕照片数</div>
                  <div class="v font-mono">{{ currentSubmission.file_ids.length }}</div>
                </div>
                <div class="mini-stat">
                  <div class="l">提交尝试轮次</div>
                  <div class="v font-mono">第 {{ currentSubmission.attempt_no }} 轮</div>
                </div>
              </div>

              <!-- 异常名单列表 -->
              <div v-if="currentSubmission.abnormal_items.length > 0" class="abnormal-table-wrap">
                <div class="table-sub-title">异常学生明细列表（{{ currentSubmission.abnormal_items.length }} 人）</div>
                <table class="tbl">
                  <thead>
                    <tr>
                      <th>学号</th>
                      <th>姓名</th>
                      <th>考勤认定</th>
                      <th>说明备注</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="ab in currentSubmission.abnormal_items" :key="ab.student_id">
                      <td class="cell-mono">{{ ab.student_no }}</td>
                      <td class="cell-main font-bold">{{ ab.name }}</td>
                      <td>
                        <span
                          class="tag"
                          :class="ab.attendance_type === 'ABSENT' ? 'tag-red' : (ab.attendance_type === 'LATE' ? 'tag-amber' : 'tag-gray')"
                        >
                          {{ typeMap[ab.attendance_type] || ab.attendance_type }}
                        </span>
                      </td>
                      <td class="cell-sub">{{ ab.note || '现场考勤标记' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- 全勤清爽提示 -->
              <div v-else class="normal-tip flex items-center gap-2">
                <AppIcon name="check-circle" :size="18" class="text-emerald-700 shrink-0" />
                <div>
                  <strong>全勤到齐：</strong>
                  <span>志愿者现场核对无缺勤，所有在册学生均已按时应到。</span>
                </div>
              </div>

              <!-- 志愿者备注（若有） -->
              <div v-if="currentSubmission.note" class="note-box">
                <div class="note-label font-mono">志愿者备注说明：</div>
                <div class="note-content">{{ currentSubmission.note }}</div>
              </div>
            </section>

            <!-- 右列：佐证材料与决策卡片 -->
            <section class="side-decision-panel">
              <h4 class="sec-heading">现场证明留痕材料</h4>
              <div v-if="currentSubmission.file_ids.length > 0" class="photo-box">
                <div v-for="fid in currentSubmission.file_ids" :key="fid" class="photo-placeholder">
                  <div class="photo-icon flex justify-center mb-1">
                    <AppIcon name="camera" :size="24" class="text-slate-400" />
                  </div>
                  <div class="photo-id font-mono">证明文件 ID: #{{ fid }}</div>
                </div>
              </div>
              <div v-else class="no-photo-tip font-mono">
                未上传留痕照片（本课次未配置强制拍照）
              </div>

              <!-- 驳回记录信息（若已驳回） -->
              <div v-if="currentSubmission.review_comment" class="reject-box">
                <div class="r-title">驳回说明：</div>
                <div class="r-text">{{ currentSubmission.review_comment }}</div>
                <div class="r-meta font-mono">
                  审核人 UID: {{ currentSubmission.reviewed_by }} · {{ currentSubmission.reviewed_at?.substring(0, 19).replace('T', ' ') }}
                </div>
              </div>

              <!-- 审核决策动作栏 -->
              <div class="decision-wrap">
                <div class="sec-heading">管理审核决策</div>
                <p class="dec-hint">
                  审核通过将自动固化学生考勤事实并入库，驳回将留存驳回原因并通知小程序端。
                </p>

                <div v-if="currentSubmission.review_status === 'PENDING'" class="action-btn-row">
                  <button
                    class="btn btn-dark inline-flex items-center gap-1.5"
                    :disabled="singleReviewLoading"
                    @click="handleApprove(currentSubmission)"
                  >
                    <AppIcon v-if="!singleReviewLoading" name="check" :size="14" />
                    <span>{{ singleReviewLoading ? '处理中…' : '审核通过' }}</span>
                  </button>
                  <button
                    class="btn btn-outline-danger inline-flex items-center gap-1.5"
                    :disabled="singleReviewLoading"
                    @click="handleReject(currentSubmission)"
                  >
                    <AppIcon name="close" :size="14" />
                    <span>驳回并填写原因</span>
                  </button>
                </div>

                <div v-else-if="currentSubmission.review_status === 'APPROVED'" class="decision-done success">
                  <AppIcon name="check-circle" :size="16" class="text-emerald-700" />
                  <span>已审核通过 · 考勤记录已固化落库</span>
                </div>

                <div v-else-if="currentSubmission.review_status === 'REJECTED'" class="decision-done rejected">
                  <AppIcon name="close" :size="16" class="text-red-700" />
                  <span>已驳回 · 理由与历史已留痕归档</span>
                </div>
              </div>
            </section>
          </div>
        </template>

        <div v-else class="detail-empty">
          <AppIcon name="info" :size="32" class="text-slate-300 mb-2" />
          <div class="text-sm font-semibold text-slate-500">请选择左侧待审提交查看详情</div>
        </div>
      </main>
    </div>

    <!-- 无数据状态 -->
    <div v-else-if="!loading" class="empty-box">
      <div class="empty-icon flex justify-center mb-2">
        <AppIcon name="check-circle" :size="36" class="text-gray-300" />
      </div>
      <div class="empty-text">当前筛选条件下暂无查课提交记录</div>
      <div class="empty-sub">切换上方标签或清空搜索词可查看其他记录</div>
    </div>
  </div>
</template>

<style scoped>
/* 统计指标卡 */
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat-cell {
  background: var(--paper);
  border: 1px solid var(--line);
  padding: 16px 20px;
  border-radius: var(--radius);
  transition: border-color 0.2s;
}
.stat-cell.stat-focus {
  border-left: 3px solid var(--amber);
}
.stat-cell .label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-mute);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}
.stat-cell .value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.1;
  margin-bottom: 4px;
}
.stat-cell .note {
  font-size: 11px;
  color: var(--ink-mute);
}

/* 顶部工具栏与筛选 */
.toolbar-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.filter-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.tab-btn {
  padding: 6px 12px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 500;
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-btn:hover {
  background: var(--paper);
  border-color: var(--line-strong);
}
.tab-btn.on {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}

.action-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.search-box {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 10px;
  color: var(--ink-mute);
  pointer-events: none;
}
.search-input {
  width: 240px;
  padding-left: 30px !important;
  font-size: 12px;
}

/* ⚡ 一键全勤通过特殊按钮风格 */
.btn-flash {
  background: #1e4620;
  border: 1px solid #153217;
  color: #f0fdf4;
  font-weight: 600;
}
.btn-flash:hover:not(:disabled) {
  background: #285e2b;
  color: #ffffff;
}
.btn-flash:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 主从双栏布局容器 */
.master-detail-container {
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: 16px;
  align-items: start;
}

/* 左栏：待审队列面板 */
.queue-panel {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
}
.queue-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
}
.select-all-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.head-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
}
.kbd-hint {
  font-size: 10px;
  color: var(--ink-mute);
}

.queue-list {
  max-height: calc(100vh - 280px);
  min-height: 480px;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 队列单张卡片 */
.queue-card {
  display: flex;
  gap: 10px;
  padding: 12px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.15s ease-in-out;
}
.queue-card:hover {
  background: var(--paper-deep);
  border-color: var(--line-strong);
}
.queue-card.active {
  background: #ffffff;
  border-color: var(--blue);
  box-shadow: 0 0 0 1px var(--blue);
}
.queue-card.checked {
  background: #fbfbfd;
}

.card-left-check {
  padding-top: 2px;
}
.card-body {
  flex: 1;
  min-width: 0;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--ink-mute);
  margin-bottom: 4px;
}
.sub-id {
  font-weight: 700;
  color: var(--ink);
}
.sub-attempt {
  margin-left: auto;
  background: var(--paper-deep);
  padding: 1px 6px;
  border-radius: 2px;
}

.card-course-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.3;
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-class-desc {
  font-size: 12px;
  color: var(--ink-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 6px;
}
.card-loc-vol {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--ink-mute);
  margin-bottom: 8px;
}
.card-footer-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.photo-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  font-size: 10px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  color: var(--ink-soft);
  border-radius: 2px;
}

/* 右栏：详情展卷 */
.detail-canvas {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  max-height: calc(100vh - 280px);
  min-height: 480px;
  overflow-y: auto;
}
.detail-head {
  padding: 24px;
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}
.detail-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 6px;
}
.detail-subtitle {
  font-size: 13px;
  color: var(--ink-soft);
}
.detail-meta {
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.8;
  text-align: right;
  white-space: nowrap;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 24px;
  padding: 24px;
}

.sec-heading {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  margin-bottom: 14px;
}

/* 指标小四格 */
.mini-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 20px;
}
.mini-stat {
  padding: 10px 12px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
}
.mini-stat .l {
  font-size: 10px;
  color: var(--ink-mute);
  margin-bottom: 2px;
}
.mini-stat .v {
  font-size: 15px;
  font-weight: 700;
}
.mini-stat.bad .v {
  color: var(--accent);
}

.normal-tip {
  padding: 16px;
  background: var(--green-soft);
  color: var(--green);
  font-size: 13px;
  border-left: 3px solid var(--green);
}

.table-sub-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--ink);
}

.note-box {
  margin-top: 16px;
  padding: 12px;
  background: var(--paper-deep);
  border-left: 2px solid var(--line-strong);
}
.note-label {
  font-size: 10px;
  color: var(--ink-mute);
  margin-bottom: 4px;
}
.note-content {
  font-size: 12px;
  color: var(--ink);
}

/* 侧边决策面板 */
.side-decision-panel {
  border-left: 1px solid var(--line);
  padding-left: 24px;
}
.photo-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}
.photo-placeholder {
  padding: 14px;
  background: var(--paper-deep);
  border: 1px dashed var(--line-strong);
  text-align: center;
}
.photo-id {
  font-size: 11px;
  color: var(--ink-mute);
}
.no-photo-tip {
  padding: 12px;
  background: var(--paper-deep);
  color: var(--ink-mute);
  font-size: 11px;
  margin-bottom: 20px;
  text-align: center;
}

.reject-box {
  padding: 12px;
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  margin-bottom: 20px;
}
.r-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 4px;
}
.r-text {
  font-size: 12px;
  color: var(--ink);
  margin-bottom: 4px;
}
.r-meta {
  font-size: 10px;
  color: var(--ink-mute);
}

.decision-wrap {
  border-top: 1px solid var(--line);
  padding-top: 18px;
}
.dec-hint {
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.5;
  margin-bottom: 14px;
}
.action-btn-row {
  display: flex;
  gap: 10px;
}
.btn-outline-danger {
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
}
.btn-outline-danger:hover {
  background: var(--accent-soft);
}

.decision-done {
  padding: 12px;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 2px;
}
.decision-done.success {
  background: var(--green-soft);
  color: var(--green);
}
.decision-done.rejected {
  background: var(--accent-soft);
  color: var(--accent);
}

.detail-empty {
  padding: 100px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

/* 空白视图 */
.empty-box {
  padding: 80px 20px;
  text-align: center;
  color: var(--ink-mute);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.empty-icon { font-size: 32px; color: var(--green); margin-bottom: 8px; }
.empty-text { font-size: 14px; font-weight: 600; color: var(--ink-soft); margin-bottom: 4px; }
.empty-sub { font-size: 12px; }

/* 滚动条细化 */
.custom-scroll::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: var(--line-strong);
  border-radius: 3px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}

@media (max-width: 1100px) {
  .master-detail-container {
    grid-template-columns: 1fr;
  }
  .queue-list {
    max-height: 360px;
  }
  .detail-grid {
    grid-template-columns: 1fr;
  }
  .side-decision-panel {
    border-left: none;
    border-top: 1px solid var(--line);
    padding-left: 0;
    padding-top: 20px;
  }
}
</style>
