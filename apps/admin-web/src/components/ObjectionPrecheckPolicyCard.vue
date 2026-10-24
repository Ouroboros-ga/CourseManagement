<script setup lang="ts">
import { watch, onScopeDispose } from 'vue'
import { useObjectionPrecheckPolicy } from '../composables/useObjectionPrecheckPolicy'

const props = defineProps<{ collegeId: string; collegeName: string; contextKey: string; available: boolean; busy: boolean }>()
const emit = defineEmits<{ saved: []; savingChange: [saving: boolean] }>()
const { policy, loading, saving, error, notice, refresh, setEnabled } = useObjectionPrecheckPolicy(
  () => ({ key: props.contextKey, collegeId: props.collegeId, available: props.available }),
  () => emit('saved')
)
watch(saving, value => emit('savingChange', value), { flush: 'sync' })
onScopeDispose(() => emit('savingChange', false))
</script>

<template>
  <section class="precheck-policy-card" aria-label="学院申诉预审设置">
    <div class="policy-heading">
      <div><h3>申诉自动预审</h3><p>{{ collegeName }} · 学院统一设置，适用于各学期</p></div>
      <span v-if="policy" class="policy-readiness">{{ policy.configuration_ready ? '接入配置已就绪' : '接入配置未就绪，暂不可开启' }}</span>
    </div>
    <p class="policy-description">开启后，新提交的申诉先登记智能预审，最终仍由教务管理员核验。历史申诉需要在详情中手动发起预审。</p>
    <p v-if="policy?.enabled" class="policy-description">关闭不会立即终止已发起的处理，结果仍须核对有效性。</p>
    <p v-if="!available">当前账号或学院范围不可设置预审。</p>
    <div v-else class="policy-controls">
      <button type="button" role="switch" aria-label="自动预审新申诉"
        :aria-checked="policy?.enabled ?? false"
        :disabled="busy || loading || saving || !policy || (!policy.enabled && !policy.configuration_ready)"
        class="policy-switch" :class="{ enabled: policy?.enabled }" @click="setEnabled(!policy?.enabled)">
        <span class="switch-dot" />{{ saving ? '正在保存…' : loading ? '正在读取…' : policy ? (policy.enabled ? '已开启' : '已关闭') : '状态待核对' }}
      </button>
      <button class="btn btn-sm btn-ghost" :disabled="busy || loading || saving" @click="refresh">刷新预审设置</button>
    </div>
    <p v-if="error" class="policy-feedback policy-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="policy-feedback policy-success" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.precheck-policy-card { border: 1px solid var(--line); border-radius: 8px; background: var(--paper); padding: 18px 20px; margin: 16px 0; overflow-wrap: anywhere; }
.policy-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.policy-heading h3 { margin: 0; font-size: 15px; }
.policy-heading p, .policy-readiness { margin: 5px 0 0; color: var(--ink-mute); font-size: 12px; }
.policy-description { color: var(--ink-mute); font-size: 13px; line-height: 1.7; margin: 12px 0; }
.policy-controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.policy-switch { display: inline-flex; gap: 8px; align-items: center; border: 1px solid var(--line); border-radius: 20px; padding: 7px 13px; background: var(--paper); color: var(--ink); font: inherit; font-size: 13px; cursor: pointer; }
.switch-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ink-mute); }
.policy-switch.enabled { border-color: var(--green); color: var(--green); }
.policy-switch.enabled .switch-dot { background: var(--green); }
.policy-switch:disabled { cursor: default; opacity: .6; }
.policy-feedback { font-size: 13px; line-height: 1.6; margin: 8px 0 0; }
.policy-error { color: var(--red); }
.policy-success { color: var(--green); }
@media (max-width: 680px) { .precheck-policy-card { padding: 16px; } }
</style>
