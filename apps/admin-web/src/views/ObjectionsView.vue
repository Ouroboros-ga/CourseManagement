<script setup lang="ts">
import { formatBeijingTime } from '@/utils/datetime'
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '../stores/session'
import AppIcon from '../components/AppIcon.vue'
import { useFileAccess } from '../composables/useFileAccess'
import {
  listObjections,
  finalReviewObjection,
  type ObjectionItem,
  type ObjectionFinalStatus
} from '../api/objections'
import {
  getAttendanceRecord,
  type AttendanceRecord,
  type AttendanceType
} from '../api/attendance'

const sessionStore = useSessionStore()

const loading = ref(false)
const submitLoading = ref(false)
const objections = ref<ObjectionItem[]>([])
const activeIndex = ref<number>(0)
const statusFilter = ref<string>('ALL')
const page = ref(1)
const total = ref(0)
let listRequest = 0
const attendanceMap = ref<Record<string, AttendanceRecord>>({})

// 审核表单
const finalDecision = ref<'LEAVE' | 'NORMAL' | 'LATE' | 'ABSENT' | 'REJECTED'>('LEAVE')
const finalReasonNote = ref('')

const typeMap: Record<string, string> = {
  NORMAL: '正常出勤',
  LEAVE: '请假',
  LATE: '迟到',
  ABSENT: '旷课'
}

async function fetchObjections() {
  const requestId = ++listRequest
  loading.value = true
  try {
    let final_status: ObjectionFinalStatus | undefined = undefined

    if (statusFilter.value === 'PENDING_FINAL') {
      final_status = 'PENDING'
    } else if (statusFilter.value === 'APPROVED') {
      final_status = 'APPROVED'
    } else if (statusFilter.value === 'REJECTED') {
      final_status = 'REJECTED'
    }

    const res = await listObjections({
      final_status,
      page: page.value,
      page_size: 50
    })

    if (requestId !== listRequest) return
    objections.value = res.items || []
    total.value = res.total
    if (activeIndex.value >= objections.value.length) {
      activeIndex.value = 0
    }

    // 预加载考勤记录快照
    const recordIds = Array.from(new Set(objections.value.map(o => o.attendance_record_id)))
    await loadAttendanceForRecords(recordIds)
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取考勤异议列表失败'
    ElMessage.error(msg)
  } finally {
    if (requestId === listRequest) loading.value = false
  }
}

async function loadAttendanceForRecords(recordIds: string[]) {
  const missing = recordIds.filter(id => id && !attendanceMap.value[id])
  if (missing.length === 0) return
  await Promise.allSettled(
    missing.map(async id => {
      try {
        const att = await getAttendanceRecord(id)
        attendanceMap.value[id] = att
      } catch (e) {
        console.warn(`拉取考勤记录 #${id} 失败:`, e)
      }
    })
  )
}

watch(statusFilter, () => {
  page.value = 1
  activeIndex.value = 0
  fetchObjections()
})

onMounted(() => {
  fetchObjections()
})

const activeObjection = computed<ObjectionItem | null>(() => {
  if (objections.value.length === 0) return null
  return objections.value[activeIndex.value] || null
})

const activeAttendance = computed<AttendanceRecord | null>(() => {
  if (!activeObjection.value) return null
  return attendanceMap.value[activeObjection.value.attendance_record_id] || null
})

// 默认预设期望改判类型
watch(
  () => activeObjection.value,
  obj => {
    if (obj) {
      if (obj.final_status === 'PENDING') {
        finalDecision.value = obj.desired_type || 'LEAVE'
      } else if (obj.final_status === 'REJECTED') {
        finalDecision.value = 'REJECTED'
      } else if (obj.final_attendance_type) {
        finalDecision.value = obj.final_attendance_type
      }
      finalReasonNote.value = obj.final_comment || ''
    }
  },
  { immediate: true }
)

// 审核提交
function reviewerAccount(obj: ObjectionItem): string {
  const account = obj.final_reviewed_username || (obj.final_reviewed_by ? `账号 #${obj.final_reviewed_by}` : '历史账号不可用')
  return obj.final_reviewed_display_name ? `${obj.final_reviewed_display_name}（${account}）` : account
}

