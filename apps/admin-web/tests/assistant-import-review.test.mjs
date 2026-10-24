import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], Error, Date, Set })
  return module.exports
}
const validAgentId = value => typeof value === 'string' && /^[1-9][0-9]{0,18}$/.test(value) && BigInt(value) < 2n ** 63n
const contracts = load('../src/api/assistantImports.ts', {
  './http': {}, './importer': {}, './assistantReports': { validAgentId }
})
const epoch = load('../src/utils/contextEpoch.ts')
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const wire = (extra = {}) => ({
  kind: 'IMPORT_PREVIEW_REVIEW', college_id: '1', semester_id: '2', can_confirm: false,
  business_data_applied: false, requires_human_confirmation: true,
  files: [{ batch_id: '11', target: 'volunteer', changes: { CREATE: 2 }, error_count: 1, warning_count: 0 }], ...extra
})
const task = (data = wire()) => ({ task_id: '9', status: 'SUCCEEDED', result: { status: 'SUCCEEDED', data } })
const draft = (extra = {}) => ({ id: '11', target: 'volunteer', status: 'PREVIEW', semester_id: '2', ...extra })
function fixture(extra = {}) {
  const calls = [], opened = []
  const api = {
    read: async id => { calls.push(['read', id]); return task() },
    batch: async id => { calls.push(['batch', id]); return draft({ id }) }, ...extra
  }
  const { useAssistantImportReview } = load('../src/composables/useAssistantImportReview.ts', {
    vue, '../api/assistantImports': { ...contracts, assistantImportsApi: api },
    '../api/assistantReports': { validAgentId }, '../utils/contextEpoch': epoch
  })
  const context = vue.reactive({ key: 'user1:revision1', taskId: '9', collegeId: '1', semesterId: '2', available: true })
  const scope = vue.effectScope()
  const state = scope.run(() => useAssistantImportReview(() => ({ ...context }), value => opened.push(value)))
  return { context, state, calls, opened, stop: () => scope.stop() }
}

test('task read does not save; explicit group action resumes conflicting previews for human review', async () => {
  const f = fixture()
  try {
    await flush()
    assert.equal(f.state.summary.value.can_confirm, false)
    assert.equal(f.calls.length, 1); assert.equal(f.opened.length, 0)
    await f.state.open('volunteer')
    assert.equal(f.opened[0][0].id, '11')
    assert.equal(f.opened[0][0].filename, '资料预览 11')
    assert.deepEqual(f.calls.map(c => c[0]), ['read', 'batch'])
  } finally { f.stop() }
})

test('task contract rejects wrong scope, duplicated IDs, invalid counts and implicit saves', () => {
  for (const value of [
    wire({ college_id: '3' }), wire({ semester_id: '3' }), wire({ business_data_applied: true }),
    wire({ requires_human_confirmation: false }), wire({ files: [] }),
    wire({ files: [...wire().files, ...wire().files] }),
    wire({ files: [{ ...wire().files[0], batch_id: '01' }] }),
    wire({ files: [{ ...wire().files[0], target: 'execute_sql' }] }),
    wire({ files: [{ ...wire().files[0], changes: { CREATE: -1 } }] }),
    wire({ files: [{ ...wire().files[0], changes: { DELETE_ALL: 2 } }] })
  ]) assert.throws(() => contracts.parseImportReview(value, '1', '2'))
})

test('pending and failed tasks expose no resume action', async () => {
  for (const status of ['QUEUED', 'RUNNING', 'FAILED', 'CANCELED']) {
    const f = fixture({ read: async () => ({ task_id: '9', status, result: null }) })
    try {
      await flush(); await f.state.open('volunteer')
      assert.equal(f.state.summary.value, null); assert.equal(f.opened.length, 0)
      assert.equal(f.state.taskStatus.value, status)
    } finally { f.stop() }
  }
})

test('bad task IDs cannot issue requests', async () => {
  const f = fixture()
  try {
    await flush(); f.context.taskId = '01'; await flush()
    assert.equal(f.calls.length, 1); assert.equal(f.state.summary.value, null)
    assert.ok(f.state.error.value)
  } finally { f.stop() }
})

test('unknown or rounded task response cannot be used', async () => {
  for (const result of [{ ...task(), task_id: 9 }, { ...task(), status: 'DONE' }, { ...task(), result: null }]) {
    const f = fixture({ read: async () => result })
    try { await flush(); assert.equal(f.state.summary.value, null); assert.ok(f.state.error.value) }
    finally { f.stop() }
  }
})

test('a late task response is fenced on account or authorization change', async () => {
  let release
  const f = fixture({ read: () => new Promise(resolve => { release = resolve }) })
  try {
    await flush(); f.context.key = 'user2'; f.context.available = false; await flush()
    release(task()); await flush()
    assert.equal(f.state.summary.value, null); assert.equal(f.opened.length, 0)
  } finally { f.stop() }
})

test('batch response is fenced on semester change and after disposal', async () => {
  for (const dispose of [false, true]) {
    let release
    const f = fixture({ batch: () => new Promise(resolve => { release = resolve }) })
    await flush(); const pending = f.state.open('volunteer'); await flush()
    if (dispose) f.stop(); else { f.context.semesterId = '3'; await flush() }
    release(draft()); await pending
    assert.equal(f.opened.length, 0)
    if (!dispose) f.stop()
  }
})

test('current preview metadata must match the task group before resuming', async () => {
  for (const batch of [draft({ id: '12' }), draft({ target: 'admin_roster' }), draft({ semester_id: '3' }), draft({ status: 'CONFIRMED' })]) {
    const f = fixture({ batch: async () => batch })
    try {
      await flush(); await f.state.open('volunteer')
      assert.equal(f.opened.length, 0); assert.equal(f.state.summary.value, null); assert.ok(f.state.error.value)
    } finally { f.stop() }
  }
})

test('no partial group resumes when a later preview is denied', async () => {
  const f = fixture({
    read: async () => task(wire({ files: [wire().files[0], { ...wire().files[0], batch_id: '12' }] })),
    batch: async id => { if (id === '12') throw new Error('无权读取'); return draft() }
  })
  try {
    await flush(); await f.state.open('volunteer')
    assert.equal(f.opened.length, 0); assert.equal(f.state.summary.value, null)
  } finally { f.stop() }
})

test('repeated clicks cannot duplicate batch loading and unknown target cannot be opened', async () => {
  let release
  const f = fixture({ batch: () => new Promise(resolve => { release = resolve }) })
  try {
    await flush(); await f.state.open('execute_sql'); assert.equal(f.state.opening.value, false)
    const pending = f.state.open('volunteer'); await flush(); await f.state.open('volunteer')
    release(draft()); await pending
    assert.equal(f.opened.length, 1)
  } finally { f.stop() }
})
