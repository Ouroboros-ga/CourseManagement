import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}, globals = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], Error, Date, Map, Set, JSON, FormData, File, crypto: { randomUUID: () => 'synthetic-key' }, ...globals })
  return module.exports
}
const validAgentId = value => typeof value === 'string' && /^[1-9][0-9]{0,18}$/.test(value) && BigInt(value) < 2n ** 63n
const api = load('../src/api/assistantWorkspaces.ts', { './http': {}, './assistantReports': { validAgentId }, './importer': {} })
const epoch = load('../src/utils/contextEpoch.ts')
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const scope = { collegeId: '1', semesterId: '2' }
const member = (extra = {}) => ({ member_no: 1, filename: '志愿者.csv', archive_member: null, target: 'volunteer', blocked: false, message: '', sha256: 'a'.repeat(64), size_bytes: 20, duplicate_of: null, ...extra })
const source = (extra = {}) => ({ workspace_id: '3', college_id: '1', semester_id: '2', state: 'READY', filename: '资料.zip', inspection: { protocol_version: 1, source_sha256: 'a'.repeat(64), business_data_applied: false, files: [member()] }, preview: null, error_code: null, business_data_applied: false, ...extra })

test('source parser rejects wrong scope, duplicate members, applied data and untrusted targets', () => {
  assert.equal(api.parseWorkspace(source(), scope).inspection.files[0].target, 'volunteer')
  for (const value of [source({ college_id: '4' }), source({ workspace_id: 3 }), source({ business_data_applied: true }), source({ inspection: { ...source().inspection, files: [member(), member()] } }), source({ inspection: { ...source().inspection, files: [member({ target: 'execute_sql' })] } })]) assert.throws(() => api.parseWorkspace(value, scope))
})

function fixture(extra = {}, stored = null) {
  const calls = [], timers = new Map(), memory = new Map(stored ? [['management-assistant-imports', JSON.stringify(stored)]] : [])
  let tid = 0
  const remote = { read: async id => { calls.push(['read', id]); return source() }, lookup: async key => { calls.push(['lookup', key]); return source() }, upload: async (file, c, key) => { calls.push(['upload', file.name, key]); return source({ state: 'QUEUED', inspection: null }) }, cancel: async () => source({ state: 'CANCELED', inspection: null }), ...extra }
  const { useAssistantWorkspaces } = load('../src/composables/useAssistantWorkspaces.ts', { vue, '../api/assistantWorkspaces': { ...api, assistantWorkspacesApi: remote }, '../utils/contextEpoch': epoch, '../api/assistantReports': { validAgentId } }, { setTimeout: fn => { const id = ++tid; timers.set(id, fn); return id }, clearTimeout: id => timers.delete(id) })
  const context = vue.reactive({ key: 'user1:rev1', ...scope, active: true, available: true })
  const effect = vue.effectScope()
  const state = effect.run(() => useAssistantWorkspaces(() => ({ ...context }), { storage: { getItem: key => memory.get(key) || null, setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key) } }))
  return { state, context, calls, memory, timers, stop: () => effect.stop() }
}

test('upload queues one durable source and stores only context IDs, then a read obtains its manifest', async () => {
  const f = fixture()
  try {
    await f.state.upload(new File(['synthetic'], 'one.csv'))
    assert.equal(f.state.sources.value[0].state, 'QUEUED')
    assert.ok(![...f.memory.values()].join('').includes('synthetic'))
    await f.state.refresh()
    assert.equal(f.state.sources.value[0].state, 'READY')
    assert.equal(f.calls.filter(c => c[0] === 'upload').length, 1)
  } finally { f.stop() }
})

test('unknown upload response retries the same file and request key without automatic resend', async () => {
  const attempts = []
  const f = fixture({ upload: async (file, c, key) => { attempts.push([file, key]); if (attempts.length === 1) throw new Error('network'); return source() } })
  try {
    await f.state.upload(new File(['synthetic'], 'one.csv'))
    assert.equal(attempts.length, 1); assert.equal(f.state.retryPending.value, true)
    await f.state.retryUpload()
    assert.equal(attempts[0][0], attempts[1][0]); assert.equal(attempts[0][1], attempts[1][1])
  } finally { f.stop() }
})

test('reload resolves an uncertain upload by its owned request key, never uploads again', async () => {
  const f = fixture({}, { key: 'user1:rev1', ...scope, ids: [], pendingKey: 'original-key' })
  try { await flush(); assert.equal(f.state.sources.value[0].workspace_id, '3'); assert.deepEqual(f.calls, [['lookup', 'original-key']]); assert.equal(f.state.retryPending.value, false) }
  finally { f.stop() }
})

test('scope change fences a late upload and discards file bytes and recovery pointer', async () => {
  let resolve
  const f = fixture({ upload: () => new Promise(r => { resolve = r }) })
  try {
    const pending = f.state.upload(new File(['old'], 'one.csv')); await flush()
    f.context.key = 'user2:rev1'; await flush(); resolve(source()); await pending
    assert.equal(f.state.sources.value.length, 0); assert.equal(f.memory.size, 0); assert.equal(f.state.retryPending.value, false)
  } finally { f.stop() }
})

test('permission denial clears old source names and restores no stale actions', async () => {
  let denied = false
  const f = fixture({ read: async () => { if (denied) throw Object.assign(new Error('权限已变化'), { status: 403 }); return source() } }, { key: 'user1:rev1', ...scope, ids: ['3'], pendingKey: '' })
  try { await flush(); denied = true; await f.state.refresh(); assert.equal(f.state.sources.value.length, 0); assert.equal(f.memory.size, 0); assert.ok(f.state.error.value) }
  finally { f.stop() }
})

test('an upload idempotency conflict preserves earlier sources and the uncertain request pointer', async () => {
  const f = fixture({ upload: async () => { throw Object.assign(new Error('同键资料已变化'), { status: 409, code: 'IDEMPOTENCY_KEY_REUSED' }) } }, { key: 'user1:rev1', ...scope, ids: ['3'], pendingKey: '' })
  try {
    await flush(); await f.state.upload(new File(['different'], 'different.csv'))
    assert.equal(f.state.sources.value[0].workspace_id, '3')
    assert.equal(f.state.retryPending.value, true); assert.equal(f.memory.size, 1)
    await f.state.refresh(); assert.equal(f.state.retryPending.value, false)
  } finally { f.stop() }
})

test('expiration of one source preserves other accepted sources and continues reading', async () => {
  const f = fixture({ read: async id => { if (id === '3') throw Object.assign(new Error('资料过期'), { status: 410 }); return source({ workspace_id: '4' }) } }, { key: 'user1:rev1', ...scope, ids: ['3', '4'], pendingKey: '' })
  try { await flush(); assert.equal(f.state.sources.value[0].workspace_id, '4'); assert.deepEqual(JSON.parse([...f.memory.values()][0]).ids, ['4']) }
  finally { f.stop() }
})
