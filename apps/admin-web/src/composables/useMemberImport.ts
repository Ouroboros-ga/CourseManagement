import { onScopeDispose, shallowRef, watch } from 'vue'
import { memberImportApi, type MemberImportForm, type MemberImportPreview, type MemberImportResult } from '../api/groupMembers'

export interface MemberImportContext { collegeId: string; groupId: string; userId: string; semesterId: string; allowed: boolean }
export function useMemberImport(context: () => MemberImportContext, api = memberImportApi) {
  const file = shallowRef<File | null>(null), preview = shallowRef<MemberImportPreview | null>(null)
  const busy = shallowRef(false), error = shallowRef(''), result = shallowRef<MemberImportResult | null>(null)
  let epoch = 0
  let reviewedBody = ''
  const key = () => JSON.stringify(context())
  const invalidate = () => { epoch++; reviewedBody = ''; preview.value = null; result.value = null; busy.value = false; error.value = '' }
  watch(key, () => { invalidate(); file.value = null })
  onScopeDispose(invalidate)
  function select(value: File | null) { invalidate(); file.value = value }
  async function run(body: MemberImportForm, commit = false) {
    const scope = context(), scopeKey = key(), selected = file.value, reviewed = preview.value
    if (!selected || !scope.allowed || busy.value || (commit && !reviewed?.can_commit)) return false
    if (commit && reviewedBody !== JSON.stringify(body)) { invalidate(); error.value = '有效期或资格选项已变化，请重新核对'; return false }
    const ticket = ++epoch
    busy.value = true; error.value = ''; result.value = null
    try {
      if (commit) {
        const saved = await api.commit(scope.collegeId, scope.groupId, selected, body, reviewed!.revision)
        if (ticket !== epoch || scopeKey !== key()) return false
        result.value = saved; preview.value = null; file.value = null
      } else {
        const parsed = await api.preview(scope.collegeId, scope.groupId, selected, body)
        if (ticket !== epoch || scopeKey !== key()) return false
        preview.value = parsed; reviewedBody = JSON.stringify(body)
      }
      return true
    } catch (e) {
      if (ticket === epoch && scopeKey === key()) { error.value = e instanceof Error ? e.message : '成员导入失败'; preview.value = null }
      return false
    } finally { if (ticket === epoch && scopeKey === key()) busy.value = false }
  }
  return { file, preview, busy, error, result, select, invalidate, run }
}
