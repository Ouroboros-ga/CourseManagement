import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import {
  groupMemberApi, type GroupMember, type GroupMemberApi, type GroupMemberKind,
  type MemberCandidate, type MemberImpact, type MemberStatus
} from '../api/groupMembers'

export interface GroupMemberContext {
  collegeId: () => string
  groupId: () => string
  semesterId: () => string
  canManage: () => boolean
  isSuper: () => boolean
}

export interface MemberDraft {
  student_id: string
  semester_id: string
  effective_from: string
  effective_to: string
  status: MemberStatus
}

interface PendingChange {
  kind: GroupMemberKind
  row: GroupMember
  impact: MemberImpact
  draft: MemberDraft
  revoke: boolean
  context: string
}

const blankDraft = (): MemberDraft => ({ student_id: '', semester_id: '', effective_from: '', effective_to: '', status: 'ACTIVE' })
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '成员操作失败'

export function useGroupMembers(context: GroupMemberContext, api: GroupMemberApi = groupMemberApi) {
  const members = shallowRef<GroupMember[]>([])
  const supports = shallowRef<GroupMember[]>([])
  const candidates = shallowRef<MemberCandidate[]>([])
  const draft = ref<MemberDraft>(blankDraft())
  const selectedCandidate = shallowRef<MemberCandidate | null>(null)
  const editing = shallowRef<GroupMember | null>(null)
  const creating = shallowRef(false)
  const pendingChange = shallowRef<PendingChange | null>(null)
  const confirmFutureAssignments = shallowRef(false)
  const keyword = shallowRef('')
  const candidateFrom = shallowRef('')
  const candidateTo = shallowRef('')
  const error = shallowRef('')
  const message = shallowRef('')
  const loading = shallowRef(false)
  const candidateLoading = shallowRef(false)
  const writing = shallowRef(false)
  const activeKind = shallowRef<GroupMemberKind>('members')
  const busy = computed(() => loading.value || candidateLoading.value || writing.value)

  const contextKey = () => [context.collegeId(), context.groupId(), context.semesterId(), context.canManage() ? 'manage' : 'read', context.isSuper() ? 'super' : 'standard'].join(':')
  let epoch = 0
  let loadEpoch = 0
  let candidateEpoch = 0
  let disposed = false
  const invalidate = () => { epoch++; loadEpoch++; candidateEpoch++ }
  const reset = () => {
    members.value = []; supports.value = []; candidates.value = []
    draft.value = blankDraft(); selectedCandidate.value = null; editing.value = null
    pendingChange.value = null; confirmFutureAssignments.value = false; creating.value = false
    keyword.value = ''; candidateFrom.value = ''; candidateTo.value = ''
    error.value = ''; message.value = ''; loading.value = false; candidateLoading.value = false; writing.value = false
  }

  watch(contextKey, () => {
    invalidate(); reset()
    if (context.collegeId() && context.groupId() && context.semesterId()) void load()
  }, { immediate: true, flush: 'sync' })

  onUnmounted(() => { disposed = true; invalidate() })

  async function load() {
    const cid = context.collegeId(), gid = context.groupId(), sid = context.semesterId()
    if (!cid || !gid || !sid) { members.value = []; supports.value = []; return }
    const ticket = ++loadEpoch, revision = epoch, key = contextKey()
    loading.value = true; error.value = ''
    try {
      const [memberRows, supportRows] = await Promise.all([
        api.list('members', cid, gid, sid),
        api.list('support-authorizations', cid, gid, sid)
      ])
      if (!disposed && ticket === loadEpoch && revision === epoch && key === contextKey()) {
        members.value = memberRows; supports.value = supportRows
      }
    } catch (caught) {
      if (!disposed && ticket === loadEpoch && revision === epoch && key === contextKey()) error.value = errorMessage(caught)
    } finally {
      if (!disposed && ticket === loadEpoch && revision === epoch && key === contextKey()) loading.value = false
    }
  }

  async function searchCandidates() {
    const cid = context.collegeId(), gid = context.groupId(), sid = context.semesterId()
    if (!cid || !gid || !sid || !candidateFrom.value || !candidateTo.value || !context.canManage() || writing.value) return
    const ticket = ++candidateEpoch, key = contextKey()
    candidateLoading.value = true; error.value = ''; candidates.value = []; selectedCandidate.value = null
    try {
      const rows = await api.candidates(cid, gid, sid, candidateFrom.value, candidateTo.value, keyword.value, activeKind.value === 'support-authorizations' && context.isSuper())
      if (!disposed && ticket === candidateEpoch && key === contextKey()) candidates.value = rows
    } catch (caught) {
      if (!disposed && ticket === candidateEpoch && key === contextKey()) error.value = errorMessage(caught)
    } finally {
      if (!disposed && ticket === candidateEpoch && key === contextKey()) candidateLoading.value = false
    }
  }

  function setKind(kind: GroupMemberKind) {
    activeKind.value = kind; candidates.value = []; selectedCandidate.value = null
    editing.value = null; creating.value = false; pendingChange.value = null; confirmFutureAssignments.value = false
  }

  function startCreate() {
    if (!context.canManage() || writing.value || (activeKind.value === 'support-authorizations' && !context.isSuper())) return
    editing.value = null; creating.value = true; pendingChange.value = null; selectedCandidate.value = null
    draft.value = { ...blankDraft(), semester_id: context.semesterId() }
    candidateFrom.value = ''; candidateTo.value = ''; candidates.value = []; error.value = ''; message.value = ''
  }

  function startEdit(row: GroupMember) {
    if (!context.canManage() || writing.value || (activeKind.value === 'support-authorizations' && !context.isSuper())) return
    editing.value = row; creating.value = false; selectedCandidate.value = null; pendingChange.value = null
    draft.value = { student_id: row.student_id, semester_id: row.semester_id, effective_from: row.effective_from, effective_to: row.effective_to, status: row.status }
    error.value = ''; message.value = ''
  }

  function cancelEdit() {
    editing.value = null; creating.value = false; selectedCandidate.value = null; pendingChange.value = null
    confirmFutureAssignments.value = false; draft.value = blankDraft(); candidates.value = []
  }

  async function create() {
    const cid = context.collegeId(), gid = context.groupId(), sid = context.semesterId(), key = contextKey()
    if (!context.canManage() || !cid || !gid || !sid || writing.value || !draft.value.effective_from || !draft.value.effective_to || !selectedCandidate.value) return
    if (activeKind.value === 'support-authorizations' && !context.isSuper()) return
    const ticket = epoch, kind = activeKind.value
    writing.value = true; error.value = ''; message.value = ''
    try {
      await api.create(kind, cid, gid, { student_id: selectedCandidate.value.id, semester_id: sid, effective_from: draft.value.effective_from, effective_to: draft.value.effective_to })
      if (ticket !== epoch || key !== contextKey() || disposed) return
      cancelEdit(); message.value = kind === 'members' ? '已新增组成员' : '已新增跨院支援授权'
      await load()
    } catch (caught) { if (ticket === epoch && key === contextKey() && !disposed) handleWriteError(caught) }
    finally { if (ticket === epoch && key === contextKey() && !disposed) writing.value = false }
  }

  async function prepareChange(row: GroupMember, revoke = false) {
    const cid = context.collegeId(), gid = context.groupId(), key = contextKey(), kind = activeKind.value
    if (!context.canManage() || !cid || !gid || writing.value || (kind === 'support-authorizations' && !context.isSuper())) return
    const ticket = epoch
    writing.value = true; error.value = ''; message.value = ''; pendingChange.value = null; confirmFutureAssignments.value = false
    if (revoke) {
      editing.value = row; creating.value = false
      draft.value = { student_id: row.student_id, semester_id: row.semester_id, effective_from: row.effective_from, effective_to: row.effective_to, status: 'INACTIVE' }
    }
    try {
      const impact = await api.impact(kind, cid, gid, row.id)
      if (ticket !== epoch || key !== contextKey() || disposed) return
      pendingChange.value = { kind, row, impact, draft: { ...draft.value, status: revoke ? 'INACTIVE' : draft.value.status }, revoke, context: key }
    } catch (caught) {
      if (ticket === epoch && key === contextKey() && !disposed) handleWriteError(caught)
    } finally { if (ticket === epoch && key === contextKey() && !disposed) writing.value = false }
  }

  async function applyChange() {
    const pending = pendingChange.value
    const cid = context.collegeId(), gid = context.groupId(), key = contextKey()
    if (!pending || pending.context !== key || !context.canManage() || !cid || !gid || writing.value) return
    if (pending.kind === 'support-authorizations' && !context.isSuper()) return
    if (pending.impact.retained_future_task_ids.length > 0 && !confirmFutureAssignments.value) {
      error.value = '请确认保留未来受派任务，并安排改派后再提交'
      return
    }
    const ticket = epoch, confirm = pending.impact.retained_future_task_ids.length > 0 && confirmFutureAssignments.value
    writing.value = true; error.value = ''; message.value = ''
    try {
      if (pending.revoke) {
        await api.revoke(pending.kind, cid, gid, pending.row.id, { lock_version: pending.impact.lock_version, confirm_future_assignments: confirm })
      } else {
        await api.update(pending.kind, cid, gid, pending.row.id, {
          lock_version: pending.impact.lock_version,
          effective_from: pending.draft.effective_from,
          effective_to: pending.draft.effective_to,
          status: pending.draft.status,
          confirm_future_assignments: confirm
        })
      }
      if (ticket !== epoch || key !== contextKey() || disposed) return
      pendingChange.value = null; confirmFutureAssignments.value = false; editing.value = null; creating.value = false
      message.value = pending.revoke ? '已停用该记录；未来受派任务保留，请安排改派' : '成员资料已更新'
      await load()
    } catch (caught) {
      if (ticket === epoch && key === contextKey() && !disposed) handleWriteError(caught)
    } finally { if (ticket === epoch && key === contextKey() && !disposed) writing.value = false }
  }

  function handleWriteError(caught: unknown) {
    if (typeof caught === 'object' && caught !== null && 'status' in caught && (caught as { status?: unknown }).status === 409) {
      editing.value = null; selectedCandidate.value = null; pendingChange.value = null
      confirmFutureAssignments.value = false; candidates.value = []; draft.value = blankDraft()
      error.value = '成员资料已变化，请刷新后重新选择和编辑'
      const refresh = load()
      error.value = '成员资料已变化，请刷新后重新选择和编辑'
      void refresh
      return
    }
    error.value = errorMessage(caught)
  }

  return {
    members, supports, candidates, draft, selectedCandidate, editing, creating, pendingChange,
    confirmFutureAssignments, keyword, candidateFrom, candidateTo, error, message,
    loading, candidateLoading, writing, busy, activeKind, load, searchCandidates,
    setKind, startCreate, startEdit, cancelEdit, create, prepareChange, applyChange
  }
}
