import { ElMessageBox } from 'element-plus'
import { groupSamplingApi } from '../api/groupSampling'
import type { InspectionTaskItem } from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { assignmentWarnings } from '../utils/assignmentWarnings'

export async function confirmGroupPlan(collegeId: string, groupId: string, body: Parameters<typeof groupSamplingApi.previewAssignment>[2]) {
  const session = useSessionStore()
  const context = () => `${session.currentUser?.id}:${session.workspaceCollegeId}:${session.workspace?.authorization_revision}`
  const captured = context()
  if (!collegeId || !groupId || collegeId !== session.workspaceCollegeId) {
    throw new Error('任务缺少有效学院/执行组，请刷新工作区')
  }
  const plan = await groupSamplingApi.previewAssignment(collegeId, groupId, body)
  if (captured !== context()) return null
  const warningCodes = plan.assigned.flatMap(item => item.warning_codes)
  try {
    const rows = plan.assigned.map(item => `任务 #${item.task_id} → 账号 ${item.volunteer_user_id}：${assignmentWarnings(item.warning_codes) || '无规则警告'}`)
    await ElMessageBox.confirm(rows.join('\n') + `\n未能排班：${plan.unassigned.length}项。确认仅适用于以上具体任务和人员。`, '确认具体排班计划', { type: 'warning', confirmButtonText: '确认并派发' })
  } catch { return null }
  if (captured !== context()) return null
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
