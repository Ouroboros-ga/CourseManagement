<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listManagementSubmissions,
  reviewSubmission,
  type ManagementSubmissionItem
} from '../api/submissions'

const sessionStore = useSessionStore()

const loading = ref(false)
const reviewLoading = ref(false)
const submissions = ref<ManagementSubmissionItem[]>([])
const activeIndex = ref<number>(0)
const statusFilter = ref<string>('')

async function fetchSubmissions() {
  loading.value = true
  try {
    const res = await listManagementSubmissions({
      semester_id: sessionStore.currentSemesterId || undefined,
      review_status: (statusFilter.value || undefined) as any,
      page_size: 50
    })
    submissions.value = res.items || []
    if (activeIndex.value >= submissions.value.length) {
      activeIndex.value = 0
    }
  } catch (err: unknown) {
    console.error('获取待审核提交列表失败:', err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [sessionStore.currentSemesterId, statusFilter.value],
  () => {
    fetchSubmissions()
  }
)

onMounted(() => {
  fetchSubmissions()
})

const activeSubmission = computed<ManagementSubmissionItem | null>(() => {
  if (submissions.value.length === 0) return null
  return submissions.value[activeIndex.value] || null
})

const pendingCount = computed(() => {
  return submissions.value.filter(s => s.review_status === 'PENDING').length
})

async function handleApprove() {
  if (!activeSubmission.value) return
  reviewLoading.value = true
  try {
    await reviewSubmission(activeSubmission.value.id, { decision: 'APPROVED' })
    ElMessage.success(`提交 #${activeSubmission.value.id} 审核通过！考勤记录已固化落库。`)
    await fetchSubmissions()
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '审核失败'
    ElMessage.error(msg)
  } finally {
    reviewLoading.value = false
  }
}

async function handleReject() {
  if (!activeSubmission.value) return
  try {
    const { value: comment } = await ElMessageBox.prompt(
      '请输入驳回理由（该说明将反馈给小程序志愿者并记入审计）：',
      '驳回考勤提交',
      {
        confirmButtonText: '确认驳回',
        cancelButtonText: '取消',
        inputPattern: /\S+/,
        inputErrorMessage: '驳回理由不能为空'
      }
    )

    if (comment) {
      reviewLoading.value = true
      await reviewSubmission(activeSubmission.value.id, {
        decision: 'REJECTED',
        comment
      })
      ElMessage.warning(`提交 #${activeSubmission.value.id} 已驳回，理由：${comment}`)
      await fetchSubmissions()
    }
  } catch {
    // cancelled
  } finally {
    reviewLoading.value = false
  }
}

const typeMap: Record<string, string> = {
  'LATE': '迟到',
  'ABSENT': '旷课',
  'LEAVE': '请假'
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>SUBMISSIONS REVIEW</span>
        <em>●</em>
        <span>待审核 {{ pendingCount }} 笔</span>
        <em>●</em>
        <span>总记录 {{ submissions.length }} 笔</span>
      </div>
      <h1>查课提交管理审核</h1>
      <p class="sub">
        审核志愿者在小程序端提交的到课清点与异常学生名单。审核通过后自动生成不可篡改的最终考勤事实，驳回将完整保留提交记录与理由。
      </p>
    </header>

    <!-- 过滤器与批次切换 -->
    <div class="sub-nav-bar">
      <div class="sub-nav-tabs">
        <button
          class="tab-btn"
          :class="{ on: statusFilter === '' }"
          @click="statusFilter = ''"
        >
          全部提交 ({{ submissions.length }})
        </button>
        <button
          class="tab-btn"
          :class="{ on: statusFilter === 'PENDING' }"
          @click="statusFilter = 'PENDING'"
        >
          待审核
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

      <button class="btn btn-sm btn-ghost" @click="fetchSubmissions">⟳ 刷新提交列表</button>
    </div>

    <!-- 主展示区 -->
    <div v-if="submissions.length > 0 && activeSubmission" class="panel">
      <!-- 列表选择器 (如果有多条) -->
      <div class="submission-selector">
        <span class="label">切换审核记录：</span>
        <div class="selector-tags">
          <button
            v-for="(sub, idx) in submissions"
            :key="sub.id"
            class="sel-tag font-mono"
            :class="{ active: idx === activeIndex, 'is-pending': sub.review_status === 'PENDING' }"
            @click="activeIndex = idx"
          >
            #{{ sub.id }} - {{ sub.task?.course_name_snapshot || '任务' + sub.task_id }}
            <span v-if="sub.review_status === 'PENDING'" class="dot-amber"></span>
          </button>
        </div>
      </div>

      <!-- 提交头信息 -->
      <div class="sub-head">
        <div>
          <span
            class="tag"
            :class="{
              'tag-amber': activeSubmission.review_status === 'PENDING',
              'tag-green': activeSubmission.review_status === 'APPROVED',
              'tag-red': activeSubmission.review_status === 'REJECTED'
            }"
          >
            {{
              activeSubmission.review_status === 'PENDING'
                ? '待审核 SUBMISSION-' + activeSubmission.id
                : (activeSubmission.review_status === 'APPROVED' ? '已通过' : '已驳回') + ' SUBMISSION-' + activeSubmission.id
            }}
          </span>
          <div class="sub-title font-serif">
            {{ activeSubmission.task?.class_name_snapshot || '教学班' }} · 
            {{ activeSubmission.task?.course_name_snapshot || '未命名课程' }}
          </div>
        </div>
        <div class="sub-meta">
          提交志愿者 UID：<strong class="font-mono">{{ activeSubmission.volunteer_user_id }}</strong><br />
          提交时间：<span class="font-mono">{{ activeSubmission.submitted_at ? activeSubmission.submitted_at.substring(0, 19).replace('T', ' ') : '—' }}</span>
        </div>
      </div>

      <div class="review-grid">
        <!-- 左栏：考勤事实 -->
        <section>
          <h4 class="sec-heading">
            现场提交考勤事实
          </h4>

          <div class="mini-stats">
            <div class="mini-stat">
              <div class="l">到课清点结论</div>
              <div class="v font-mono" :style="{ color: activeSubmission.result === 'NORMAL' ? 'var(--green)' : 'var(--amber)' }">
                {{ activeSubmission.result === 'NORMAL' ? '全员到齐' : '存在异常' }}
              </div>
            </div>
            <div class="mini-stat bad">
              <div class="l">异常学生记录数</div>
              <div class="v font-mono">{{ activeSubmission.abnormal_items.length }}</div>
            </div>
            <div class="mini-stat">
              <div class="l">现场留痕照片数</div>
              <div class="v font-mono">{{ activeSubmission.file_ids.length }}</div>
            </div>
            <div class="mini-stat">
              <div class="l">提交尝试轮次</div>
              <div class="v font-mono">第 {{ activeSubmission.attempt_no }} 轮</div>
            </div>
          </div>

          <!-- 异常明细表 -->
          <div v-if="activeSubmission.abnormal_items.length > 0">
            <div class="table-sub-title">异常学生明细列表</div>
            <table class="tbl">
              <thead>
                <tr>
                  <th>学号</th>
                  <th>姓名</th>
                  <th>异常考勤认定</th>
                  <th>说明与备注</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="ab in activeSubmission.abnormal_items" :key="ab.student_id">
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
          <div v-else class="normal-tip">
            ✓ 志愿者报告：现场无迟到、早退、旷课或请假情况，本节课全勤应到。
          </div>
        </section>

        <!-- 右栏：现场留痕材料与审核决策 -->
        <section class="side-panel">
          <h4 class="sec-heading">现场证明留痕材料</h4>
          <div v-if="activeSubmission.file_ids.length > 0" class="photo-box">
            <div v-for="fid in activeSubmission.file_ids" :key="fid" class="photo-placeholder">
              <div class="photo-icon">📷</div>
              <div class="photo-id font-mono">证明文件 ID: #{{ fid }}</div>
            </div>
          </div>
          <div v-else class="no-photo-tip font-mono">
            未上传留痕照片（本课次未配置强制拍照）
          </div>

          <!-- 驳回记录信息（若已驳回） -->
          <div v-if="activeSubmission.review_comment" class="reject-box">
            <div class="r-title">驳回说明：</div>
            <div class="r-text">{{ activeSubmission.review_comment }}</div>
            <div class="r-meta font-mono">审核人 UID: {{ activeSubmission.reviewed_by }} · {{ activeSubmission.reviewed_at?.substring(0, 19).replace('T', ' ') }}</div>
          </div>

          <!-- 审核动作栏 -->
          <div class="decision-wrap">
            <div class="sec-heading">管理审核决策</div>
            <p class="dec-hint">
              审核决定将实时触发考勤认定与源修订号递增。一旦通过，学生端可查询考勤明细。
            </p>

            <div class="action-btn-row">
              <button
                class="btn btn-dark"
                :disabled="reviewLoading || activeSubmission.review_status === 'APPROVED'"
                @click="handleApprove"
              >
                {{ reviewLoading ? '处理中…' : '✓ 审核通过' }}
              </button>
              <button
                class="btn btn-outline-danger"
                :disabled="reviewLoading"
                @click="handleReject"
              >
                ✕ 驳回并填写原因
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- 无数据状态 -->
    <div v-else-if="!loading" class="empty-box">
      <div class="empty-icon">✓</div>
      <div class="empty-text">当前学期暂无符合筛选条件的查课提交记录</div>
      <div class="empty-sub">志愿者在微信小程序提交查课记录后，将实时出现在此工作台中</div>
    </div>
  </div>
</template>

<style scoped>
.sub-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}
.sub-nav-tabs { display: flex; gap: 8px; }
.tab-btn {
  padding: 6px 14px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 500;
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-btn.on {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}

.submission-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}
.submission-selector .label { font-size: 12px; color: var(--ink-mute); font-weight: 600; }
.selector-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.sel-tag {
  padding: 4px 10px;
  font-size: 11px;
  background: var(--paper);
  border: 1px solid var(--line);
  color: var(--ink-soft);
  border-radius: 2px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sel-tag.active {
  border-color: var(--blue);
  color: var(--blue);
  font-weight: 700;
}
.dot-amber { width: 6px; height: 6px; border-radius: 50%; background: var(--amber); }

.panel {
  background: var(--paper);
  border: 1px solid var(--line);
}
.sub-head {
  padding: 24px;
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.sub-title { font-size: 20px; font-weight: 700; margin-top: 8px; }
.sub-meta { font-size: 12px; color: var(--ink-mute); text-align: right; line-height: 1.6; }

.review-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 24px;
  padding: 24px;
}
.side-panel { border-left: 1px solid var(--line); padding-left: 24px; }

.sec-heading {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  margin-bottom: 16px;
}
.table-sub-title {
  font-size: 12px;
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--ink);
}

.mini-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.mini-stat {
  padding: 12px;
  background: var(--paper-deep);
  border: 1px solid var(--line);
}
.mini-stat .l { font-size: 10px; color: var(--ink-mute); margin-bottom: 4px; }
.mini-stat .v { font-size: 16px; font-weight: 700; }
.mini-stat.bad .v { color: var(--accent); }

.normal-tip {
  padding: 20px;
  background: var(--green-soft);
  color: var(--green);
  font-size: 13px;
  font-weight: 600;
  border-left: 3px solid var(--green);
}

.photo-box { display: flex; flex-direction: column; gap: 8px; margin-bottom: 24px; }
.photo-placeholder {
  padding: 16px;
  background: var(--paper-deep);
  border: 1px dashed var(--line-strong);
  text-align: center;
}
.photo-icon { font-size: 24px; margin-bottom: 4px; }
.photo-id { font-size: 11px; color: var(--ink-mute); }
.no-photo-tip {
  padding: 14px;
  background: var(--paper-deep);
  color: var(--ink-mute);
  font-size: 11px;
  margin-bottom: 24px;
  text-align: center;
}

.reject-box {
  padding: 14px;
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  margin-bottom: 24px;
}
.r-title { font-size: 11px; font-weight: 700; color: var(--accent); margin-bottom: 4px; }
.r-text { font-size: 13px; color: var(--ink); margin-bottom: 6px; }
.r-meta { font-size: 10px; color: var(--ink-mute); }

.decision-wrap { border-top: 1px solid var(--line); padding-top: 20px; }
.dec-hint { font-size: 11px; color: var(--ink-mute); line-height: 1.6; margin-bottom: 16px; }
.action-btn-row { display: flex; gap: 10px; }
.btn-outline-danger {
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
}
.btn-outline-danger:hover { background: var(--accent-soft); }

.empty-box {
  padding: 80px 20px;
  text-align: center;
  color: var(--ink-mute);
  background: var(--paper);
  border: 1px solid var(--line);
}
.empty-icon { font-size: 32px; color: var(--green); margin-bottom: 8px; }
.empty-text { font-size: 14px; font-weight: 600; color: var(--ink-soft); margin-bottom: 4px; }
.empty-sub { font-size: 12px; }

@media (max-width: 1000px) {
  .review-grid { grid-template-columns: 1fr; }
  .side-panel { border-left: none; border-top: 1px solid var(--line); padding-left: 0; padding-top: 24px; }
}
</style>
