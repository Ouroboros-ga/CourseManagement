import { listTasks, type InspectionTaskItem, type TaskListQuery } from '../api/tasks'
import { collectPages } from './collectPages'

export function isUnassignedTask(task: InspectionTaskItem): boolean {
  return !task.exception_reported_at && !['异常', 'EXCEPTION'].includes(task.status) && !task.canceled_at && task.status !== '已取消' && !task.assignment?.volunteer_user_id && !task.assigned_volunteer_id
}

/** Full filtered selection is an explicit batch action, independent of the visible 50-row page. */
export async function automaticAssignmentTargets(query: TaskListQuery, current: () => boolean,
  fetchPage: typeof listTasks = listTasks): Promise<InspectionTaskItem[]> {
  const rows = await collectPages(async (page, page_size) => {
    const result = await fetchPage({ ...query, needs_attention: 'unassigned', deleted_only: false, page, page_size })
    if (result.total > 500) throw new Error('单次排班最多500项未分配任务，请按日期或课程缩小筛选范围')
    return result
  }, current)
  return rows.filter(task => isUnassignedTask(task) && (query.needs_attention !== 'roster' || task.roster_review_required))
}
