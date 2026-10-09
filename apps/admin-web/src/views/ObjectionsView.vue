<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listObjections,
  initialReviewObjection,
  finalReviewObjection,
  getFileAccess,
  type ObjectionItem,
  type ObjectionFinalStatus,
  type ObjectionInitialStatus
} from '../api/objections'
import {
  getAttendanceRecord,
  type AttendanceRecord,
  type AttendanceType
} from '../api/attendance'

const sessionStore = useSessionStore()

const loading = ref(false)
const submitLoading = ref(false)
const initialLoading = ref(false)
const objections = ref<ObjectionItem[]>([])
const activeIndex = ref<number>(0)
const statusFilter = ref<string>('ALL') // ALL, PENDING_FINAL, PENDING_INITIAL, APPROVED, REJECTED
const attendanceMap = ref<Record<string, AttendanceRecord>>({})

// 终审表单
const finalDecision = ref<'LEAVE' | 'NORMAL' | 'LATE' | 'ABSENT' | 'REJECTED'>('LEAVE')
const finalReasonNote = ref('')

const typeMap: Record<string, string> = {
  NORMAL: '正常出勤',
  LEAVE: '请假',
  LATE: '迟到',
  ABSENT: '旷课'
}

async function fetchObjections() {
  loading.value = true
  try {
    let final_status: ObjectionFinalStatus | undefined = undefined
    let initial_status: ObjectionInitialStatus | undefined = undefined

    if (statusFilter.value === 'PENDING_FINAL') {
      final_status = 'PENDING'
    } else if (statusFilter.value === 'PENDING_INITIAL') {
      initial_status = 'PENDING'
    } else if (statusFilter.value === 'APPROVED') {
      final_status = 'APPROVED'
    } else if (statusFilter.value === 'REJECTED') {
      final_status = 'REJECTED'
    }

    const res = await listObjections({
      final_status,
      initial_status,
      page_size: 50
    })

    objections.value = res.items || []
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
    loading.value = false
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

const pendingFinalCount = computed(() => {
  return objections.value.filter(o => o.final_status === 'PENDING').length
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

// 初核通过/驳回
async function handleInitialReview(decision: 'PASSED' | 'REJECTED') {
  if (!activeObjection.value) return
  try {
    let comment: string | undefined = undefined
    if (decision === 'REJECTED') {
      const promptRes = await ElMessageBox.prompt(
        '请输入初核未通过原因说明：',
        '负责人初核判定',
        {
          confirmButtonText: '确定驳回初核',
          cancelButtonText: '取消',
          inputPattern: /\S+/,
          inputErrorMessage: '请填写初核理由'
        }
      )
      comment = promptRes.value
    } else {
      const promptRes = await ElMessageBox.prompt(
        '初核意见说明（选填）：',
        '负责人初核通过',
        {
          confirmButtonText: '初核通过',
          cancelButtonText: '取消',
          inputValue: '材料齐全，情况属实，建议终审予以改判'
        }
      )
      comment = promptRes.value
    }

    initialLoading.value = true
    await initialReviewObjection(activeObjection.value.id, {
      decision,
      comment
    })
    ElMessage.success(`异议 #${activeObjection.value.id} 初核已记录（${decision === 'PASSED' ? '初核通过' : '初核未通过'}）`)
    await fetchObjections()
  } catch (e) {
    // cancelled or error
  } finally {
    initialLoading.value = false
  }
}

// 终审提交
async function handleFinalReview() {
  if (!activeObjection.value) return
  if (!activeAttendance.value) {
    ElMessage.warning('正在加载考勤基准数据，请稍后重试')
    return
  }

  const isReject = finalDecision.value === 'REJECTED'
  const targetType = isReject ? undefined : (finalDecision.value as AttendanceType)

  if (isReject && !finalReasonNote.value.trim()) {
    ElMessage.warning('终审维持原判定/驳回申诉时，请填写决议备注理由')
    return
  }

  submitLoading.value = true
  try {
    await finalReviewObjection(activeObjection.value.id, {
      decision: isReject ? 'REJECTED' : 'APPROVED',
      final_type: targetType,
      comment: finalReasonNote.value.trim() || undefined,
      current_version: activeAttendance.value.current_version
    })

    if (isReject) {
      ElMessage.warning(`终审已驳回申诉，维持原考勤判定。`)
    } else {
      ElMessage.success(`终审通过！考勤事实已更正为【${typeMap[targetType || ''] || targetType}】，已生成新考勤版本并写入审计日志。`)
    }

    // 更新当前考勤快照
    try {
      const updatedAtt = await getAttendanceRecord(activeObjection.value.attendance_record_id)
      attendanceMap.value[activeObjection.value.attendance_record_id] = updatedAtt
    } catch {}

    await fetchObjections()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '终审提交失败'
    ElMessage.error(msg)
  } finally {
    submitLoading.value = false
  }
}

// 查看证明材料附件
async function handleViewFile(fileId: string) {
  try {
    const access = await getFileAccess(fileId)
    if (access && access.url) {
      window.open(access.url, '_blank')
    } else {
      ElMessage.warning('未能获取文件访问链接')
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取证明材料链接失败'
    ElMessage.error(msg)
  }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <h1>学生考勤异议处理</h1>
      <p class="sub">
        处理学生对考勤结果提出的异议申诉。终审裁决将同步更正考勤最终事实、递增版本编号、写入操作人审计日志并刷新学院周报。
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
          全部异议 ({{ objections.length }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'PENDING_FINAL' }"
          @click="statusFilter = 'PENDING_FINAL'"
        >
          待教师终审 ({{ pendingFinalCount }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'PENDING_INITIAL' }"
          @click="statusFilter = 'PENDING_INITIAL'"
        >
          待负责人初核
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'APPROVED' }"
          @click="statusFilter = 'APPROVED'"
        >
          终审已改判
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'REJECTED' }"
          @click="statusFilter = 'REJECTED'"
        >
          已维持/驳回
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
          <span class="font-mono text-mute">{{ objections.length }} 笔</span>
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
                    ? (obj.initial_status === 'PENDING' ? '待初核' : '待终审')
                    : (obj.final_status === 'APPROVED' ? '已改判' : '已驳回')
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
              <span class="card-time font-mono">{{ obj.created_at ? obj.created_at.substring(5, 16).replace('T', ' ') : '' }}</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右栏：申诉详情、三方事实与终审决策 -->
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
                    ? '待终审 OBJ-#' + activeObjection.id
                    : (activeObjection.final_status === 'APPROVED' ? '终审通过改判' : '终审驳回申诉') + ' OBJ-#' + activeObjection.id
                }}
              </span>
              <span v-if="activeObjection.initial_status !== 'PENDING'" class="tag tag-blue">
                负责人初核: {{ activeObjection.initial_status === 'PASSED' ? '初核通过' : '初核未通过' }}
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
            <span class="font-mono">{{ activeObjection.created_at ? activeObjection.created_at.substring(0, 19).replace('T', ' ') : '-' }}</span>
          </div>
        </div>

        <!-- 三方事实对比栅格 -->
        <div class="fact-grid">
          <!-- 1. 原考勤认定事实 -->
          <div class="fact">
            <span class="f-label">原考勤认定事实</span>
            <div class="f-main">
              {{ activeAttendance?.task?.course_name_snapshot || '教学任务' }}
            </div>
            <div class="f-bad font-mono">
              原判定：{{ typeMap[activeAttendance?.effective_type || ''] || activeAttendance?.effective_type || '-' }} · v{{ activeObjection.base_attendance_version }}
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
            <div class="f-files" v-if="activeObjection.file_ids && activeObjection.file_ids.length > 0">
              <button
                v-for="(fid, i) in activeObjection.file_ids"
                :key="fid"
                class="f-link"
                @click="handleViewFile(fid)"
              >
                ▣ 证明附件 {{ i + 1 }} (ID: {{ fid }})
              </button>
            </div>
            <div v-else class="cell-sub font-mono" style="font-size: 11px">
              无证明材料附件
            </div>
          </div>

          <!-- 3. 负责人初核意见 -->
          <div class="fact" :class="{ ok: activeObjection.initial_status === 'PASSED', warn: activeObjection.initial_status === 'REJECTED' }">
            <span class="f-label" :class="{ 'ok-label': activeObjection.initial_status === 'PASSED' }">
              负责人初核意见
            </span>
            <div class="f-main">
              <span v-if="activeObjection.initial_status === 'PASSED'">初核结论：审核通过</span>
              <span v-else-if="activeObjection.initial_status === 'REJECTED'">初核结论：审核未通过</span>
              <span v-else class="cell-sub">待初核审查</span>
            </div>
            <div class="f-ok-note">
              {{ activeObjection.initial_comment ? `“${activeObjection.initial_comment}”` : (activeObjection.initial_status === 'PENDING' ? '暂未填写初核意见' : '无详细说明') }}
            </div>
            <div v-if="activeObjection.initial_reviewed_by" class="f-meta cell-sub font-mono">
              初核人: {{ activeObjection.initial_reviewed_by }} · {{ activeObjection.initial_reviewed_at ? activeObjection.initial_reviewed_at.substring(0, 16).replace('T', ' ') : '' }}
            </div>
            <!-- 初核操作按钮 (仅在未初核时提供) -->
            <div v-if="activeObjection.initial_status === 'PENDING' && sessionStore.hasPermission('objection.initial_review')" class="initial-actions">
              <button class="btn btn-sm btn-ghost" :disabled="initialLoading" @click="handleInitialReview('PASSED')">
                ✓ 初核通过
              </button>
              <button class="btn btn-sm btn-ghost text-accent" :disabled="initialLoading" @click="handleInitialReview('REJECTED')">
                ✕ 不通过
              </button>
            </div>
          </div>
        </div>

        <!-- 终审决策与考勤更正区域 -->
        <div class="decision">
          <div class="d-head">
            <span class="d-title">教师管理员终审裁决</span>
            <span class="font-mono d-lock">
              考勤版本: v{{ activeAttendance?.current_version || activeObjection.base_attendance_version }} · 乐观锁与审计闭环保护
            </span>
          </div>

          <!-- 若当前已终审，展示终审结论只读状态 -->
          <div v-if="activeObjection.final_status !== 'PENDING'" class="decision-result">
            <div class="dr-title">
              终审结果：
              <span v-if="activeObjection.final_status === 'APPROVED'" class="text-green font-serif">
                终审通过并更正为【{{ typeMap[activeObjection.final_attendance_type || ''] || activeObjection.final_attendance_type }}】
              </span>
              <span v-else class="text-red font-serif">
                终审维持原认定（驳回申诉）
              </span>
            </div>
            <div v-if="activeObjection.final_comment" class="dr-comment">
              终审决议备注：{{ activeObjection.final_comment }}
            </div>
            <div class="dr-meta font-mono cell-sub">
              裁决操作人: {{ activeObjection.final_reviewed_by || '教师管理员' }} · 裁决时间: {{ activeObjection.final_reviewed_at ? activeObjection.final_reviewed_at.substring(0, 19).replace('T', ' ') : '-' }}
            </div>
          </div>

          <!-- 若未终审，展示操作控件 -->
          <div v-else>
            <div class="d-radios">
              <span class="d-rlabel">终审判定：</span>
              <label class="d-radio">
                <input v-model="finalDecision" type="radio" value="LEAVE" />
                <span>改判为 请假 (LEAVE)</span>
              </label>
              <label class="d-radio">
                <input v-model="finalDecision" type="radio" value="NORMAL" />
                <span>改判为 正常出勤 (NORMAL)</span>
              </label>
              <label class="d-radio">
                <input v-model="finalDecision" type="radio" value="LATE" />
                <span>改判为 迟到 (LATE)</span>
              </label>
              <label class="d-radio">
                <input v-model="finalDecision" type="radio" value="ABSENT" />
                <span>改判为 旷课 (ABSENT)</span>
              </label>
              <label class="d-radio">
                <input v-model="finalDecision" type="radio" value="REJECTED" />
                <span class="text-accent font-semibold">维持原判定（驳回申诉）</span>
              </label>
            </div>

            <div class="d-form">
              <input
                v-model="finalReasonNote"
                type="text"
                class="input"
                placeholder="录入终审决议备注说明（驳回时必填，通过时选填，将完整写入不可篡改审计日志）…"
              />
              <button
                class="btn btn-dark"
                :disabled="submitLoading"
                @click="handleFinalReview"
              >
                {{ submitLoading ? '正在提交裁决…' : (finalDecision === 'REJECTED' ? '确认维持原判（驳回申诉）' : `提交终审并更正为【${typeMap[finalDecision]}】`) }}
              </button>
            </div>
          </div>
        </div>

        <!-- 处理流程时间线 -->
        <div class="timeline-box">
          <h4 class="tl-caption">业务流转时间线</h4>
          <div class="timeline">
            <!-- 步骤 1 -->
            <div class="tl-item done">
              <div class="tl-head">
                <span class="tl-title">学生发起考勤异议申请</span>
                <span class="tl-time font-mono">{{ activeObjection.created_at ? activeObjection.created_at.substring(5, 16).replace('T', ' ') : '' }}</span>
              </div>
              <div class="tl-body">学生提交异议理由与证明材料附件，诉求更正为【{{ typeMap[activeObjection.desired_type] }}】</div>
            </div>

            <!-- 步骤 2 -->
            <div class="tl-item" :class="{ done: activeObjection.initial_status !== 'PENDING', now: activeObjection.initial_status === 'PENDING' }">
              <div class="tl-head">
                <span class="tl-title">负责人初核</span>
                <span class="tl-time font-mono">
                  {{ activeObjection.initial_reviewed_at ? activeObjection.initial_reviewed_at.substring(5, 16).replace('T', ' ') : (activeObjection.initial_status === 'PENDING' ? '待处理' : '') }}
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
                <span class="tl-title">教师管理员终审裁决</span>
                <span class="tl-time font-mono">
                  {{ activeObjection.final_reviewed_at ? activeObjection.final_reviewed_at.substring(5, 16).replace('T', ' ') : (activeObjection.final_status === 'PENDING' ? '进行中' : '') }}
                </span>
              </div>
              <div class="tl-body">
                <span v-if="activeObjection.final_status === 'APPROVED'">终审裁决通过，考勤更正为【{{ typeMap[activeObjection.final_attendance_type || ''] }}】</span>
                <span v-else-if="activeObjection.final_status === 'REJECTED'">终审驳回申诉，维持原考勤认定事实</span>
                <span v-else>等待具备 final_review 权限的管理员做出最终裁定</span>
              </div>
            </div>

            <!-- 步骤 4 -->
            <div class="tl-item" :class="{ done: activeObjection.final_status !== 'PENDING' }">
              <div class="tl-head">
                <span class="tl-title">考勤事实与周报快照同步</span>
              </div>
              <div class="tl-body">
                终审通过后自动写入新考勤版本，触发学院考勤周报标记最新修订号（behind_source 同步更新）
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
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
.sub-nav-tabs { display: flex; gap: 8px; }
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

/* 三方事实栅格 */
.fact-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
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
.f-reason { font-size: 12px; color: var(--ink-soft); line-height: 1.5; margin-bottom: 8px; font-style: italic; }
.f-files { display: flex; flex-direction: column; gap: 4px; }
.f-link {
  border: none;
  background: none;
  padding: 0;
  font-size: 12px;
  font-family: inherit;
  color: var(--blue);
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}
.f-link:hover { text-decoration: underline; }
.f-ok-note { font-size: 12px; color: var(--ink-soft); margin-bottom: 6px; }
.f-meta { font-size: 11px; margin-top: 6px; }
.initial-actions { display: flex; gap: 8px; margin-top: 8px; }

/* 终审裁决面板 */
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

.d-radios {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.d-rlabel { font-size: 12px; color: var(--ink-soft); font-weight: 600; }
.d-radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}
.d-radio input { accent-color: var(--ink); cursor: pointer; }

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
}
</style>