async function handleFinalReview() {
  if (!activeObjection.value || submitLoading.value) return
  const objection = activeObjection.value
  if (!activeAttendance.value) {
    ElMessage.warning('正在加载考勤基准数据，请稍后重试')
    return
  }

  const isReject = finalDecision.value === 'REJECTED'
  const targetType = isReject ? undefined : (finalDecision.value as AttendanceType)

  submitLoading.value = true
  try {
    await finalReviewObjection(objection.id, {
      decision: isReject ? 'REJECTED' : 'APPROVED',
      final_type: targetType,
      comment: finalReasonNote.value.trim() || undefined,
      current_version: activeAttendance.value.current_version
    })

    if (isReject) {
      ElMessage.warning(`审核已驳回申诉，维持原考勤判定。`)
    } else {
      ElMessage.success(`审核通过，考勤认定为【${typeMap[targetType || ''] || targetType}】。`)
    }

    // 更新当前考勤快照
    try {
      const updatedAtt = await getAttendanceRecord(objection.attendance_record_id)
      attendanceMap.value[objection.attendance_record_id] = updatedAtt
    } catch {}

    await fetchObjections()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '审核提交失败'
    ElMessage.error(msg)
  } finally {
    submitLoading.value = false
  }
}

function changePage(next: number) {
  page.value = next
  activeIndex.value = 0
  fetchObjections()
}

// 查看证明材料附件
async function handleViewFile(fileId: string) {
  const popup = window.open('', '_blank')
  if (popup) popup.opener = null
  try {
    const url = await getFileUrl(fileId)
    if (popup) popup.location.href = url
    else ElMessage.warning('浏览器阻止了新窗口，请允许弹窗后重试')
  } catch (err: unknown) {
    popup?.close()
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取证明材料链接失败'
    ElMessage.error(msg)
  }
}

// ---------------- 证明材料：内嵌缩略图 + 灯箱预览 ----------------
const fileContext = computed(() => `${sessionStore.currentUser?.id || ''}:${activeObjection.value?.id || ''}`)
const { urls: fileUrlMap, getUrl: getFileUrl, invalidate: invalidateFileUrl } = useFileAccess(fileContext)
const fileImgError = ref<Record<string, boolean>>({})
const lightboxIndex = ref<number | null>(null)

// 选中异议变化时预取全部附件签名链接，用于内嵌图片预览
watch(
  fileContext,
  async (_, __, onCleanup) => {
    let cancelled = false
    onCleanup(() => { cancelled = true })
    lightboxIndex.value = null
    fileImgError.value = {}
    const fids = activeObjection.value?.file_ids || []
    await Promise.allSettled(
      fids.map(async fid => {
        try {
          if (!cancelled) await getFileUrl(fid)
        } catch {
          // 预取失败时回退为「新窗口打开」按钮
        }
      })
    )
  },
  { immediate: true }
)

const lightboxUrl = computed<string | null>(() => {
  const fids = activeObjection.value?.file_ids || []
  if (lightboxIndex.value === null) return null
  const fid = fids[lightboxIndex.value]
  return fid ? (fileUrlMap.value[fid] || null) : null
})

// 点击缩略图：图片可用则进灯箱，否则回退新窗口打开
async function handleProofClick(fid: string, index: number) {
  const context = fileContext.value
  try {
    await getFileUrl(fid)
    if (context !== fileContext.value) return
    fileImgError.value[fid] = false
    lightboxIndex.value = index
  } catch (err: unknown) {
    if (context !== fileContext.value) return
    ElMessage.error(err instanceof Error ? err.message : '获取证明材料链接失败')
  }
}

function closeLightbox() {
  lightboxIndex.value = null
}

function stepLightbox(delta: number) {
  const total = activeObjection.value?.file_ids?.length || 0
  if (lightboxIndex.value === null || total === 0) return
  lightboxIndex.value = (lightboxIndex.value + delta + total) % total
}

function onProofImgError(fid: string) {
  fileImgError.value[fid] = true
  invalidateFileUrl(fid)
}

function onLightboxImgError() {
  const fid = activeObjection.value?.file_ids?.[lightboxIndex.value ?? -1]
  if (fid) onProofImgError(fid)
}

function openLightboxOriginal() {
  const fid = activeObjection.value?.file_ids?.[lightboxIndex.value ?? -1]
  if (fid) void handleViewFile(fid)
}

watch(lightboxIndex, async index => {
  const fid = activeObjection.value?.file_ids?.[index ?? -1]
  if (!fid) return
  try {
    await getFileUrl(fid)
  } catch {
    // 打开材料时已有错误反馈；图片失败保留人工重试入口。
  }
})

function onGlobalKeydown(e: KeyboardEvent) {
  if (lightboxIndex.value === null) return
  if (e.key === 'Escape') closeLightbox()
  else if (e.key === 'ArrowLeft') stepLightbox(-1)
  else if (e.key === 'ArrowRight') stepLightbox(1)
}

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))

