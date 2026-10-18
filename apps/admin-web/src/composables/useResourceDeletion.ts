import { ElMessageBox } from 'element-plus'
import { request } from '../api/http'
import { useSessionStore } from '../stores/session'

export interface DeletionImpact {
  revision: string; mode: 'PERMANENT' | 'RETAIN_HISTORY'; references: string[]
  blocking_task_ids: string[]; can_delete: boolean
}
export async function deleteManagedResource(cid: string, kind: 'groups' | 'course-types', row: { id: string; name: string; lock_version: number }, current: () => boolean) {
  const session = useSessionStore(), userId = session.currentUser?.id
  const isCurrent = () => current() && userId === session.currentUser?.id
  const path = `/api/v1/colleges/${encodeURIComponent(cid)}/${kind}/${encodeURIComponent(row.id)}`
  const plan = await request<DeletionImpact>(`${path}/deletion-impact`)
  if (!isCurrent()) throw new Error('身份或工作区已切换，请重新操作')
  if (!plan.can_delete) throw new Error(`仍有 ${plan.blocking_task_ids.length} 个待执行任务，请先取消或转组后再删除。`)
  const note = plan.mode === 'PERMANENT'
    ? '此记录尚未投入使用，将彻底删除，不能从已删除列表恢复。'
    : '将从日常管理移除并停止新业务使用，历史成员、考勤、照片、配置与审计保留，可在已删除列表恢复。已有专属授权不会随恢复自动续期。'
  await ElMessageBox.confirm(`删除“${row.name}”？${note}`, '确认删除方式', { type: 'warning', confirmButtonText: plan.mode === 'PERMANENT' ? '彻底删除' : '删除并保留历史' })
  if (!isCurrent()) throw new Error('身份或工作区已切换，请重新操作')
  return request(path, { method: 'DELETE', body: JSON.stringify({ lock_version: row.lock_version, deletion_revision: plan.revision }) })
}
