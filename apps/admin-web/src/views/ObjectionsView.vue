<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const finalDecision = ref('LEAVE')
const reasonNote = ref('')
const submitLoading = ref(false)

function handleFinalReview() {
  submitLoading.value = true
  setTimeout(() => {
    submitLoading.value = false
    ElMessage.success('终审通过！考勤事实已更正为【请假 (LEAVE)】，生成新考勤版本 v2 并写入操作人审计日志。')
  }, 600)
}
</script>

<template>
  <div>
    <header class="page-head">
      <div class="crumb">
        <span>OBJECTION</span><em>●</em><span>终审权限</span><em>●</em><span>1 笔待教师终审</span>
      </div>
      <h1>学生考勤异议处理</h1>
      <p class="sub">
        处理学生对考勤结果提出的异议申诉。终审判定改判将递增考勤版本、写入审计，并触发周报重新生成。
      </p>
    </header>

    <div class="obj-grid">
      <!-- 左栏：申诉详情与终审决策 -->
      <div class="panel">
        <div class="obj-head">
          <div>
            <span class="tag tag-red">待终审 OBJ-20260928-01</span>
            <div class="obj-title font-serif">赵子龙 · 计科2301</div>
            <div class="cell-sub">针对 09-28《数据结构与算法》旷课认定提出异议</div>
          </div>
          <div class="obj-time">
            申诉时间<br /><span class="font-mono">2026-09-29 14:22</span>
          </div>
        </div>

        <!-- 三方事实 -->
        <div class="fact-grid">
          <div class="fact">
            <span class="f-label">原考勤认定事实</span>
            <div class="f-main">09-28 数据结构与算法</div>
            <div class="f-bad">原判定：旷课 (ABSENT) · v1</div>
          </div>
          <div class="fact">
            <span class="f-label">学生申诉事由与证据</span>
            <div class="f-main">突发急性肠胃炎于校医院急诊</div>
            <button class="f-link" @click="ElMessage.info('通过短时 HMAC 签名链接预览证明图片')">
              ▣ 查看就诊病历与请假条.png
            </button>
          </div>
          <div class="fact ok">
            <span class="f-label ok-label">负责人初核意见</span>
            <div class="f-main">李明（负责人）初核通过</div>
            <div class="f-ok-note">“经与辅导员核实，急诊事实属实”</div>
          </div>
        </div>

        <!-- 终审决策 -->
        <div class="decision">
          <div class="d-head">
            <span class="d-title">教师终审决策与考勤更正</span>
            <span class="font-mono d-lock">需 attendance.correct 权限 · lock_version: 0 保护</span>
          </div>

          <div class="d-radios">
            <span class="d-rlabel">最终改判为：</span>
            <label class="d-radio">
              <input v-model="finalDecision" type="radio" value="LEAVE" />
              <span>请假 (LEAVE)</span>
            </label>
            <label class="d-radio">
              <input v-model="finalDecision" type="radio" value="PRESENT" />
              <span>正常出勤 (PRESENT)</span>
            </label>
            <label class="d-radio">
              <input v-model="finalDecision" type="radio" value="REJECTED" />
              <span>维持原判定（驳回）</span>
            </label>
          </div>

          <div class="d-form">
            <input
              v-model="reasonNote"
              type="text"
              class="input"
              placeholder="录入终审决议备注说明（选填，入库审计）…"
            />
            <button class="btn btn-dark" :disabled="submitLoading" @click="handleFinalReview">
              {{ submitLoading ? '正在提交…' : '提交终审并更正考勤（生成 v2）' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 右栏：处理流程 -->
      <div class="panel">
        <h4 class="panel-title" style="margin-bottom: 24px">处理流程</h4>
        <div class="timeline">
          <div class="tl-item done">
            <div class="tl-head">
              <span class="tl-title">学生提交申诉</span>
              <span class="tl-time">09-29 14:22</span>
            </div>
            <div class="tl-body">赵子龙提交异议申请与就诊证明材料</div>
          </div>
          <div class="tl-item done">
            <div class="tl-head">
              <span class="tl-title">负责人初核</span>
              <span class="tl-time">09-29 17:05</span>
            </div>
            <div class="tl-body">材料齐全，情况属实，建议更正为请假</div>
          </div>
          <div class="tl-item now">
            <div class="tl-head">
              <span class="tl-title">教师管理员终审</span>
              <span class="tl-time">进行中</span>
            </div>
            <div class="tl-body">等待 TEACHER_ADMIN 角色终审裁定</div>
          </div>
          <div class="tl-item">
            <div class="tl-head"><span class="tl-title">考勤事实修订</span></div>
            <div class="tl-body">终审通过后自动递增考勤版本并触发周报更新</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.obj-grid {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 32px;
  align-items: start;
}

.obj-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 28px;
  flex-wrap: wrap;
}
.obj-title { font-size: 20px; font-weight: 600; margin-top: 12px; margin-bottom: 4px; }
.obj-time {
  text-align: right;
  font-size: 12px;
  color: var(--ink-mute);
  line-height: 1.8;
}
.obj-time .font-mono { color: var(--ink); }

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
.fact.ok { background: var(--green-soft); }
.f-label {
  display: block;
  font-size: 11px;
  color: var(--ink-mute);
  font-weight: 500;
  margin-bottom: 8px;
}
.ok-label { color: var(--green); }
.f-main { font-size: 12px; font-weight: 600; color: var(--ink); margin-bottom: 6px; }
.f-bad { font-size: 12px; color: var(--accent); font-weight: 600; }
.f-link {
  border: none;
  background: none;
  padding: 0;
  font-size: 12px;
  font-family: inherit;
  color: var(--blue);
  font-weight: 600;
  cursor: pointer;
}
.f-link:hover { text-decoration: underline; }
.f-ok-note { font-size: 11px; color: var(--green); }

.decision {
  border: 1px solid var(--line-strong);
  border-left: 2px solid var(--ink);
  padding: 20px 24px;
  background: var(--paper-deep);
  border-radius: var(--radius);
}
.d-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.d-title { font-size: 13px; font-weight: 700; }
.d-lock { font-size: 10px; color: var(--ink-mute); }

.d-radios {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.d-rlabel { font-size: 12px; color: var(--ink-soft); font-weight: 500; }
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

@media (max-width: 1100px) {
  .obj-grid { grid-template-columns: 1fr; }
  .fact-grid { grid-template-columns: 1fr; }
}
</style>
