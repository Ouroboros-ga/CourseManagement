import type { AssignmentPlan } from '../api/groupSampling'
import type { InspectionTaskItem } from '../api/tasks'

export function assignmentPlanRows(plan: AssignmentPlan, fallback: InspectionTaskItem[] = []) {
  const taskMap = new Map(fallback.map(task => [task.id, task]))
  const taskFields = (id: string) => {
    const task = plan.display?.tasks[id], legacy = taskMap.get(id)
    return {
      taskId: id,
      courseName: task?.course_name || legacy?.course_name_snapshot || '课程资料暂不可用',
      teachingClassName: task?.teaching_class_name || legacy?.class_name_snapshot || '—',
      classroom: task?.classroom || legacy?.classroom_snapshot || '地点未填写',
      inspectionDate: task?.inspection_date || legacy?.inspection_date || '',
      startPeriod: task?.start_period ?? legacy?.start_period,
      endPeriod: task?.end_period ?? legacy?.end_period,
    }
  }
  return {
    assigned: plan.assigned.map(item => {
      const person = plan.display?.volunteers[item.volunteer_user_id]
      return { ...taskFields(item.task_id), volunteerId: item.volunteer_user_id,
        volunteerName: person?.name || '姓名暂不可用', studentNo: person?.student_no || '',
        volunteerClass: person?.administrative_class_name || '', warningCodes: item.warning_codes }
    }),
    unassigned: plan.unassigned.map(item => ({ ...taskFields(item.task_id),
      reasonCode: item.reason_code, reason: item.message })),
  }
}
