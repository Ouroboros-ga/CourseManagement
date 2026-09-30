<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const reviewLoading = ref(false)

function handleApprove() {
  reviewLoading.value = true
  setTimeout(() => {
    reviewLoading.value = false
    ElMessage.success('审核通过！已形成当次有效考勤认定，考勤源修订号已递增至 rev_42。')
  }, 600)
}

function handleReject() {
  ElMessage.warning('已打开驳回说明录入框，驳回将保留提交事实与操作人审计。')
}
</script>

<template>
  <div>
    <header class="page-head">
      <div class="crumb">
        <span>REVIEW</span><em>●</em><span>待审核 3 笔</span><em>●</em><span>今日已审 12 笔</span>
      </div>
      <h1>查课提交管理审核</h1>
      <p class="sub">
        审核志愿者提交的现场考勤记录。审核通过后自动生成有效考勤事实，入库不可篡改并留痕审计。
      </p>
    </header>

    <div class="panel">
      <!-- 提交头信息 -->
      <div class="sub-head">
        <div>
          <span class="tag tag-amber">待审核 SUBMISSION-108</span>
          <div class="sub-title font-serif">计科2301-2302合班 · 数据结构与算法</div>
        </div>
        <div class="sub-meta">
          提交人：<strong>刘晨（志愿者）</strong><br />
          提交时间：<span class="font-mono">09-28 09:40</span>
        </div>
      </div>

      <div class="review-grid">
        <!-- 左栏：考勤事实 -->
        <section>
          <h4 class="sec-heading">
            现场清点考勤事实
            <button class="link-btn" @click="ElMessage.info('可调整应到人数快照并记录审计理由')">调整应到人数</button>
          </h4>

          <div class="mini-stats">
            <div class="mini-stat">
              <div class="l">应到人数</div>
              <div class="v font-mono">68</div>
            </div>
            <div class="mini-stat good">
              <div class="l">实到人数</div>
              <div class="v font-mono">66</div>
            </div>
            <div class="mini-stat">
              <div class="l">请假人数</div>
              <div class="v font-mono">0</div>
            </div>
            <div class="mini-stat bad">
              <div class="l">缺勤人数</div>
              <div class="v font-mono">2</div>
            </div>
          </div>

          <table class="tbl">
            <thead>
              <tr>
                <th>学号</th>
                <th>姓名</th>
                <th>行政班</th>
                <th>异常类型</th>
                <th>现场说明</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="cell-mono">20230101</td>
                <td class="cell-main">赵子龙</td>
                <td class="cell-sub">计科2301</td>
                <td><span class="tag tag-red">旷课</span></td>
                <td class="cell-sub">点名未到且无请假条</td>
              </tr>
              <tr>
                <td class="cell-mono">20230115</td>
                <td class="cell-main">马超</td>
                <td class="cell-sub">计科2302</td>
                <td><span class="tag tag-amber">迟到</span></td>
                <td class="cell-sub">开课15分钟后进入</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- 右栏：拍照留痕 -->
        <section>
          <h4 class="sec-heading">
            现场拍照留痕
            <span class="font-mono hmac">凭证剩余 13:40</span>
          </h4>

          <div class="photo-grid">
            <div class="photo-item">
              <div class="photo-ph"><span class="ph-icon">▣</span><span>纸质点名册核验拍照.jpg</span></div>
              <div class="photo-name">点名册照片.jpg</div>
            </div>
            <div class="photo-item">
              <div class="photo-ph"><span class="ph-icon">▣</span><span>讲台与黑板全景.jpg</span></div>
              <div class="photo-name">现场全景.jpg</div>
            </div>
          </div>

          <p class="photo-note">
            照片通过 HMAC 短时签名凭证访问，过期后需重新申请。所有查看行为均计入审计日志。
          </p>
        </section>
      </div>

      <!-- 操作栏 -->
      <div class="review-actions">
        <div class="hint">审核通过后自动推进考勤源修订号（rev_41 → rev_42），并提示周报生成最新版本。</div>
        <div class="acts">
          <button class="btn btn-danger-line" @click="handleReject">驳回提交</button>
          <button class="btn btn-dark" :disabled="reviewLoading" @click="handleApprove">
            {{ reviewLoading ? '正在提交…' : '审核通过，生成正式考勤' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sub-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 32px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}
.sub-title {
  font-size: 20px;
  font-weight: 600;
  margin-top: 12px;
}
.sub-meta {
  text-align: right;
  font-size: 12px;
  color: var(--ink-mute);
  line-height: 1.8;
}
.sub-meta strong { color: var(--ink); }
.sub-meta .font-mono { color: var(--ink); }

.review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 40px;
}

.sec-heading {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-mute);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.link-btn {
  border: none;
  background: none;
  font-size: 12px;
  font-family: inherit;
  color: var(--blue);
  cursor: pointer;
  text-transform: none;
  letter-spacing: 0;
  padding: 0;
}
.link-btn:hover { text-decoration: underline; }
.hmac { color: var(--accent); font-size: 11px; }

.mini-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  margin-bottom: 24px;
  border-radius: var(--radius);
  overflow: hidden;
}
.mini-stat { background: var(--paper); padding: 16px 12px; text-align: center; }
.mini-stat .l { font-size: 11px; color: var(--ink-mute); margin-bottom: 6px; }
.mini-stat .v { font-size: 20px; font-weight: 600; }
.mini-stat.bad .v { color: var(--accent); }
.mini-stat.good .v { color: var(--green); }

.photo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.photo-item {
  border: 1px solid var(--line);
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.2s;
  border-radius: var(--radius);
}
.photo-item:hover { border-color: var(--ink); }
.photo-ph {
  height: 140px;
  background: var(--paper-deep);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ink-mute);
  margin-bottom: 10px;
  gap: 8px;
  font-size: 11px;
}
.ph-icon { font-size: 24px; }
.photo-name { font-size: 12px; font-weight: 500; color: var(--ink-soft); }
.photo-note {
  margin-top: 16px;
  font-size: 12px;
  color: var(--ink-mute);
  line-height: 1.7;
}

.review-actions {
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}
.review-actions .hint {
  font-size: 12px;
  color: var(--ink-mute);
  max-width: 420px;
  line-height: 1.6;
}
.review-actions .acts { display: flex; gap: 12px; }

@media (max-width: 1100px) {
  .review-grid { grid-template-columns: 1fr; }
}
</style>
