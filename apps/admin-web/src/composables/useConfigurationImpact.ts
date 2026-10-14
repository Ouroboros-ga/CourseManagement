import { onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getConfigurationImpact, type ImpactKind } from '../api/campus'
import { ContextEpoch } from '../utils/contextEpoch'

export function useConfigurationImpact(collegeId: () => string) {
  const epoch = new ContextEpoch(collegeId)
  onUnmounted(() => epoch.invalidate())
  return async (kind: ImpactKind, id: string) => {
    const cid = collegeId(), ticket = epoch.begin()
    const impact = await getConfigurationImpact(cid, kind, id)
    if (!ticket.isCurrent()) throw new Error('学院上下文已变化，请重新操作')
    if (impact.retained_future_task_ids.length) {
      await ElMessageBox.confirm(
        `涉及 ${impact.retained_future_task_ids.length} 个未来任务。已有任务保留原规则、时间快照和受派；停用后停止新增排班，需要取消的任务请单独处理。确认保存？`,
        '确认未来任务影响', { type: 'warning' }
      )
    }
    if (!ticket.isCurrent()) throw new Error('学院上下文已变化，请重新操作')
    return impact.revision
  }
}
