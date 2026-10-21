import { computed, shallowRef } from 'vue'
import type { AssignmentPlan } from '../api/groupSampling'
import type { InspectionTaskItem } from '../api/tasks'

export interface AssignmentPlanReview {
  plan: AssignmentPlan
  targetCount: number
  scopeLabel: string
  tasks?: InspectionTaskItem[]
  isCurrent: () => boolean
}
const pending = shallowRef<AssignmentPlanReview | null>(null)
let resolvePending: ((confirmed: boolean) => void) | undefined
export const assignmentPlanReview = computed(() => pending.value)

export function finishAssignmentPlanReview(confirmed: boolean) {
  const accepted = confirmed && !!pending.value?.plan.assigned.length && pending.value.isCurrent()
  const resolve = resolvePending
  resolvePending = undefined
  pending.value = null
  resolve?.(accepted)
}

export function openAssignmentPlanReview(review: AssignmentPlanReview): Promise<boolean> {
  finishAssignmentPlanReview(false)
  if (!review.isCurrent()) return Promise.resolve(false)
  return new Promise(resolve => { resolvePending = resolve; pending.value = review })
}
