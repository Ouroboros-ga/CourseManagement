import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports) {
  const module = { exports: {} }
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], Error })
  return module.exports
}
const epoch = load('../src/utils/contextEpoch.ts', {})
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const policy = (enabled = false, version = 0, ready = true) => ({ enabled, version, configuration_ready: ready })
function fixture(overrides = {}, available = true) {
  const calls = [], saved = []
  const api = {
    get: async cid => { calls.push(['get', cid]); return policy() },
    update: async (...args) => { calls.push(['update', ...args]); return policy(args[1].enabled, args[1].current_version + 1) },
    ...overrides
  }
  const { useObjectionPrecheckPolicy } = load('../src/composables/useObjectionPrecheckPolicy.ts', {
    vue, '../api/objectionPrecheck': { objectionPrecheckPolicyApi: api }, '../utils/contextEpoch': epoch
  })
  const context = vue.reactive({ key: 'user1:rev1', collegeId: '1', available })
  const scope = vue.effectScope()
  const s = scope.run(() => useObjectionPrecheckPolicy(() => ({ ...context }), value => saved.push(value)))
  return { s, context, calls, saved, stop: () => scope.stop() }
}

test('policy update sends only desired state and the seen version, then reports success', async () => {
  const f = fixture()
  try {
    await flush(); await f.s.setEnabled(true)
    assert.equal(f.s.policy.value.enabled, true)
    assert.equal(JSON.stringify(f.calls.at(-1)), JSON.stringify(['update', '1', { enabled: true, current_version: 0 }]))
    assert.equal(f.saved.length, 1)
    assert.match(f.s.notice.value, /开启/)
  } finally { f.stop() }
})
test('unready configuration blocks enable but permits disabling an already enabled policy', async () => {
  const f = fixture({ get: async () => policy(false, 0, false) })
  try {
    await flush(); await f.s.setEnabled(true)
    assert.equal(f.calls.length, 0)
    assert.equal(f.s.policy.value.enabled, false)
  } finally { f.stop() }
  const g = fixture({ get: async () => policy(true, 2, false), update: async () => policy(false, 3, false) })
  try { await flush(); await g.s.setEnabled(false); assert.equal(g.s.policy.value.enabled, false); assert.equal(g.saved.length, 1) }
  finally { g.stop() }
})
test('save is not optimistic and repeated clicks do not create another request', async () => {
  let release
  const f = fixture({ update: (...args) => { f.calls.push(['update', ...args]); return new Promise(resolve => { release = resolve }) } })
  try {
    await flush(); const pending = f.s.setEnabled(true); await f.s.setEnabled(true)
    assert.equal(f.s.saving.value, true); assert.equal(f.s.policy.value.enabled, false)
    assert.equal(f.calls.filter(x => x[0] === 'update').length, 1)
    release(policy(true, 1)); await pending
    assert.equal(f.s.policy.value.enabled, true)
  } finally { f.stop() }
})
test('save conflict leaves unknown state until explicit refresh and emits no success', async () => {
  const f = fixture({ update: async () => { throw new Error('版本冲突') } })
  try {
    await flush(); await f.s.setEnabled(true)
    assert.equal(f.s.policy.value, null); assert.match(f.s.error.value, /刷新/)
    assert.equal(f.saved.length, 0); assert.equal(f.calls.length, 1)
    await f.s.refresh(); assert.equal(f.s.policy.value.enabled, false)
  } finally { f.stop() }
})
test('late reads and writes cannot affect another college or authorization revision', async () => {
  let read, write
  const f = fixture({ get: async cid => cid === '1' ? new Promise(resolve => { read = resolve }) : policy(true, 6), update: () => new Promise(resolve => { write = resolve }) })
  try {
    await flush(); f.context.collegeId = '2'; await flush(); read(policy(false)); await flush()
    assert.equal(f.s.policy.value.version, 6)
    const pending = f.s.setEnabled(false)
    f.context.key = 'user1:rev2'; await flush()
    write(policy(false, 7)); await pending
    assert.equal(f.s.policy.value.version, 6); assert.equal(f.saved.length, 0)
  } finally { f.stop() }
})
test('loss of permission and unmount discard pending results and prevent requests', async () => {
  let release
  const f = fixture({ get: () => new Promise(resolve => { release = resolve }) })
  await flush(); f.context.available = false; await flush(); release(policy(true, 9)); await flush()
  assert.equal(f.s.policy.value, null)
  await f.s.setEnabled(true); assert.equal(f.saved.length, 0)
  f.stop()
  const g = fixture({ get: () => new Promise(resolve => { release = resolve }) })
  await flush(); g.stop(); release(policy()); await flush()
  assert.equal(g.s.policy.value, null)
})
test('malformed response is an error rather than a known disabled setting', async () => {
  const f = fixture({ get: async () => ({ enabled: false, version: 0 }) })
  try { await flush(); assert.equal(f.s.policy.value, null); assert.match(f.s.error.value, /完整/); await f.s.setEnabled(true); assert.equal(f.saved.length, 0) }
  finally { f.stop() }
})

test('an inconsistent save receipt never reports successful enablement', async () => {
  const f = fixture({ update: async () => policy(false, 1) })
  try {
    await flush(); await f.s.setEnabled(true)
    assert.equal(f.s.policy.value, null)
    assert.match(f.s.error.value, /核对/)
    assert.equal(f.saved.length, 0)
  } finally { f.stop() }
})
