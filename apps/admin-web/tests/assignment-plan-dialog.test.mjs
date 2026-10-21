import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path) {
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, { module, exports: module.exports, require: () => vue, Map, Promise })
  return module.exports
}
const taskId = '9007199254740993', userId = '9007199254740995'
const plan = { id: 'plan', assigned: [{ task_id: taskId, volunteer_user_id: userId, warning_codes: [] }],
  unassigned: [{ task_id: '22', reason_code: 'NO_QUALIFICATION', message: '执行日期无有效资格' }],
  display: { group_name: '普通课查课组', semester_name: '2026秋',
    tasks: { [taskId]: { course_name: '大学英语', teaching_class_name: '合班英语A', classroom: 'A201',
      inspection_date: '2026-10-23', start_period: 5, end_period: 6 },
    '22': { course_name: '高等数学', inspection_date: '2026-10-24' } },
    volunteers: { [userId]: { name: '李同学', student_no: '00123456', administrative_class_name: '计算机2601' } } } }

test('preview rows display names and business context while preserving exact string IDs', () => {
  const { assignmentPlanRows } = load('../src/utils/assignmentPlanRows.ts')
  const rows = assignmentPlanRows(plan)
  assert.equal(rows.assigned[0].taskId, taskId)
  assert.equal(rows.assigned[0].volunteerId, userId)
  assert.equal(rows.assigned[0].volunteerName, '李同学')
  assert.equal(rows.assigned[0].studentNo, '00123456')
  assert.equal(rows.assigned[0].volunteerClass, '计算机2601')
  assert.equal(rows.assigned[0].courseName, '大学英语')
  assert.equal(rows.unassigned[0].reason, '执行日期无有效资格')
  assert.equal(rows.unassigned[0].courseName, '高等数学')
})
test('older preview responses use known task labels and explicitly indicate unavailable names', () => {
  const { assignmentPlanRows } = load('../src/utils/assignmentPlanRows.ts')
  const rows = assignmentPlanRows({ ...plan, display: undefined }, [{ id: taskId, course_name_snapshot: '大学英语' }])
  assert.equal(rows.assigned[0].courseName, '大学英语')
  assert.equal(rows.assigned[0].volunteerName, '姓名暂不可用')
  assert.ok(!rows.assigned[0].volunteerName.includes(userId))
})
test('closing or replacing a dialog resolves false and clears its previous data', async () => {
  const { openAssignmentPlanReview, finishAssignmentPlanReview, assignmentPlanReview } = load('../src/composables/useAssignmentPlanDialog.ts')
  const first = openAssignmentPlanReview({ plan, isCurrent: () => true })
  const second = openAssignmentPlanReview({ plan: { ...plan, id: 'second' }, isCurrent: () => true })
  assert.equal(await first, false)
  assert.equal(assignmentPlanReview.value.plan.id, 'second')
  finishAssignmentPlanReview(false)
  assert.equal(await second, false)
  assert.equal(assignmentPlanReview.value, null)
})
test('only a current non-empty assignment plan can be confirmed', async () => {
  const { openAssignmentPlanReview, finishAssignmentPlanReview } = load('../src/composables/useAssignmentPlanDialog.ts')
  let current = true
  const expiredContext = openAssignmentPlanReview({ plan, isCurrent: () => current })
  current = false; finishAssignmentPlanReview(true)
  assert.equal(await expiredContext, false)
  const empty = openAssignmentPlanReview({ plan: { ...plan, assigned: [] }, isCurrent: () => true })
  finishAssignmentPlanReview(true); assert.equal(await empty, false)
  const accepted = openAssignmentPlanReview({ plan, isCurrent: () => true })
  finishAssignmentPlanReview(true); assert.equal(await accepted, true)
})