// ---------------- 审核判定选项（语义化卡片） ----------------
interface DecisionOption {
  value: 'LEAVE' | 'NORMAL' | 'LATE' | 'ABSENT' | 'REJECTED'
  label: string
  en: string
  desc: string
  tone: 'blue' | 'green' | 'amber' | 'red' | 'ink'
}

const decisionOptions: DecisionOption[] = [
  { value: 'LEAVE', label: '请假', en: 'LEAVE', desc: '合规缺勤，不计入异常', tone: 'blue' },
  { value: 'NORMAL', label: '正常出勤', en: 'NORMAL', desc: '计入实到，清零异常', tone: 'green' },
  { value: 'LATE', label: '迟到', en: 'LATE', desc: '计入异常 · 迟到人次', tone: 'amber' },
  { value: 'ABSENT', label: '旷课', en: 'ABSENT', desc: '计入异常 · 旷课人次', tone: 'red' },
  { value: 'REJECTED', label: '维持原判定', en: 'REJECT', desc: '驳回申诉，不改动考勤事实', tone: 'ink' }
]
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <h1>学生考勤异议处理</h1>
      <p class="sub">
        处理学生对考勤结果提出的异议申诉。学生负责人及以上权限一次审核即可生效。通过后按审核认定更新考勤，驳回保留原认定，所有结果保留操作账号与审核记录。
      </p>
    </header>

    <!-- 过滤器与状态切换 -->
    <div class="sub-nav-bar">
      <div class="sub-nav-tabs">
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'ALL' }"
          @click="statusFilter = 'ALL'"
        >
          全部审核
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'PENDING_FINAL' }"
          @click="statusFilter = 'PENDING_FINAL'"
        >
          待审核
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'APPROVED' }"
          @click="statusFilter = 'APPROVED'"
        >
          审核通过
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'REJECTED' }"
          @click="statusFilter = 'REJECTED'"
        >
          审核驳回
        </button>
      </div>

      <button class="btn btn-sm btn-ghost" @click="fetchObjections">⟳ 刷新异议列表</button>
    </div>

    <!-- 无数据状态 -->
    <div v-if="objections.length === 0" class="panel empty-box">
      <div class="empty-icon font-mono">∅</div>
      <h3 class="font-serif">暂无符合条件的考勤异议记录</h3>
      <p class="cell-sub">当前学期或当前筛选状态下没有任何学生提交考勤异议申诉。</p>
    </div>

    <!-- 主展示区：左侧列表 + 右侧详情 -->
    <div v-else class="obj-layout">
      <!-- 左栏：异议条目列表 -->
      <aside class="obj-list-panel">
        <div class="list-head">
          <span>异议申诉项</span>
          <span class="font-mono text-mute">共 {{ total }} 笔</span>
        </div>
        <div class="obj-items-scroll">
          <div
            v-for="(obj, idx) in objections"
            :key="obj.id"
            class="obj-card"
            :class="{ active: idx === activeIndex }"
            @click="activeIndex = idx"
          >
            <div class="card-top">
              <span class="font-mono card-id">OBJ-#{{ obj.id }}</span>
              <span
                class="tag"
                :class="{
                  'tag-red': obj.final_status === 'PENDING',
                  'tag-green': obj.final_status === 'APPROVED',
                  'tag-mute': obj.final_status === 'REJECTED'
                }"
              >
                {{
                  obj.final_status === 'PENDING'
                    ? '待审核'
                    : (obj.final_status === 'APPROVED' ? '审核通过' : '审核驳回')
                }}
              </span>
            </div>

            <div class="card-name font-serif">
              {{ obj.student_name || attendanceMap[obj.attendance_record_id]?.name || '学生 #' + obj.student_id }}
              <span class="card-class font-mono">
                {{ (obj.student_no || attendanceMap[obj.attendance_record_id]?.student_no) ? `(${obj.student_no || attendanceMap[obj.attendance_record_id]?.student_no})` : '' }}
              </span>
            </div>

            <div class="card-course cell-sub">
              {{ obj.course_name || attendanceMap[obj.attendance_record_id]?.task?.course_name_snapshot || '考勤记录 #' + obj.attendance_record_id }}
            </div>

            <div class="card-bottom">
              <span class="desired-tag font-mono">诉求：{{ typeMap[obj.desired_type] || obj.desired_type }}</span>
              <span class="card-time font-mono">{{ obj.created_at ? formatBeijingTime(obj.created_at, 'short') : '' }}</span>
            </div>
            <div v-if="obj.final_status !== 'PENDING'" class="cell-sub" style="margin-top: 6px">
              操作账号：{{ reviewerAccount(obj) }}
            </div>
          </div>
        </div>
        <div v-if="total > 50" class="list-head">
          <button class="btn btn-sm btn-ghost" :disabled="page <= 1 || loading" @click="changePage(page - 1)">上一页</button>
          <span>{{ page }} / {{ Math.ceil(total / 50) }}</span>
          <button class="btn btn-sm btn-ghost" :disabled="page * 50 >= total || loading" @click="changePage(page + 1)">下一页</button>
        </div>
      </aside>

      <!-- 右栏：申诉详情、三方事实与审核决策 -->
      <main v-if="activeObjection" class="obj-detail-panel">
        <div class="obj-head">
          <div>
            <div class="tag-row">
              <span
                class="tag"
                :class="{
                  'tag-red': activeObjection.final_status === 'PENDING',
                  'tag-green': activeObjection.final_status === 'APPROVED',
                  'tag-mute': activeObjection.final_status === 'REJECTED'
                }"
              >
                {{
                  activeObjection.final_status === 'PENDING'
                    ? '待审核 OBJ-#' + activeObjection.id
                    : (activeObjection.final_status === 'APPROVED' ? '审核通过' : '审核驳回') + ' OBJ-#' + activeObjection.id
                }}
              </span>
            </div>

            <div class="obj-title font-serif">
              {{ activeObjection.student_name || activeAttendance?.name || '学生 #' + activeObjection.student_id }}
              <span v-if="activeObjection.student_no || activeAttendance?.student_no" class="font-mono obj-sub-no">
                · {{ activeObjection.student_no || activeAttendance?.student_no }}
              </span>
              <span v-if="activeObjection.class_name || activeAttendance?.task?.class_name_snapshot" class="font-mono obj-sub-class">
                · {{ activeObjection.class_name || activeAttendance?.task?.class_name_snapshot }}
              </span>
            </div>
            <div class="cell-sub">
              针对 {{ activeObjection.date || activeAttendance?.task?.inspection_date || '' }} 《{{ activeObjection.course_name || activeAttendance?.task?.course_name_snapshot || '课程' }}》考勤认定提出异议
            </div>
          </div>

          <div class="obj-time">
            申诉提交时间<br />
            <span class="font-mono">{{ activeObjection.created_at ? formatBeijingTime(activeObjection.created_at) : '-' }}</span>
          </div>
        </div>

        <!-- 三方事实对比栅格 -->
        <div class="fact-grid">
          <!-- 1. 原考勤认定事实 -->
          <div class="fact">
            <span class="f-label">当前考勤认定</span>
            <div class="f-main">
              {{ activeAttendance?.task?.course_name_snapshot || '教学任务' }}
            </div>
            <div class="f-bad font-mono">
              当前判定：{{ typeMap[activeAttendance?.effective_type || ''] || activeAttendance?.effective_type || '-' }} · v{{ activeAttendance?.current_version || activeObjection.base_attendance_version }}
            </div>
            <div class="f-meta cell-sub font-mono">
              考勤记录 ID: {{ activeObjection.attendance_record_id }}
            </div>
          </div>

          <!-- 2. 学生申诉事由与证明 -->
          <div class="fact">
            <span class="f-label">学生申诉事由与证据</span>
            <div class="f-main">
              诉求改判为：<strong class="text-accent">{{ typeMap[activeObjection.desired_type] || activeObjection.desired_type }}</strong>
            </div>
            <div class="f-reason">
              “{{ activeObjection.reason || '无文字事由说明' }}”
            </div>
            <div v-if="activeObjection.file_ids && activeObjection.file_ids.length > 0" class="proof-zone">
              <div class="proof-grid">
                <button
                  v-for="(fid, i) in activeObjection.file_ids"
                  :key="fid"
                  type="button"
                  class="proof-thumb"
                  :title="'附件 ' + (i + 1) + ' · 点击放大预览'"
                  @click="handleProofClick(fid, i)"
                >
                  <img
                    v-if="fileUrlMap[fid] && !fileImgError[fid]"
                    :src="fileUrlMap[fid]"
                    :alt="'证明附件 ' + (i + 1)"
                    loading="lazy"
                    @error="onProofImgError(fid)"
                  />
                  <span v-else class="proof-fallback">
                    <AppIcon name="camera" :size="15" />
                    <span class="font-mono">附件 {{ i + 1 }}</span>
                  </span>
                  <span class="proof-zoom"><AppIcon name="search" :size="11" /></span>
                </button>
              </div>
              <div class="proof-hint">
                共 {{ activeObjection.file_ids.length }} 份证明材料 · 点击缩略图放大查看，支持 ← → 键切换
              </div>
            </div>
            <div v-else class="proof-empty">
              <AppIcon name="camera" :size="14" />
              <span>未附证明材料</span>
            </div>
          </div>

        </div>

        <!-- 审核决策与考勤更正区域 -->
        <div class="decision">
          <div class="d-head">
            <span class="d-title">异议审核（一次生效）</span>
            <span class="font-mono d-lock">
              考勤版本: v{{ activeAttendance?.current_version || activeObjection.base_attendance_version }}
            </span>
          </div>

          <!-- 若当前已审核，展示审核结论只读状态 -->
          <div v-if="activeObjection.final_status !== 'PENDING'" class="decision-result">
            <div class="dr-title">
              审核结果：
              <span v-if="activeObjection.final_status === 'APPROVED'" class="text-green font-serif">
                审核通过，认定为【{{ typeMap[activeObjection.final_attendance_type || ''] || activeObjection.final_attendance_type }}】
              </span>
              <span v-else class="text-red font-serif">
                审核维持原认定（驳回申诉）
              </span>
            </div>
            <div v-if="activeObjection.final_comment" class="dr-comment">
              审核决议备注：{{ activeObjection.final_comment }}
            </div>
            <div class="dr-meta font-mono cell-sub">
              操作账号: {{ reviewerAccount(activeObjection) }} · 审核时间: {{ activeObjection.final_reviewed_at ? formatBeijingTime(activeObjection.final_reviewed_at) : '-' }}
            </div>
          </div>

          <!-- 若未审核，展示操作控件 -->
          <div v-else-if="sessionStore.hasPermission('objection.final_review')">
            <div class="d-caption">
              <span class="d-rlabel">审核判定</span>
              <span class="d-wish-tip">
                学生诉求改判为 <b class="font-mono">{{ typeMap[activeObjection.desired_type] || activeObjection.desired_type }}</b>
              </span>
            </div>

            <div class="d-options">
              <button
                v-for="opt in decisionOptions"
                :key="opt.value"
                type="button"
                class="d-option"
                :class="[opt.tone, { selected: finalDecision === opt.value }]"
                @click="finalDecision = opt.value"
              >
                <span v-if="opt.value === activeObjection.desired_type" class="do-wish">学生诉求</span>
                <span class="do-check"><AppIcon name="check" :size="10" /></span>
                <span class="do-label">{{ opt.label }}</span>
                <span class="do-en font-mono">{{ opt.en }}</span>
                <span class="do-desc">{{ opt.desc }}</span>
              </button>
            </div>

            <div class="d-form">
              <input
                v-model="finalReasonNote"
                type="text"
                class="input"
                placeholder="审核备注（选填）"
                maxlength="512"
              />
              <button
                class="btn btn-dark"
                :disabled="submitLoading"
                @click="handleFinalReview"
              >
                {{ submitLoading ? '正在提交裁决…' : (finalDecision === 'REJECTED' ? '确认维持原判（驳回申诉）' : `提交审核并更正为【${typeMap[finalDecision]}】`) }}
              </button>
            </div>
          </div>
          <div v-else class="cell-sub">需要学生负责人或更高权限管理员审核。</div>
        </div>

        <!-- 处理流程时间线 -->
        <div class="timeline-box">
          <h4 class="tl-caption">业务流转时间线</h4>
          <div class="timeline">
            <!-- 步骤 1 -->
            <div class="tl-item done">
              <div class="tl-head">
                <span class="tl-title">学生发起考勤异议申请</span>
                <span class="tl-time font-mono">{{ activeObjection.created_at ? formatBeijingTime(activeObjection.created_at, 'short') : '' }}</span>
              </div>
              <div class="tl-body">学生提交异议理由与证明材料附件，诉求更正为【{{ typeMap[activeObjection.desired_type] }}】</div>
            </div>

            <!-- 步骤 2 -->
            <div v-if="activeObjection.initial_status !== 'PENDING'" class="tl-item done">
              <div class="tl-head">
                <span class="tl-title">历史初核记录</span>
                <span class="tl-time font-mono">
                  {{ activeObjection.initial_reviewed_at ? formatBeijingTime(activeObjection.initial_reviewed_at, 'short') : '' }}
                </span>
              </div>
              <div class="tl-body">
                <span v-if="activeObjection.initial_status === 'PASSED'">初核已通过：{{ activeObjection.initial_comment || '证明材料齐全属实' }}</span>
                <span v-else-if="activeObjection.initial_status === 'REJECTED'">初核未通过：{{ activeObjection.initial_comment || '材料不充分' }}</span>
                <span v-else>等待责任教师/班主任初核学生申诉事由与就诊证明真实性</span>
              </div>
            </div>

            <!-- 步骤 3 -->
            <div class="tl-item" :class="{ done: activeObjection.final_status !== 'PENDING', now: activeObjection.final_status === 'PENDING' }">
              <div class="tl-head">
                <span class="tl-title">异议审核（一次生效）</span>
                <span class="tl-time font-mono">
                  {{ activeObjection.final_reviewed_at ? formatBeijingTime(activeObjection.final_reviewed_at, 'short') : (activeObjection.final_status === 'PENDING' ? '进行中' : '') }}
                </span>
              </div>
              <div class="tl-body">
                <span v-if="activeObjection.final_status === 'APPROVED'">审核裁决通过，考勤更正为【{{ typeMap[activeObjection.final_attendance_type || ''] }}】</span>
                <span v-else-if="activeObjection.final_status === 'REJECTED'">审核驳回申诉，维持原考勤认定事实</span>
                <span v-else>等待学生负责人或更高权限管理员审核</span>
              </div>
            </div>

            <!-- 步骤 4 -->
            <div class="tl-item" :class="{ done: activeObjection.final_status !== 'PENDING' }">
              <div class="tl-head">
                <span class="tl-title">考勤事实与考勤数据同步</span>
              </div>
              <div class="tl-body">
                审核通过后自动写入新考勤版本，触发全院到课率与考勤详表即时更新
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- 证明材料灯箱 -->
    <teleport to="body">
      <div v-if="lightboxIndex !== null && activeObjection" class="lightbox" @click.self="closeLightbox">
        <button type="button" class="lb-close" title="关闭（Esc）" @click="closeLightbox">
          <AppIcon name="close" :size="17" />
        </button>
        <button
          v-if="(activeObjection.file_ids?.length || 0) > 1"
          type="button"
          class="lb-nav prev"
          title="上一份（←）"
          @click.stop="stepLightbox(-1)"
        >‹</button>
        <div class="lb-body">
          <div class="lb-frame">
            <img v-if="lightboxUrl" :src="lightboxUrl" alt="证明材料大图" @error="onLightboxImgError" />
            <div v-else class="lb-broken">附件暂无法内嵌预览</div>
          </div>
          <div class="lb-meta">
            <span class="font-mono">附件 {{ lightboxIndex + 1 }} / {{ activeObjection.file_ids?.length || 0 }}</span>
            <span class="lb-dot">·</span>
            <span>OBJ-#{{ activeObjection.id }}</span>
            <span class="lb-dot">·</span>
            <span>{{ activeObjection.student_name || '学生 #' + activeObjection.student_id }} 提交的申诉证明</span>
            <button
              v-if="lightboxUrl"
              type="button"
              class="lb-open"
              @click.stop="openLightboxOriginal"
            >新窗口打开原图</button>
          </div>
        </div>
        <button
          v-if="(activeObjection.file_ids?.length || 0) > 1"
          type="button"
          class="lb-nav next"
          title="下一份（→）"
          @click.stop="stepLightbox(1)"
        >›</button>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.sub-nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 16px;
}
.sub-nav-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.tab-btn {
  padding: 8px 16px;
  border: none;
  background: none;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-soft);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s ease;
}
.tab-btn:hover { color: var(--ink); }
.tab-btn.on {
  color: var(--ink);
  font-weight: 700;
  border-bottom-color: var(--ink);
}

