import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function fixture() {
  const calls = []
  const pending = []
  class ApiError extends Error {
    constructor(status, payload) { super(payload.message); this.code = payload.code; this.status = status }
  }
  const code = ts.transpileModule(readFileSync(new URL('../src/api/workspaceHttp.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports,
    require: () => ({ ApiError, request: (...args) => { calls.push(args); return new Promise(resolve => pending.push(resolve)) } }) })
  return { ...module.exports, calls, pending }
}

test('workspace requests fail closed before context or without a selected college', async () => {
  const state = fixture()
  await assert.rejects(state.request('/api/v1/inspection-tasks'), { code: 'WORKSPACE_REQUIRED' })
  state.configureWorkspace({ academic_scoped: true, business_scoped: true, scheduling: true }, '')
  assert.throws(() => state.workspaceUrl('/api/v1/imports'), { code: 'WORKSPACE_REQUIRED' })
  assert.equal(state.calls.length, 0)
})

test('explicit workspace paths preserve BIGINT IDs, query strings and shared directories', () => {
  const state = fixture()
  state.configureWorkspace({ academic_scoped: true, business_scoped: true, scheduling: true }, '9007199254740993')
  assert.equal(state.workspaceUrl('/api/v1/imports?target=volunteer'), '/api/v1/colleges/9007199254740993/imports?target=volunteer')
  assert.equal(state.workspaceUrl('/api/v1/academic/course-schedules/12'), '/api/v1/colleges/9007199254740993/academic/schedules/12')
  assert.equal(state.workspaceUrl('/api/v1/academic/volunteer-qualifications'), '/api/v1/colleges/9007199254740993/academic/qualifications')
  assert.equal(state.workspaceUrl('/api/v1/academic/semesters/12/reset-preview'), '/api/v1/colleges/9007199254740993/academic/semesters/12/reset-preview')
  for (const url of ['/api/v1/academic/semesters?status=ACTIVE', '/api/v1/me/attendance', '/api/v1/files/12/access']) {
    assert.equal(state.workspaceUrl(url), url)
  }
})

test('late responses cannot populate a different college and legacy mode is explicit', async () => {
  const state = fixture()
  const mode = { academic_scoped: true, business_scoped: true, scheduling: true }
  state.configureWorkspace(mode, '10')
  const old = state.request('/api/v1/attendance?page=1')
  state.configureWorkspace(mode, '20')
  state.pending[0]({ items: ['old data'] })
  await assert.rejects(old, { code: 'WORKSPACE_CHANGED' })
  assert.equal(state.calls[0][0], '/api/v1/colleges/10/attendance?page=1')
  state.configureWorkspace({ academic_scoped: false, business_scoped: false, scheduling: false }, '')
  assert.equal(state.workspaceUrl('/api/v1/attendance'), '/api/v1/attendance')
})
