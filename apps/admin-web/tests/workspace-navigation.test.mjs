import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function load(path) {
  const module = { exports: {} }
  const source = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(source, { module, exports: module.exports })
  return module.exports
}

const nav = load('../src/navigation/workspaceNavigation.ts')
const actor = (permissions = [], roles = []) => ({
  hasPermission: code => permissions.includes(code),
  hasAnyRole: (...codes) => codes.some(code => roles.includes(code))
})

test('seven primary entries share a stable order and distinct destinations', () => {
  assert.deepEqual(Array.from(nav.primaryPages, row => row.label), ['工作台', '教务资料', '学生与班级', '志愿者组织', '查课安排', '考勤与异议', '统计报表'])
  assert.equal(new Set(nav.primaryPages.map(row => row.path)).size, 7)
})

test('page and tab lifecycle distinguishes current files from semester participation', () => {
  assert.equal(nav.pageContextMode('students'), 'current')
  assert.equal(nav.pageContextMode('organizations', 'groups'), 'current')
  assert.equal(nav.pageContextMode('organizations', 'members'), 'semester')
  assert.equal(nav.pageContextMode('organizations', 'preparation'), 'semester')
  assert.equal(nav.pageContextMode('academic', 'types'), 'current')
  assert.equal(nav.pageContextMode('academic', 'timetable'), 'semester')
  assert.equal(nav.pageContextMode('inspections', 'tasks'), 'semester')
  assert.equal(nav.pageContextMode('attendance', 'objections'), 'semester')
})

test('resource limited managers see their relevant entries without gaining unrelated academic access', () => {
  const manager = actor(['volunteer.group.read', 'assignment.manage', 'inspection.read'])
  assert.equal(nav.canAccessPage('organizations', manager), true)
  assert.equal(nav.canAccessPage('inspections', manager), true)
  assert.equal(nav.canAccessPage('students', manager), false)
  assert.equal(nav.canAccessPage('school', manager), false)
  assert.equal(nav.canAccessPage('school', actor([], ['SUPER_ADMIN'])), true)
})

test('legacy task and objection bookmarks retain IDs, semester, and hash', () => {
  const task = nav.legacyDestination('tasks', { task_id: '9007199254740993', semester_id: 'S2' }, '#record')
  assert.equal(task.path, '/dashboard/inspections')
  assert.equal(task.query.tab, 'tasks')
  assert.equal(task.query.task_id, '9007199254740993')
  assert.equal(task.query.semester_id, 'S2')
  assert.equal(task.hash, '#record')
  assert.equal(nav.legacyDestination('objections', {}).query.tab, 'objections')
})

test('legacy timetable and import links go to academic pages, while dispatch stays in inspections', () => {
  assert.equal(nav.legacyDestination('schedule', { tab: 'master' }).path, '/dashboard/academic')
  assert.equal(nav.legacyDestination('schedule', { import: '1' }).query.tab, 'imports')
  assert.equal(nav.legacyDestination('schedule', {}).path, '/dashboard/inspections')
})

test('current file keys ignore remembered semester, semester business keys invalidate stale work', () => {
  const base = { userId: 'U1', collegeId: 'C1', authorizationRevision: 'R1', semesterId: 'S1' }
  assert.equal(nav.workspaceContextKey(base, 'current'), nav.workspaceContextKey({ ...base, semesterId: 'S2' }, 'current'))
  assert.notEqual(nav.workspaceContextKey(base, 'semester'), nav.workspaceContextKey({ ...base, semesterId: 'S2' }, 'semester'))
  assert.notEqual(nav.workspaceContextKey(base, 'current'), nav.workspaceContextKey({ ...base, userId: 'U2' }, 'current'))
  assert.notEqual(nav.workspaceContextKey(base, 'current'), nav.workspaceContextKey({ ...base, authorizationRevision: 'R2' }, 'current'))
})

test('操作日志只对持有 audit.read 的账号开放，教师管理员默认看不到', () => {
  assert.equal(nav.canAccessPage('audit', actor(['audit.read'])), true)
  assert.equal(nav.canAccessPage('audit', actor(['academic.manage', 'student.manage', 'inspection.read'])), false)
  assert.equal(nav.canAccessPage('audit', actor([])), false)
  assert.equal(nav.pageContextMode('audit'), 'current')
})
