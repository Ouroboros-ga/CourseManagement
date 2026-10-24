import { onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getConfigurationImpact, type ImpactKind } from '../api/campus'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'
import { useSessionStore } from '../stores/session'

export function useConfigurationImpact(collegeId: () => string) {
  const session = useSessionStore()
  const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${collegeId()}:${session.currentSemesterId}`)
  onUnmounted(() => epoch.invalidate())
  return async (kind: ImpactKind, id: string, semesterId = '', configurationOnly = false) => {
    const cid = collegeId(), ticket = epoch.begin()
    const impact = await getConfigurationImpact(cid, kind, id, semesterId, configurationOnly)
    if (!ticket.isCurrent()) throw new Error('账号、学院或学期上下文已变化，请重新操作')
    if (impact.retained_future_task_ids.length) {
      await ElMessageBox.confirm(
        `涉及 ${impact.retained_future_task_ids.length} 个未来任务。已有任务保留原规则、时间快照和受派；停用后停止新增排班，需要取消的任务请单独处理。确认保存？`,
        '确认未来任务影响', { type: 'warning' }
      )
    }
    if (!ticket.isCurrent()) throw new Error('账号、学院或学期上下文已变化，请重新操作')
    return impact.revision
  }
}