.empty-box {
  text-align: center;
  padding: 64px 24px;
}
.empty-icon { font-size: 40px; color: var(--ink-mute); margin-bottom: 12px; }

/* 左右分栏布局 */
.obj-layout {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 24px;
  align-items: start;
}

/* 左侧列表 */
.obj-list-panel {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}
.list-head {
  padding: 12px 16px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
}
.obj-items-scroll {
  max-height: calc(100vh - 280px);
  overflow-y: auto;
}
.obj-card {
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  transition: background 0.15s;
}
.obj-card:hover { background: var(--paper-deep); }
.obj-card.active {
  background: #fdfbf7;
  border-left: 3px solid var(--ink);
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.card-id { font-size: 11px; color: var(--ink-mute); }
.card-name { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 4px; }
.card-class { font-size: 11px; color: var(--ink-soft); margin-left: 4px; }
.card-course { font-size: 12px; margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}
.desired-tag {
  background: var(--paper-deep);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--ink-soft);
}
.card-time { color: var(--ink-mute); }

/* 右侧详情 */
.obj-detail-panel {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 24px 28px;
}

.obj-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}
.tag-row { display: flex; gap: 8px; margin-bottom: 8px; }
.obj-title { font-size: 22px; font-weight: 600; margin-bottom: 6px; }
.obj-sub-no { font-size: 14px; color: var(--ink-soft); }
.obj-sub-class { font-size: 14px; color: var(--ink-mute); }
.obj-time { text-align: right; font-size: 12px; color: var(--ink-mute); line-height: 1.6; }

