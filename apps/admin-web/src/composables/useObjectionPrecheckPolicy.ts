import { shallowRef, watch, onScopeDispose } from 'vue'
import { objectionPrecheckPolicyApi, type ObjectionPrecheckPolicy } from '../api/objectionPrecheck'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context { key: string; collegeId: string; available: boolean }
const message = (cause: unknown) => cause instanceof Error ? cause.message : '操作失败'
function checked(value: ObjectionPrecheckPolicy): ObjectionPrecheckPolicy {
  if (!value || typeof value.enabled !== 'boolean' || typeof value.configuration_ready !== 'boolean'
    || !Number.isSafeInteger(value.version) || value.version < 0) throw new Error('预审设置读取不完整，请刷新核对')
  return value
}

export function useObjectionPrecheckPolicy(context: () => Context, onSaved: (policy: ObjectionPrecheckPolicy) => void) {
  const policy = shallowRef<ObjectionPrecheckPolicy | null>(null)
  const loading = shallowRef(false), saving = shallowRef(false), error = shallowRef(''), notice = shallowRef('')
  const epoch = new ContextEpoch(() => JSON.stringify(context()))
  let disposed = false
  const eligible = () => !disposed && context().available && !!context().collegeId
  async function refresh() {
    if (saving.value) return
    const ticket = epoch.begin(), scope = context()
    policy.value = null; error.value = ''; notice.value = ''
    if (!eligible()) return
    loading.value = true
    try {
      const result = await objectionPrecheckPolicyApi.get(scope.collegeId)
      if (ticket.isCurrent()) policy.value = checked(result)
    } catch (cause) {
      if (ticket.isCurrent()) error.value = message(cause)
    } finally { if (ticket.isLatest()) loading.value = false }
  }
  async function setEnabled(enabled: boolean) {
    if (!eligible() || !policy.value || loading.value || saving.value || policy.value.enabled === enabled
      || (enabled && !policy.value.configuration_ready)) return
    const ticket = epoch.begin(), scope = context(), version = policy.value.version
    saving.value = true; error.value = ''; notice.value = ''
    try {
      const result = await objectionPrecheckPolicyApi.update(scope.collegeId, { enabled, current_version: version })
      if (!ticket.isCurrent()) return
      const value = checked(result)
      if (value.enabled !== enabled || value.version <= version) throw new Error('预审设置保存结果待核对')
      policy.value = value
      notice.value = enabled ? '已开启：后续新申诉按此设置登记预审' : '已关闭：后续新申诉不再自动发起预审'
      onSaved(value)
    } catch (cause) {
      if (ticket.isCurrent()) {
        policy.value = null
        error.value = `${message(cause)}；请刷新设置，核对是否已保存`
      }
    } finally { if (ticket.isLatest()) saving.value = false }
  }
  watch(() => JSON.stringify(context()), () => {
    epoch.invalidate(); policy.value = null; loading.value = false; saving.value = false
    error.value = ''; notice.value = ''; void refresh()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { disposed = true; epoch.invalidate() })
  return { policy, loading, saving, error, notice, refresh, setEnabled }
}
