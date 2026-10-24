import { shallowRef, watch, onScopeDispose } from 'vue'
import { autoChangePolicyApi, type AutoChangePolicy } from '../api/autoChangePolicy'
import type { VolunteerGroup } from '../api/campus'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context { key: string; collegeId: string; semesterId: string; enabled: boolean }

function checkedPolicy(value: AutoChangePolicy): AutoChangePolicy {
  if (!value || typeof value.enabled !== 'boolean' || !Number.isSafeInteger(value.version)
    || value.version < 0 || !(value.authorizer_user_id === null || typeof value.authorizer_user_id === 'string')) {
    throw new Error('自动换班设置读取不完整，请刷新后重试')
  }
  return value
}
const message = (error: unknown) => error instanceof Error ? error.message : '操作失败，请刷新设置后重试'

export function useAutoChangePolicy(context: () => Context) {
  const groups = shallowRef<VolunteerGroup[]>([])
  const selectedGroupId = shallowRef('')
  const policy = shallowRef<AutoChangePolicy | null>(null)
  const loadingGroups = shallowRef(false), loadingPolicy = shallowRef(false), saving = shallowRef(false)
  const error = shallowRef(''), groupError = shallowRef(''), notice = shallowRef('')
  const contextKey = () => JSON.stringify(context())
  const policyKey = () => JSON.stringify([contextKey(), selectedGroupId.value])
  const groupEpoch = new ContextEpoch(contextKey)
  const policyEpoch = new ContextEpoch(policyKey)
  const saveEpoch = new ContextEpoch(policyKey)
  let disposed = false

  function eligible() {
    const scope = context()
    return !disposed && scope.enabled && !!scope.collegeId && !!scope.semesterId
  }
  function hasGroup() {
    return eligible() && groups.value.some(group => group.id === selectedGroupId.value)
  }

  async function loadGroups() {
    const ticket = groupEpoch.begin()
    groups.value = []; selectedGroupId.value = ''; groupError.value = ''
    if (!eligible()) return
    loadingGroups.value = true
    const scope = context()
    try {
      const result = await autoChangePolicyApi.listGroups(scope.collegeId)
      if (!ticket.isCurrent()) return
      groups.value = result.filter(group => group.status === 'ACTIVE' && group.college_id === scope.collegeId)
    } catch (cause) {
      if (ticket.isCurrent()) groupError.value = message(cause)
    } finally {
      if (ticket.isLatest()) loadingGroups.value = false
    }
  }

  async function loadPolicy() {
    const ticket = policyEpoch.begin()
    policy.value = null; error.value = ''; notice.value = ''
    if (!hasGroup()) return
    loadingPolicy.value = true
    const scope = context(), gid = selectedGroupId.value
    try {
      const result = checkedPolicy(await autoChangePolicyApi.get(scope.collegeId, gid, scope.semesterId))
      if (ticket.isCurrent()) policy.value = result
    } catch (cause) {
      if (ticket.isCurrent()) error.value = message(cause)
    } finally {
      if (ticket.isLatest()) loadingPolicy.value = false
    }
  }

  async function setEnabled(enabled: boolean) {
    if (!hasGroup() || !policy.value || saving.value || loadingPolicy.value || policy.value.enabled === enabled) return
    const ticket = saveEpoch.begin(), scope = context(), gid = selectedGroupId.value
    const currentVersion = policy.value.version
    saving.value = true; error.value = ''; notice.value = ''
    try {
      const result = checkedPolicy(await autoChangePolicyApi.update(scope.collegeId, gid, {
        semester_id: scope.semesterId, enabled, current_version: currentVersion
      }))
      if (!ticket.isCurrent()) return
      policy.value = result
      notice.value = result.enabled ? '已开启：后续新申请按此策略处理' : '已关闭：后续申请由管理员处理'
    } catch (cause) {
      if (!ticket.isCurrent()) return
      policy.value = null
      error.value = `${message(cause)}；请刷新设置，核对是否已保存`
    } finally {
      if (ticket.isLatest()) saving.value = false
    }
  }

  watch(contextKey, () => {
    groupEpoch.invalidate(); policyEpoch.invalidate(); saveEpoch.invalidate()
    groups.value = []; selectedGroupId.value = ''; policy.value = null
    loadingGroups.value = false; loadingPolicy.value = false; saving.value = false
    error.value = ''; groupError.value = ''; notice.value = ''
    void loadGroups()
  }, { immediate: true, flush: 'sync' })
  watch(selectedGroupId, () => {
    policyEpoch.invalidate(); saveEpoch.invalidate()
    loadingPolicy.value = false; saving.value = false
    void loadPolicy()
  }, { flush: 'sync' })
  onScopeDispose(() => {
    disposed = true
    groupEpoch.invalidate(); policyEpoch.invalidate(); saveEpoch.invalidate()
  })
  return { groups, selectedGroupId, policy, loadingGroups, loadingPolicy, saving, error, groupError, notice,
    loadGroups, loadPolicy, setEnabled }
}