/* 三方事实栅格：申诉栏加宽以容纳证明缩略图 */
.fact-grid {
  display: grid;
  grid-template-columns: 0.85fr 1.3fr;
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 28px;
}
.fact { background: var(--paper); padding: 16px; }
.fact.ok { background: #f0fdf4; }
.fact.warn { background: #fff1f2; }
.f-label {
  display: block;
  font-size: 11px;
  color: var(--ink-mute);
  font-weight: 500;
  margin-bottom: 8px;
}
.ok-label { color: var(--green); }
.f-main { font-size: 13px; font-weight: 600; color: var(--ink); margin-bottom: 6px; }
.f-bad { font-size: 12px; color: var(--accent); font-weight: 600; margin-bottom: 4px; }
.f-reason { font-size: 12px; color: var(--ink-soft); line-height: 1.5; margin-bottom: 10px; font-style: italic; }

/* ---------- 证明材料缩略图 ---------- */
.proof-zone { margin-top: 2px; }
.proof-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.proof-thumb {
  position: relative;
  aspect-ratio: 4 / 3;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--paper-deep);
  padding: 0;
  cursor: zoom-in;
  overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.proof-thumb:hover {
  border-color: var(--ink);
  box-shadow: 0 2px 8px rgba(28, 27, 26, 0.12);
}
.proof-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.proof-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 100%;
  color: var(--ink-mute);
  font-size: 10px;
}
.proof-zoom {
  position: absolute;
  right: 5px;
  bottom: 5px;
  width: 20px;
  height: 20px;
  border-radius: 3px;
  background: rgba(28, 27, 26, 0.72);
  color: #faf8f5;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s;
}
.proof-thumb:hover .proof-zoom { opacity: 1; }
.proof-hint {
  margin-top: 7px;
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.5;
}
.proof-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  padding: 8px 10px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  color: var(--ink-mute);
  font-size: 11px;
}

