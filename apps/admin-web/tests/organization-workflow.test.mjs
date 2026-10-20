import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const module = { exports: {} }
const source = readFileSync(new URL('../src/utils/organizationReadiness.ts', import.meta.url), 'utf8')
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
  { module, exports: module.exports })
const { organizationReadiness, countEffectiveMembers, canPreviewOrganization } = module.exports
const group = { status: 'ACTIVE', starts_on: null, ends_on: null }
const configuration = { course_type_ids: ['morning', 'evening'], class_mode: 'ALL_AUTHORIZED' }
const context = { group, configuration, memberCount: 2, loaded: true, error: '', semesterOpen: true,
  schedulingEnabled: true, businessEnabled: true, date: '2026-10-20' }

test('unknown or failed reads never imply zero members or readiness', () => {
  for (const state of [{ loaded: false }, { error: 'forbidden' }, { memberCount: null }]) {
    const result = organizationReadiness({ ...context, ...state })
    assert.equal(result.ready, false)
    assert.equal(result.action, 'members')
  }
})

test('the next action follows scope, members and enabling order', () => {
  assert.equal(organizationReadiness({ ...context, configuration: null, memberCount: 0 }).action, 'rules')
  assert.equal(organizationReadiness({ ...context, memberCount: 0 }).action, 'members')
  assert.equal(organizationReadiness({ ...context, group: { ...group, status: 'DRAFT' } }).action, 'enable')
  assert.equal(organizationReadiness(context).ready, true)
})

test('platform gate and archived semester remain explicit blockers', () => {
  assert.equal(organizationReadiness({ ...context, schedulingEnabled: false }).ready, false)
  assert.match(organizationReadiness({ ...context, schedulingEnabled: false }).label, /未开放/)
  assert.equal(organizationReadiness({ ...context, semesterOpen: false }).ready, false)
})

test('group date limits and empty selected class scopes block readiness', () => {
  assert.equal(organizationReadiness({ ...context, group: { ...group, ends_on: '2026-10-19' } }).ready, false)
  assert.equal(organizationReadiness({ ...context, configuration: { ...configuration, class_mode: 'SPECIFIC', class_ids: [] } }).action, 'rules')
})

test('only active members of the selected term on the reference date count', () => {
  const rows = [
    { student_id: '9007199254740993', semester_id: 's', status: 'ACTIVE', effective_from: '2026-10-01', effective_to: '2026-10-21' },
    { student_id: '9007199254740993', semester_id: 's', status: 'ACTIVE', effective_from: '2026-10-01', effective_to: '2026-10-21' },
    { student_id: '2', semester_id: 's', status: 'ACTIVE', effective_from: '2026-10-01', effective_to: '2026-10-20' },
    { student_id: '3', semester_id: 'other', status: 'ACTIVE', effective_from: '2026-10-01', effective_to: '2026-10-21' },
    { student_id: '4', semester_id: 's', status: 'INACTIVE', effective_from: '2026-10-01', effective_to: '2026-10-21' }
  ]
  assert.equal(countEffectiveMembers(rows, 's', '2026-10-20'), 1)
})

test('current-date member count does not block previewing future inspection dates', () => {
  assert.equal(canPreviewOrganization({ ...context, memberCount: 0 }), true)
  assert.equal(canPreviewOrganization({ ...context, loaded: false }), false)
  assert.equal(canPreviewOrganization({ ...context, error: 'denied' }), false)
  assert.equal(canPreviewOrganization({ ...context, schedulingEnabled: false }), false)
})
