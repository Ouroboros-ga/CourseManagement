import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as pinia from 'pinia'
import * as vue from 'vue'

function academicSession(listSemesters) {
  const imports = { pinia, vue, '../api/auth': {}, '../api/academic': { listSemesters },
    '../api/campus': { campusActionLabels: {} }, '../api/http': {}, '../api/workspaceHttp': {} }
  const source = readFileSync(new URL('../src/stores/session.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const module = { exports: {} }, storage = new Map()
  vm.runInNewContext(code, { module, exports: module.exports, console,
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    require: name => imports[name] })
  pinia.setActivePinia(pinia.createPinia())
  return module.exports.useSessionStore()
}
const semester = (id, status = 'ACTIVE') => ({ id, name: id, status, start_date: '2026-09-01', first_monday: '2026-08-31', total_weeks: 20 })

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
