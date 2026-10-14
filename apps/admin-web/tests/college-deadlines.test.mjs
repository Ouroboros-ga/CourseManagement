import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name] })
  return module.exports
}
function fixture() {
  const session = vue.reactive({ currentUser: { id: '1' }, currentSemesterId: '10' })
  const college = vue.ref('9007199254740993'), requests = [], writes = [], callbacks = []
  const api = {
    list: (...args) => new Promise(resolve => requests.push({ args, resolve })),
    update: (...args) => new Promise(resolve => writes.push({ args, resolve })),
    history: async () => []
  }
  const { useCollegeDeadlines } = load('../src/composables/useCollegeDeadlines.ts', {
    vue: { ...vue, onUnmounted: callback => callbacks.push(callback) },
    '../api/collegeDeadlines': { collegeDeadlineApi: api },
    '../stores/session': { useSessionStore: () => session },
    '../utils/contextEpoch': load('../src/utils/contextEpoch.ts', {}),
    '../utils/datetime': load('../src/utils/datetime.ts', {})
  })
  const scope = vue.effectScope()
  const state = scope.run(() => useCollegeDeadlines(() => college.value, () => true))
  return { session, college, requests, writes, state, stop: () => { callbacks.forEach(cb => cb()); scope.stop() } }
}
const row = { inspection_date: '2026-10-15', deadline_at: '2026-10-15T14:00:00Z', version: 7, task_count: 4 }
const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }

test('late deadlines from another semester never populate the selected workspace', async () => {
  const f = fixture()
  try {
    f.session.currentSemesterId = '11'; await flush()
    f.requests[1].resolve([{ ...row, version: 8 }]); await flush()
    f.requests[0].resolve([row]); await flush()
    assert.equal(f.state.rows.value[0].version, 8)
    assert.equal(f.state.drafts[row.inspection_date], '22:00')
  } finally { f.stop() }
})

test('deadline writes freeze college, semester, HHMM and actual version before a context change', async () => {
  const f = fixture()
  try {
    f.requests[0].resolve([row]); await flush()
    f.state.drafts[row.inspection_date] = '23:15'
    const pending = f.state.save(vue.reactive(f.state.rows.value[0])); await flush()
    assert.equal(f.writes[0].args[0], '9007199254740993')
    assert.equal(f.writes[0].args[1], '10')
    assert.equal(f.writes[0].args[3].lock_version, 7)
    assert.equal(f.writes[0].args[3].time, '23:15')
    f.college.value = '2'; await flush()
    f.writes[0].resolve({ ...row, version: 8 }); await pending
    assert.equal(f.state.rows.value.length, 0)
    assert.equal(f.requests.length, 2)
  } finally { f.stop() }
})
