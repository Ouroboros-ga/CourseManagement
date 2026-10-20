import { ElMessageBox } from 'element-plus'
import { h } from 'vue'
import { groupSamplingApi } from '../api/groupSampling'
import type { InspectionTaskItem } from '../api/tasks'
import { useSessionStore } from '../stores/session'
import { assignmentWarnings } from '../utils/assignmentWarnings'

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
  const taskMap = new Map((options.tasks || []).map(task => [task.id, task]))
  const label = (id: string) => {
    const task = taskMap.get(id)
    return `任务 #${id}${task ? ` ${task.inspection_date} 第${task.start_period}—${task.end_period}节 ${task.course_name_snapshot || ''}` : ''}`
  }
  const days = (options.tasks || []).map(task => task.inspection_date).sort()
  const rows = plan.assigned.map(item => `${label(item.task_id)} → 志愿者 #${item.volunteer_user_id}：${assignmentWarnings(item.warning_codes) || '无规则警告'}`)
  const text = [options.scopeLabel || (body.assignments ? '人工指派的具体任务' : '本次明确选择的任务'),
    `目标 ${body.task_ids.length} 项；拟派发 ${plan.assigned.length} 项；未分配 ${plan.unassigned.length} 项。`,
    days.length ? `日期：${days[0]} 至 ${days[days.length - 1]}` : '',
    ...rows,
    ...plan.unassigned.map(item => `${label(item.task_id)}：未分配，${item.message}`),
    '只有点击“确认并派发”才会保存上述排班；关闭或返回调整不会派发。'].filter(Boolean).join('\n')
  const message = h('div', { style: { whiteSpace: 'pre-wrap', maxHeight: '55vh', overflowY: 'auto' } }, text)
  const customStyle = { width: 'min(760px, 92vw)', maxWidth: '92vw' }
  if (!plan.assigned.length) {
    await ElMessageBox.alert(message, '本轮没有可派发的任务', { confirmButtonText: '返回调整', customStyle })
    return null
  }
  try {
    await ElMessageBox.confirm(message, '确认具体排班计划', { type: 'warning', confirmButtonText: '确认并派发', cancelButtonText: '返回调整', closeOnClickModal: false, customStyle })
  } catch { return null }
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
