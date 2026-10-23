import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function load(path, imports) {
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, { module, exports: module.exports, require: name => imports[name], Error, Map, Set })
  return module.exports
}
function setup(plan, confirm) {
  const session = { currentUser: { id: '1' }, workspaceCollegeId: '2', currentSemesterId: '3', workspace: { authorization_revision: 1 } }
  let commits = 0, message = '', review
  const api = { previewAssignment: async () => plan, commitAssignment: async () => { commits++; return { assigned_count: plan.assigned.length } } }
  const { confirmGroupPlan } = load('../src/composables/confirmGroupAssignment.ts', {
    vue: { h: (_tag, _props, text) => text },
    'element-plus': { ElMessageBox: { confirm: async value => { message = value; await confirm?.(session) }, alert: async value => { message = value } } },
    '../api/groupSampling': { groupSamplingApi: api }, '../stores/session': { useSessionStore: () => session },
    '../utils/assignmentWarnings': { assignmentWarnings: () => '' },
    './useAssignmentPlanDialog': { openAssignmentPlanReview: async value => {
      review = value
      message = `目标 ${value.targetCount} ${value.plan.unassigned.map(row => row.message).join('；')}`
      await confirm?.(session)
      return value.plan.assigned.length > 0
    } }
  })
  return { confirmGroupPlan, session, get review() { return review }, get commits() { return commits }, get message() { return message } }
}
const body = { semester_id: '3', task_ids: ['10', '11'] }
const plan = { id: 'p', revision: 'r', assigned: [{ task_id: '10', volunteer_user_id: '8', warning_codes: [] }],
  unassigned: [{ task_id: '11', reason_code: 'NO_QUALIFICATION', message: '本学期无有效志愿者资格' }] }

test('confirmation exposes target scope and unassigned reasons before committing', async () => {
  const state = setup(plan, () => { throw new Error('cancel') })
  await state.confirmGroupPlan('2', '4', body)
  assert.match(state.message, /目标.*2/)
  assert.match(state.message, /本学期无有效志愿者资格/)
  assert.equal(state.commits, 0)
})
test('changing semester while confirming prevents the old plan from committing', async () => {
  const state = setup(plan, session => { session.currentSemesterId = 'other' })
  await state.confirmGroupPlan('2', '4', body)
  assert.equal(state.commits, 0)
})
test('zero assignment plans show reasons without a misleading commit', async () => {
  const state = setup({ ...plan, assigned: [] })
  await state.confirmGroupPlan('2', '4', body)
  assert.equal(state.commits, 0)
  assert.match(state.message, /本学期无有效志愿者资格/)
})

test('resolved names and the exact frozen plan reach the structured dialog', async () => {
  const named = { ...plan, display: { group_name: '普通课查课组', semester_name: '2026秋', tasks: {},
    volunteers: { '8': { name: '张同学', student_no: '00123456', administrative_class_name: '计算机2601' } } } }
  const state = setup(named, () => { throw new Error('cancel') })
  await state.confirmGroupPlan('2', '4', body)
  assert.equal(state.review?.plan.display.volunteers['8'].name, '张同学')
  assert.equal(state.review?.targetCount, 2)
  assert.equal(state.commits, 0)
})

function targetLoader() {
  const { collectPages } = load('../src/utils/collectPages.ts', {})
  return load('../src/utils/automaticAssignmentTargets.ts', {
    '../api/tasks': {}, './collectPages': { collectPages }
  })
}
test('full filtered automatic scope includes the last-page Friday task, not only the first 50', async () => {
  const { automaticAssignmentTargets } = targetLoader()
  const rows = Array.from({ length: 98 }, (_, i) => ({ id: String(9007199254740993n + BigInt(i)),
    status: '待执行', inspection_date: i < 50 ? '2026-10-19' : '2026-10-23' }))
  const calls = []
  const result = await automaticAssignmentTargets({ semester_id: '3', week_no: 6, page: 1, keyword: '课程' }, () => true, async query => {
    calls.push(query)
    return { total: 98, items: rows.slice((query.page - 1) * 50, query.page * 50) }
  })
  assert.equal(result.length, 98)
  assert.equal(result[97].inspection_date, '2026-10-23')
  assert.equal(result[97].id, rows[97].id)
  assert.deepEqual(calls.map(c => c.page), [1, 2])
  assert.ok(calls.every(c => c.page_size === 50 && c.week_no === 6 && c.keyword === '课程' && c.needs_attention === 'unassigned'))
})
test('assigned/canceled tasks are skipped and oversized scopes are rejected', async () => {
  const { automaticAssignmentTargets, isUnassignedTask } = targetLoader()
  assert.equal(isUnassignedTask({ assignment: { volunteer_user_id: '8' } }), false)
  assert.equal(isUnassignedTask({ canceled_at: '2026-10-20', status: '已取消' }), false)
  await assert.rejects(automaticAssignmentTargets({}, () => true, async () => ({ items: [], total: 501 })), /最多500/)
})
test('scope change while reading later pages discards the plan input', async () => {
  const { automaticAssignmentTargets } = targetLoader()
  let current = true
  const result = await automaticAssignmentTargets({}, () => current, async () => {
    current = false
    return { items: [{ id: '10' }], total: 1 }
  })
  assert.equal(result.length, 0)
})


test('execution exceptions never enter automatic assignment, including compatibility states', () => {
  const { isUnassignedTask } = targetLoader()
  assert.equal(isUnassignedTask({ status: '异常' }), false)
  assert.equal(isUnassignedTask({ status: 'EXCEPTION' }), false)
  assert.equal(isUnassignedTask({ status: '待执行', exception_reported_at: '2026-10-23T10:00:00Z' }), false)
  assert.equal(isUnassignedTask({ status: '待执行' }), true)
})
