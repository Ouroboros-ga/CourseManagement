import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports) {
  const module = { exports: {} }
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022
  } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], Error })
  return module.exports
}
const epoch = load('../src/utils/contextEpoch.ts', {})
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const state = (overrides = {}) => ({
  objection_id: '9', job_id: '11', status: 'SUCCEEDED', stored_status: 'SUCCEEDED',
  is_current: true, result: { recommendation: 'SUPPORT', summary: '材料与申请相符', evidence: [], questions: [] },
  can_retry: false, retry_block_message: null, can_final_review: true,
  manual_reason_required: false, review_block_reason: null, final_status: 'PENDING', ...overrides
})
function fixture(overrides = {}, enabled = true) {
  const calls = []
  const api = {
    get: async (...args) => { calls.push(['get', ...args]); return state() },
    retry: async (...args) => { calls.push(['retry', ...args]); return state({ job_id: '12', status: 'QUEUED', result: null, can_final_review: false }) },
    ...overrides
  }
  const { useObjectionPrecheck } = load('../src/composables/useObjectionPrecheck.ts', {
    vue, '../api/objectionPrecheck': { objectionPrecheckApi: api }, '../utils/contextEpoch': epoch
  })
  const context = vue.reactive({ key: 'actor1:revision1', collegeId: '1', objectionId: '9', enabled })
  const scope = vue.effectScope()
  const s = scope.run(() => useObjectionPrecheck(() => ({ ...context })))
  return { s, context, calls, stop: () => scope.stop() }
}

test('confirmed current advice adds its ID without making the formal decision', async () => {
  const f = fixture()
  try {
    await flush()
    assert.throws(() => f.s.reviewFields(), /确认/)
    f.s.confirmed.value = true
    assert.equal(JSON.stringify(f.s.reviewFields()), JSON.stringify({ precheck_job_id: '11' }))
  } finally { f.stop() }
})
test('running precheck cannot be bypassed by entering a manual reason', async () => {
  const f = fixture({ get: async () => state({ status: 'RUNNING', result: null, can_final_review: false, review_block_reason: '预审仍在处理中' }) })
  try {
    await flush(); f.s.confirmed.value = true; f.s.manualReason.value = '我已核验'
    assert.throws(() => f.s.reviewFields(), /处理中/)
  } finally { f.stop() }
})
test('manual fallback requires confirmation and a nonblank reason', async () => {
  const f = fixture({ get: async () => state({ status: 'FAILED', result: null, manual_reason_required: true }) })
  try {
    await flush(); f.s.confirmed.value = true; f.s.manualReason.value = '   '
    assert.throws(() => f.s.reviewFields(), /原因/)
    f.s.manualReason.value = ' 已核对原始材料 '
    assert.equal(f.s.reviewFields().manual_precheck_reason, '已核对原始材料')
  } finally { f.stop() }
})
test('failed read blocks final review and never behaves as feature disabled', async () => {
  const f = fixture({ get: async () => { throw new Error('无权读取') } })
  try { await flush(); assert.throws(() => f.s.reviewFields(), /读取/); assert.match(f.s.error.value, /无权/) }
  finally { f.stop() }
})
test('disabled feature sends no new fields and performs no precheck calls', async () => {
  const f = fixture({}, false)
  try { await flush(); assert.equal(JSON.stringify(f.s.reviewFields()), '{}'); assert.equal(f.calls.length, 0) }
  finally { f.stop() }
})
test('old account or case responses cannot overwrite a new context', async () => {
  let release
  const f = fixture({ get: async (_cid, id) => id === '9' ? new Promise(resolve => { release = resolve }) : state({ objection_id: id, job_id: '21' }) })
  try {
    await flush(); f.context.objectionId = '10'; await flush()
    release(state()); await flush()
    assert.equal(f.s.snapshot.value.objection_id, '10')
    f.s.confirmed.value = true; f.s.manualReason.value = 'old'
    f.context.key = 'actor2'; await flush()
    assert.equal(f.s.confirmed.value, false); assert.equal(f.s.manualReason.value, '')
  } finally { f.stop() }
})
test('retry uses the seen ID once and never automatically resubmits after failure', async () => {
  let release
  const f = fixture({ get: async () => state({ status: 'FAILED', result: null, can_retry: true }), retry: (...args) => {
    f.calls.push(['retry', ...args]); return new Promise(resolve => { release = resolve })
  } })
  try {
    await flush(); f.s.confirmed.value = true
    const pending = f.s.retry(); await f.s.retry()
    assert.equal(f.calls.filter(x => x[0] === 'retry').length, 1)
    assert.equal(JSON.stringify(f.calls.at(-1)), JSON.stringify(['retry', '1', '9', { expected_job_id: '11' }]))
    release(state({ job_id: '12', status: 'QUEUED', result: null, can_final_review: false })); await pending
    assert.equal(f.s.confirmed.value, false)
    assert.equal(f.s.snapshot.value.job_id, '12')
  } finally { f.stop() }
})
test('refresh clears confirmation and rejects a response for a different case', async () => {
  let wrong = false
  const f = fixture({ get: async () => state({ objection_id: wrong ? '100' : '9' }) })
  try {
    await flush(); f.s.confirmed.value = true
    wrong = true; await f.s.refresh()
    assert.equal(f.s.snapshot.value, null); assert.equal(f.s.confirmed.value, false)
    assert.throws(() => f.s.reviewFields(), /读取/)
  } finally { f.stop() }
})

test('invalid persisted advice is hidden while the server manual requirement stays authoritative', async () => {
  const f = fixture({ get: async () => state({ manual_reason_required: true, result: { summary: 'broken' } }) })
  try {
    await flush()
    assert.equal(f.s.snapshot.value.result, null)
    f.s.confirmed.value = true
    assert.throws(() => f.s.reviewFields(), /原因/)
  } finally { f.stop() }
})

test('an uncertain retry clears the old receipt and requires an explicit read', async () => {
  let reads = 0
  const f = fixture({ get: async () => { reads++; return state({ can_retry: true }) }, retry: async () => { throw new Error('请求超时') } })
  try {
    await flush(); await f.s.retry()
    assert.equal(f.s.snapshot.value, null)
    assert.equal(reads, 1)
    assert.match(f.s.error.value, /勿重复提交/)
    await f.s.refresh()
    assert.equal(f.s.snapshot.value.job_id, '11')
  } finally { f.stop() }
})

test('successful status without advice cannot be confirmed as normal AI review', async () => {
  const f = fixture({ get: async () => state({ result: null }) })
  try {
    await flush(); f.s.confirmed.value = true
    assert.equal(f.s.snapshot.value, null)
    assert.throws(() => f.s.reviewFields(), /读取/)
  } finally { f.stop() }
})
