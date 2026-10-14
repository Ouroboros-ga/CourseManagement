import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as pinia from 'pinia'
import * as vue from 'vue'

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
