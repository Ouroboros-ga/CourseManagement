import { groupSamplingApi } from '../api/groupSampling'
import type { InspectionTaskItem } from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { openAssignmentPlanReview } from './useAssignmentPlanDialog'

export async function confirmGroupPlan(collegeId: string, groupId: string, body: Parameters<typeof groupSamplingApi.previewAssignment>[2], options: {
  scopeLabel?: string; tasks?: InspectionTaskItem[]; isCurrent?: () => boolean
} = {}) {
  const session = useSessionStore()
  const context = () => `${session.currentUser?.id}:${session.workspaceCollegeId}:${session.workspace?.authorization_revision}:${session.currentSemesterId}`
  const captured = context()
  const current = () => captured === context() && (options.isCurrent?.() ?? true)
  if (!collegeId || !groupId || collegeId !== session.workspaceCollegeId) {
    throw new Error('任务缺少有效学院/执行组，请刷新工作区')
  }
  const plan = await groupSamplingApi.previewAssignment(collegeId, groupId, body)
  if (!current()) return null
  const warningCodes = plan.assigned.flatMap(item => item.warning_codes)
  let confirmed = false
  try {
    confirmed = await openAssignmentPlanReview({ plan, targetCount: body.task_ids.length,
      scopeLabel: options.scopeLabel || (body.assignments ? '人工指派的具体任务' : '本次明确选择的任务'),
      tasks: options.tasks, isCurrent: current })
  } catch { return null }
  if (!confirmed) return null
  if (!current()) return null
  const result = await groupSamplingApi.commitAssignment(collegeId, groupId, plan.id, {
    revision: plan.revision, confirmations: plan.assigned.filter(item => item.warning_codes.length)
  })
  return { ...result, operation_warning_codes: warningCodes }
}

export async function confirmGroupAssignment(task: InspectionTaskItem, userId: string, reason = '') {
  return confirmGroupPlan(task.college_id || '', task.group_id || '', {
    semester_id: task.semester_id, task_ids: [task.id], assignments: { [task.id]: userId }, reason
  })
}
