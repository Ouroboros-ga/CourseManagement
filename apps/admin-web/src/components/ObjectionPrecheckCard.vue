<script setup lang="ts">
import type { ObjectionPrecheck } from '../api/objectionPrecheck'

defineProps<{ snapshot: ObjectionPrecheck | null; loading: boolean; retrying: boolean; error: string }>()
defineEmits<{ refresh: []; retry: [] }>()
const labels: Record<string, string> = { NOT_STARTED: '尚未预审', QUEUED: '等待预审', RUNNING: '正在预审', SUCCEEDED: '预审完成', FAILED: '预审失败', STALE: '资料变化，建议已失效' }
const recommendations: Record<string, string> = { SUPPORT: '材料支持申诉', NEEDS_INFORMATION: '建议补充信息', NEEDS_VERIFICATION: '需要人工核验' }
const sources: Record<string, string> = { APPLICATION: '申请说明', ATTENDANCE: '考勤记录', PROOF: '证明材料' }
</script>

<template>
  <section class="precheck-card" aria-label="智能预审">
    <div class="precheck-heading">
      <h4>智能预审 <span v-if="snapshot">· {{ labels[snapshot.status] }}</span></h4>
      <button class="btn btn-sm" :disabled="loading || retrying" @click="$emit('refresh')">{{ loading ? '读取中…' : '刷新状态' }}</button>
    </div>
    <p class="precheck-note">预审意见供人工核验，正式考勤由教务管理员终审决定。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-else-if="snapshot">
      <template v-if="snapshot.is_current && snapshot.status === 'SUCCEEDED' && snapshot.result">
        <strong>{{ recommendations[snapshot.result.recommendation] }}</strong>
        <p>{{ snapshot.result.summary }}</p>
        <ul v-if="snapshot.result.evidence.length">
          <li v-for="(item, index) in snapshot.result.evidence" :key="index">
            <span>{{ sources[item.source] }}<template v-if="item.file_id"> #{{ item.file_id }}</template><template v-if="item.page"> · 第{{ item.page }}页</template>：</span>
            {{ item.observation }}<q v-if="item.quote">{{ item.quote }}</q>
          </li>
        </ul>
        <ul v-if="snapshot.result.questions.length"><li v-for="question in snapshot.result.questions" :key="question">{{ question }}</li></ul>
      </template>
      <p v-else-if="snapshot.status === 'QUEUED' || snapshot.status === 'RUNNING'">后台正在处理，可稍后刷新。尚未形成正式审核结论。</p>
      <p v-else-if="snapshot.status === 'FAILED' || snapshot.status === 'STALE'">当前没有可直接采用的预审意见，请重新预审或按要求记录人工核验原因。</p>
      <p v-if="snapshot.review_block_reason">{{ snapshot.review_block_reason }}</p>
      <button v-if="snapshot.can_retry" class="btn btn-sm" :disabled="loading || retrying" @click="$emit('retry')">{{ retrying ? '正在登记…' : snapshot.job_id ? '重新预审' : '发起预审' }}</button>
      <p v-else-if="snapshot.final_status === 'PENDING' && snapshot.retry_block_message" class="precheck-note">{{ snapshot.retry_block_message }}</p>
    </template>
  </section>
</template>

<style scoped>
.precheck-card { margin: 16px 0; padding: 16px; border: 1px solid var(--border-color, #dce2e8); border-radius: 8px; background: var(--bg-secondary, #f8fafc); overflow-wrap: anywhere; }
.precheck-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.precheck-heading h4 { margin: 0; font-size: 14px; }
.precheck-note { color: var(--text-secondary, #64748b); font-size: 12px; }
.precheck-card p, .precheck-card li { line-height: 1.7; white-space: pre-wrap; }
.precheck-card ul { padding-left: 20px; }
.precheck-card q { display: block; color: var(--text-secondary, #64748b); }
</style>
