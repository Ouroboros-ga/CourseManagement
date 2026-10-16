import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as pinia from 'pinia'
import * as vue from 'vue'

function academicSession(listSemesters, overrides = {}) {
  const imports = { pinia, vue, '../api/auth': {}, '../api/academic': { listSemesters },
    '../api/campus': { campusActionLabels: {} }, '../api/http': {}, '../api/workspaceHttp': {}, ...overrides }
  const source = readFileSync(new URL('../src/stores/session.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const module = { exports: {} }, storage = new Map()
  vm.runInNewContext(code, { module, exports: module.exports, console, Error,
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    require: name => imports[name] })
  pinia.setActivePinia(pinia.createPinia())
  return module.exports.useSessionStore()
}
const semester = (id, status = 'ACTIVE') => ({ id, name: id, status, start_date: '2026-09-01', first_monday: '2026-08-31', total_weeks: 20 })

test('refreshing college permissions keeps the current routing until the new snapshot is ready', async () => {
  let resolveMode
  const configurations = []
  const mode = { academic_scoped: true, business_scoped: true, scheduling: true }
  const college = { id: '2', status: 'ACTIVE', capabilities: ['academic.read'] }
  const session = academicSession(async () => ({ items: [] }), {
    '../api/http': { request: () => new Promise(resolve => { resolveMode = resolve }) },
    '../api/campus': { campusActionLabels: {}, listWorkspaces: async () => [college] },
    '../api/workspaceHttp': { configureWorkspace: (...args) => configurations.push(args) }
  })
  session.currentUser = { id: '1' }
  session.campusRuntime = mode
  session.workspaces = [college]
  session.selectWorkspace('2')
  configurations.length = 0
  const pending = session.refreshWorkspaces()
  assert.equal(configurations.length, 0, 'an ordinary permission refresh must not reset routing to legacy mode')
  resolveMode(mode)
  await pending
  assert.equal(configurations.length, 1)
  assert.equal(configurations[0][1], '2')
  assert.equal(configurations[0][0].business_scoped, true)
})

test('failed college permission refresh clears routing and visible authorization', async () => {
  const configurations = []
  const session = academicSession(async () => ({ items: [] }), {
    '../api/http': { request: async () => { throw new Error('permissions unavailable') } },
    '../api/workspaceHttp': { configureWorkspace: (...args) => configurations.push(args) }
  })
  session.currentUser = { id: '1' }
  session.workspaceCollegeId = '2'
  await session.refreshWorkspaces()
  assert.equal(session.workspaceCollegeId, '')
  assert.equal(session.workspaces.length, 0)
  assert.equal(session.campusRuntime, null)
  assert.equal(configurations.at(-1)[0], null)
  assert.equal(session.workspaceError, 'permissions unavailable')
})

test('explicit archived semester survives context reload', async () => {
  const session = academicSession(async () => ({ items: [semester('new'), semester('old', 'ARCHIVED')] }))
  await session.fetchAcademicContext('old')
  assert.equal(session.currentSemesterId, 'old')
})

test('an earlier academic request cannot replace a newer user-selected semester', async () => {
  let resolve
  const session = academicSession(() => new Promise(done => { resolve = done }))
  session.semesters = [semester('S1'), semester('S2')]
  const pending = session.fetchAcademicContext()
  session.setSemester('S2')
  resolve({ items: [semester('S1')] })
  await pending
  assert.equal(session.currentSemesterId, 'S2')
})

test('failed restore stays unauthenticated even in development and never guesses credentials', async () => {
  const logins = [], workspaces = []
  const imports = {
    pinia, vue,
    '../api/auth': { refresh: async () => null, login: async (...args) => { logins.push(args); throw new Error('login must be explicit') } },
    '../api/academic': {}, '../api/campus': { campusActionLabels: {} }, '../api/http': {},
    '../api/workspaceHttp': { configureWorkspace: (...args) => workspaces.push(args) }
  }
  const source = readFileSync(new URL('../src/stores/session.ts', import.meta.url), 'utf8').replaceAll('import.meta.env.DEV', 'true')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name] })
  pinia.setActivePinia(pinia.createPinia())
  const session = module.exports.useSessionStore()
  assert.equal(await session.restoreSession(), false)
  assert.equal(logins.length, 0)
  assert.equal(session.currentUser, null)
  assert.equal(session.isRestored, true)
})
