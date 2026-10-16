import { onUnmounted, reactive, shallowRef, watch } from 'vue'
import { collegeDeadlineApi, type CollegeDeadline, type DeadlineVersion } from '../api/collegeDeadlines'
import { useSessionStore } from '../stores/session'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'
import { formatBeijingTime } from '../utils/datetime'

export function useCollegeDeadlines(collegeId: () => string, canManage: () => boolean) {
  const session = useSessionStore()
  const context = () => `${identityContext(session.currentUser)}:${collegeId()}:${session.currentSemesterId}`
  const epoch = new ContextEpoch(context), historyEpoch = new ContextEpoch(context)
  const rows = shallowRef<CollegeDeadline[]>([]), history = shallowRef<DeadlineVersion[]>([])
  const historyDate = shallowRef(''), error = shallowRef(''), busy = shallowRef(false), writing = shallowRef(false)
  const drafts = reactive<Record<string, string>>({})
  let active = true
  onUnmounted(() => { active = false; epoch.invalidate(); historyEpoch.invalidate() })

  async function load() {
    const ticket = epoch.begin(), cid = collegeId(), sid = session.currentSemesterId
    historyEpoch.invalidate(); history.value = []; historyDate.value = ''
    rows.value = []; error.value = ''; Object.keys(drafts).forEach(key => delete drafts[key])
    if (!active || !cid || !sid || !session.currentUser) { busy.value = false; return }
    busy.value = true
    try {
      const result = await collegeDeadlineApi.list(cid, sid)
      if (!ticket.isCurrent()) return
      rows.value = result
      for (const row of result) drafts[row.inspection_date] = formatBeijingTime(row.deadline_at, 'minute').slice(11, 16)
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '截止配置读取失败'
    } finally { if (ticket.isLatest()) busy.value = false }
  }

  async function save(row: CollegeDeadline) {
    if (!active || writing.value || !canManage()) return false
    const current = rows.value.find(item => item.inspection_date === row.inspection_date && item.version === row.version)
    if (!current) { error.value = '记录已变化，请刷新后重试'; return false }
    const cid = collegeId(), sid = session.currentSemesterId, ticket = epoch.begin()
    const time = drafts[row.inspection_date]
    if (!/^\d{2}:\d{2}$/.test(time || '')) { error.value = '请填写有效的 HH:MM'; return false }
    writing.value = true; error.value = ''
    try {
      await collegeDeadlineApi.update(cid, sid, current.inspection_date, { time, lock_version: current.version })
      if (!ticket.isCurrent()) return false
      await load()
      return true
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '截止配置保存失败，请刷新版本'
      return false
    } finally { writing.value = false }
  }

  async function showHistory(day: string) {
    const ticket = historyEpoch.begin(), cid = collegeId(), sid = session.currentSemesterId
    historyDate.value = day; history.value = []
    try {
      const result = await collegeDeadlineApi.history(cid, sid, day)
      if (ticket.isCurrent()) history.value = result
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '历史读取失败'
    }
  }
  watch(context, load, { immediate: true })
  return { rows, drafts, history, historyDate, error, busy, writing, load, save, showHistory }
}
