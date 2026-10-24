import { shallowRef, watch, onScopeDispose } from 'vue'
import { objectionPrecheckApi, type ObjectionPrecheck, type PrecheckReviewFields } from '../api/objectionPrecheck'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context { key: string; collegeId: string; objectionId: string; enabled: boolean }
const message = (cause: unknown) => cause instanceof Error ? cause.message : '操作失败，请刷新核对'

export function useObjectionPrecheck(context: () => Context) {
  const snapshot = shallowRef<ObjectionPrecheck | null>(null)
  const loading = shallowRef(false), retrying = shallowRef(false), error = shallowRef('')
  const confirmed = shallowRef(false), manualReason = shallowRef('')
  const epoch = new ContextEpoch(() => JSON.stringify(context()))
  let disposed = false
  const eligible = () => !disposed && context().enabled && !!context().collegeId && !!context().objectionId
  function checked(value: ObjectionPrecheck): ObjectionPrecheck {
    if (!value || value.objection_id !== context().objectionId
      || !['NOT_STARTED', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'STALE'].includes(value.status)
      || !(value.job_id === null || (typeof value.job_id === 'string' && /^[1-9][0-9]{0,18}$/.test(value.job_id)))
      || typeof value.can_final_review !== 'boolean' || typeof value.manual_reason_required !== 'boolean'
      || typeof value.can_retry !== 'boolean') throw new Error('预审状态读取不完整，请刷新核对')
    const result = value.result
    const validResult = result && ['SUPPORT', 'NEEDS_INFORMATION', 'NEEDS_VERIFICATION'].includes(result.recommendation)
      && typeof result.summary === 'string' && Array.isArray(result.evidence) && Array.isArray(result.questions)
      && result.evidence.every(item => item && typeof item.observation === 'string'
        && ['APPLICATION', 'ATTENDANCE', 'PROOF'].includes(item.source))
      && result.questions.every(question => typeof question === 'string')
    if (!value.manual_reason_required && !validResult
      && (result || (value.status === 'SUCCEEDED' && value.is_current))) throw new Error('预审意见读取不完整，请刷新核对')
    return { ...value, result: validResult && value.is_current && value.status === 'SUCCEEDED' ? result : null }
  }
  async function refresh() {
    if (retrying.value) return
    const ticket = epoch.begin(), scope = context()
    snapshot.value = null; confirmed.value = false; error.value = ''
    if (!eligible()) return
    loading.value = true
    try {
      const value = await objectionPrecheckApi.get(scope.collegeId, scope.objectionId)
      if (ticket.isCurrent()) snapshot.value = checked(value)
    } catch (cause) {
      if (ticket.isCurrent()) error.value = message(cause)
    } finally { if (ticket.isLatest()) loading.value = false }
  }
  async function retry() {
    if (!eligible() || loading.value || retrying.value || !snapshot.value?.can_retry) return
    const ticket = epoch.begin(), scope = context(), expected = snapshot.value.job_id
    retrying.value = true; confirmed.value = false; error.value = ''
    try {
      const value = await objectionPrecheckApi.retry(scope.collegeId, scope.objectionId, { expected_job_id: expected })
      if (ticket.isCurrent()) snapshot.value = checked(value)
    } catch (cause) {
      if (ticket.isCurrent()) { snapshot.value = null; error.value = `${message(cause)}；请刷新核对，勿重复提交` }
    } finally { if (ticket.isLatest()) retrying.value = false }
  }
  function reviewFields(): PrecheckReviewFields {
    if (!context().enabled) return {}
    const value = snapshot.value
    if (!eligible() || loading.value || retrying.value || error.value || !value) throw new Error('请先读取并核对预审状态')
    if (!value.can_final_review) throw new Error(value.review_block_reason || '当前不可终审')
    if (!confirmed.value) throw new Error('请确认已核对本次预审状态与材料')
    const reason = manualReason.value.trim()
    if (value.manual_reason_required && !reason) throw new Error('请填写人工核验原因')
    if (reason.length > 512) throw new Error('人工核验原因不能超过512字')
    return { precheck_job_id: value.job_id, ...(value.manual_reason_required ? { manual_precheck_reason: reason } : {}) }
  }
  watch(() => JSON.stringify(context()), () => {
    epoch.invalidate(); snapshot.value = null; loading.value = false; retrying.value = false
    confirmed.value = false; manualReason.value = ''; error.value = ''
    void refresh()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { disposed = true; epoch.invalidate() })
  return { snapshot, loading, retrying, error, confirmed, manualReason, refresh, retry, reviewFields }
}