/* ---------- 证明材料灯箱 ---------- */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(28, 27, 26, 0.92);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 32px;
}
.lb-body {
  max-width: min(880px, 86vw);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.lb-frame {
  max-height: 76vh;
  border: 1px solid rgba(250, 248, 245, 0.25);
  border-radius: var(--radius);
  overflow: hidden;
  background: rgba(250, 248, 245, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
}
.lb-frame img {
  max-width: 100%;
  max-height: 76vh;
  display: block;
  object-fit: contain;
}
.lb-broken {
  padding: 60px 40px;
  color: rgba(250, 248, 245, 0.6);
  font-size: 13px;
}
.lb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgba(250, 248, 245, 0.75);
  font-size: 12px;
  flex-wrap: wrap;
  justify-content: center;
}
.lb-dot { opacity: 0.4; }
.lb-open {
  margin-left: 10px;
  background: none;
  border: 1px solid rgba(250, 248, 245, 0.35);
  color: rgba(250, 248, 245, 0.85);
  font-size: 11px;
  font-family: inherit;
  padding: 4px 10px;
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.15s;
}
.lb-open:hover { background: rgba(250, 248, 245, 0.12); }
.lb-close {
  position: absolute;
  top: 20px;
  right: 24px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid rgba(250, 248, 245, 0.35);
  background: transparent;
  color: rgba(250, 248, 245, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s;
}
.lb-close:hover { background: rgba(250, 248, 245, 0.12); }
.lb-nav {
  flex-shrink: 0;
  width: 40px;
  height: 64px;
  border: 1px solid rgba(250, 248, 245, 0.3);
  border-radius: var(--radius);
  background: transparent;
  color: rgba(250, 248, 245, 0.85);
  font-size: 26px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s;
}
.lb-nav:hover { background: rgba(250, 248, 245, 0.12); }
.f-ok-note { font-size: 12px; color: var(--ink-soft); margin-bottom: 6px; }
.f-meta { font-size: 11px; margin-top: 6px; }
.initial-actions { display: flex; gap: 8px; margin-top: 8px; }

/* 审核裁决面板 */
.decision {
  border: 1px solid var(--line-strong);
  border-left: 3px solid var(--ink);
  padding: 20px 24px;
  background: var(--paper-deep);
  border-radius: var(--radius);
  margin-bottom: 28px;
}
.d-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.d-title { font-size: 14px; font-weight: 700; }
.d-lock { font-size: 11px; color: var(--ink-mute); }

.decision-result {
  padding: 12px 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.dr-title { font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.dr-comment { font-size: 13px; color: var(--ink); margin-bottom: 6px; }
.dr-meta { font-size: 11px; }

/* ---------- 审核判定选项卡片 ---------- */
.d-caption {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.d-rlabel { font-size: 12px; color: var(--ink-soft); font-weight: 700; letter-spacing: 0.02em; }
.d-wish-tip { font-size: 11px; color: var(--ink-mute); }
.d-wish-tip b { color: var(--accent); font-weight: 600; }

.d-options {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}
.d-option {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 12px 12px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--paper);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.d-option:hover { border-color: var(--ink); }
.d-option.selected {
  border-color: var(--ink);
  box-shadow: inset 0 0 0 1px var(--ink), 0 2px 8px rgba(28, 27, 26, 0.1);
  background: var(--paper);
}
.do-label { font-size: 14px; font-weight: 700; color: var(--ink); }
.do-en { font-size: 10px; color: var(--ink-mute); letter-spacing: 0.08em; }
.do-desc { font-size: 11px; color: var(--ink-mute); line-height: 1.5; margin-top: 4px; }

/* 语义色：顶部色条 + 选中态标签色 */
.d-option::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  border-radius: var(--radius) var(--radius) 0 0;
  background: var(--line);
  transition: background 0.15s;
}
.d-option.blue::before { background: var(--blue); }
.d-option.green::before { background: var(--green); }
.d-option.amber::before { background: var(--amber); }
.d-option.red::before { background: var(--accent); }
.d-option.ink::before { background: var(--ink-mute); }
.d-option.blue.selected .do-label { color: var(--blue); }
.d-option.green.selected .do-label { color: var(--green); }
.d-option.amber.selected .do-label { color: var(--amber); }
.d-option.red.selected .do-label { color: var(--accent); }

/* 选中勾选角标 */
.do-check {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  color: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.d-option.selected .do-check {
  background: var(--ink);
  border-color: var(--ink);
  color: var(--paper);
}

/* 「学生诉求」对齐角标 */
.do-wish {
  position: absolute;
  top: -8px;
  left: 8px;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 2px;
  background: var(--accent);
  color: #faf8f5;
  letter-spacing: 0.04em;
}

.input-required { border-color: var(--accent) !important; }
.input-required::placeholder { color: var(--accent); opacity: 0.75; }

.d-form { display: flex; gap: 12px; }
.d-form .input { flex: 1; }

/* 时间线 */
.timeline-box {
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.tl-caption {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--ink-soft);
}
.timeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: relative;
  padding-left: 20px;
}
.timeline::before {
  content: '';
  position: absolute;
  top: 6px;
  bottom: 6px;
  left: 6px;
  width: 2px;
  background: var(--line);
}
.tl-item {
  position: relative;
}
.tl-item::before {
  content: '';
  position: absolute;
  left: -20px;
  top: 4px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--line-strong);
  border: 2px solid var(--paper);
}
.tl-item.done::before { background: var(--green); }
.tl-item.now::before { background: var(--accent); }
.tl-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 2px;
}
.tl-title { color: var(--ink); }
.tl-time { color: var(--ink-mute); font-size: 11px; }
.tl-body { font-size: 12px; color: var(--ink-soft); line-height: 1.4; }

.text-accent { color: var(--accent); }
.text-green { color: var(--green); }
.text-red { color: #dc2626; }
.tag-mute { background: #e5e7eb; color: #4b5563; }
.tag-blue { background: #eff6ff; color: #1d4ed8; }

@media (max-width: 1100px) {
  .obj-layout { grid-template-columns: 1fr; }
  .fact-grid { grid-template-columns: 1fr; }
  .d-options { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 640px) {
  .d-options { grid-template-columns: repeat(2, 1fr); }
  .d-form { flex-direction: column; }
  .lb-nav { display: none; }
}
</style>
