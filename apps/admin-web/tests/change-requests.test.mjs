import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
function load(path, imports = {}) {
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, { module, exports: module.exports, URLSearchParams, Error, require: name => imports[name] })
  return module.exports
}
const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }
function setup(fetch) {
  const session = vue.reactive({ currentUser: { id: '100' }, workspaceCollegeId: '1', currentSemesterId: '9007199254740993', workspace: { authorization_revision: 1 } })
  const { ContextEpoch } = load('../src/utils/contextEpoch.ts')
  const { useChangeRequests } = load('../src/composables/useChangeRequests.ts', {
    vue: { ...vue, onUnmounted: () => {} }, '../api/tasks': { listChangeRequests: fetch },
    '../stores/session': { useSessionStore: () => session }, '../utils/contextEpoch': { ContextEpoch }
  })
  const scope = vue.effectScope()
  return { session, state: scope.run(useChangeRequests), stop: () => scope.stop() }
}
test('change requests use current semester and reset to page one on status change', async () => {
  const calls = []
  const { state, stop } = setup(async query => { calls.push(query); return { items: [{ id: '1' }], total: 105 } })
  await flush()
  assert.equal(calls[0].semester_id, '9007199254740993')
  assert.equal(calls[0].status, 'PENDING')
  state.page.value = 2; await flush()
  state.status.value = 'REJECTED'; await flush()
  assert.equal(calls.at(-1).page, 1)
  assert.equal(calls.at(-1).status, 'REJECTED')
  stop()
})
test('late old-college response cannot replace the new workspace and failures stay visible', async () => {
  const pending = []
  const { state, session, stop } = setup(() => new Promise((resolve, reject) => pending.push({ resolve, reject })))
  session.workspaceCollegeId = '2'; await flush()
  pending[1].resolve({ items: [{ id: 'new' }], total: 1 }); await flush()
  pending[0].resolve({ items: [{ id: 'old' }], total: 1 }); await flush()
  assert.equal(state.rows.value[0].id, 'new')
  const reload = state.reload()
  pending[2].reject(new Error('读取失败')); await reload
  assert.equal(state.rows.value.length, 0)
  assert.equal(state.error.value, '读取失败')
  stop()
})
test('request list serializes server-side pages of fifty and preserves bigint semester', async () => {
  let url
  const { listChangeRequests } = load('../src/api/tasks.ts', { './workspaceHttp': { request: async value => { url = value; return { items: [], total: 0 } } } })
  await listChangeRequests({ semester_id: '9007199254740993', status: 'APPROVED', page: 2 })
  const query = new URLSearchParams(url.split('?')[1])
  assert.equal(query.get('page_size'), '50')
  assert.equal(query.get('semester_id'), '9007199254740993')
  assert.equal(query.get('status'), 'APPROVED')
  assert.equal(query.get('page'), '2')
})
