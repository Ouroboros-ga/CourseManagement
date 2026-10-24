<script setup lang="ts">
import { useAutoChangePolicy } from '../composables/useAutoChangePolicy'

const props = defineProps<{
  collegeId: string
  collegeName: string
  semesterId: string
  semesterName: string
  contextKey: string
  available: boolean
}>()
const {
  groups, selectedGroupId, policy, loadingGroups, loadingPolicy, saving,
  error, groupError, notice, loadGroups, loadPolicy, setEnabled
} = useAutoChangePolicy(() => ({
  key: props.contextKey, collegeId: props.collegeId,
  semesterId: props.semesterId, enabled: props.available
}))
</script>

<template>
  <section class="auto-change-card" aria-labelledby="auto-change-title">
    <div class="policy-heading">
      <div>
        <h3 id="auto-change-title">志愿者自动换班</h3>
        <p>{{ collegeName }} · {{ semesterName }} · 按组织单独设置</p>
      </div>
      <span class="policy-hint">无合适人选时保留原受派，转人工处理</span>
    </div>
    <p class="policy-description">开启后，新提交的换班申请将自动选择符合排班规则的空闲志愿者，并保留换班记录。已有申请仍由管理员处理。</p>
    <div v-if="!available" class="policy-feedback">当前范围暂不可设置自动换班。</div>
    <div v-else-if="groupError" class="policy-feedback policy-error" role="alert">
      {{ groupError }} <button class="btn btn-sm btn-ghost" @click="loadGroups">重新加载组织</button>
    </div>
    <div v-else class="policy-controls">
      <label class="group-picker">
        <span>执行组织</span>
        <select v-model="selectedGroupId" class="input" :disabled="loadingGroups || saving">
          <option value="">{{ loadingGroups ? '正在读取组织…' : '请选择组织' }}</option>
          <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option>
        </select>
      </label>
      <span v-if="!loadingGroups && !groups.length" class="policy-feedback">暂无可用的执行组织</span>
      <template v-if="selectedGroupId">
        <button
          type="button" role="switch" aria-label="自动处理新换班申请"
          :aria-checked="policy?.enabled ?? false"
          :disabled="!policy || loadingPolicy || saving"
          class="policy-switch" :class="{ enabled: policy?.enabled }"
          @click="setEnabled(!policy?.enabled)"
        ><span class="switch-dot" />{{ saving ? '正在保存…' : loadingPolicy ? '正在读取…' : policy ? (policy.enabled ? '已开启' : '已关闭') : '状态待核对' }}</button>
        <button class="btn btn-sm btn-ghost" :disabled="loadingPolicy || saving" @click="loadPolicy">刷新设置</button>
      </template>
    </div>
    <p v-if="error" class="policy-feedback policy-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="policy-feedback policy-success" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.auto-change-card { border: 1px solid var(--line); border-radius: 8px; background: var(--paper); padding: 18px 20px; margin-bottom: 18px; }
.policy-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.policy-heading h3 { margin: 0; font-size: 15px; font-weight: 600; }
.policy-heading p, .policy-hint { margin: 5px 0 0; color: var(--ink-mute); font-size: 12px; }
.policy-description { color: var(--ink-mute); font-size: 13px; line-height: 1.7; margin: 12px 0; }
.policy-controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.group-picker { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.group-picker select { width: 220px; max-width: 100%; }
.policy-switch { display: inline-flex; gap: 8px; align-items: center; border: 1px solid var(--line); border-radius: 20px; padding: 7px 13px; background: var(--paper); color: var(--ink); font: inherit; font-size: 13px; cursor: pointer; }
.switch-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ink-mute); }
.policy-switch.enabled { border-color: var(--green); color: var(--green); }
.policy-switch.enabled .switch-dot { background: var(--green); }
.policy-switch:disabled { cursor: default; opacity: .6; }
.policy-feedback { font-size: 13px; line-height: 1.6; margin: 8px 0 0; }
.policy-error { color: var(--red); }
.policy-success { color: var(--green); }
@media (max-width: 680px) {
  .auto-change-card { padding: 16px; }
  .policy-heading { align-items: flex-start; flex-direction: column; gap: 4px; }
  .group-picker { width: 100%; }
  .group-picker select { flex: 1; min-width: 0; }
}
</style>
