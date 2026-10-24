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
const policy = (enabled = false, version = 0) => ({ enabled, version, authorizer_user_id: null })
const group = (id, college = 'C1') => ({ id, college_id: college, name: id, status: 'ACTIVE' })

function fixture(overrides = {}) {
  const calls = []
  const api = {
    listGroups: async cid => { calls.push(['groups', cid]); return [group('G1', cid), group('G2', cid)] },
    get: async (...args) => { calls.push(['get', ...args]); return policy() },
    update: async (...args) => { calls.push(['update', ...args]); return policy(true, 1) },
    ...overrides
  }
  const { useAutoChangePolicy } = load('../src/composables/useAutoChangePolicy.ts', {
    vue, '../api/autoChangePolicy': { autoChangePolicyApi: api }, '../utils/contextEpoch': epoch
  })
  const context = vue.reactive({ key: 'actor-1:revision-1', collegeId: 'C1', semesterId: 'S1', enabled: true })
  const scope = vue.effectScope()
  const state = scope.run(() => useAutoChangePolicy(() => ({ ...context })))
  return { context, state, calls, stop: () => scope.stop() }
}

test('requires explicit organization selection and saves the read version without identity fields', async () => {
  const f = fixture()
  try {
    await flush()
    assert.equal(f.state.selectedGroupId.value, '')
    assert.equal(f.state.policy.value, null)
    assert.equal(f.calls.filter(row => row[0] === 'get').length, 0)
    f.state.selectedGroupId.value = 'G1'; await flush()
    assert.equal(f.state.policy.value.enabled, false)
    await f.state.setEnabled(true)
    assert.equal(f.state.policy.value.enabled, true)
    assert.equal(JSON.stringify(f.calls.at(-1)), JSON.stringify(['update', 'C1', 'G1', {
      semester_id: 'S1', enabled: true, current_version: 0
    }]))
  } finally { f.stop() }
})

test('does not flip the switch optimistically and prevents repeated saves', async () => {
  let release
  const f = fixture({ update: () => new Promise(resolve => { release = resolve }) })
  try {
    await flush(); f.state.selectedGroupId.value = 'G1'; await flush()
    const pending = f.state.setEnabled(true)
    await f.state.setEnabled(false)
    assert.equal(f.state.policy.value.enabled, false)
    assert.equal(f.state.saving.value, true)
    release(policy(true, 1)); await pending
    assert.equal(f.state.policy.value.enabled, true)
    assert.equal(f.state.saving.value, false)
  } finally { f.stop() }
})

test('late policy reads and writes cannot overwrite a different organization', async () => {
  let releaseRead, releaseWrite
  const f = fixture({
    get: async (_cid, gid) => gid === 'G1' ? new Promise(resolve => { releaseRead = resolve }) : policy(true, 4),
    update: () => new Promise(resolve => { releaseWrite = resolve })
  })
  try {
    await flush(); f.state.selectedGroupId.value = 'G1'; await flush()
    f.state.selectedGroupId.value = 'G2'; await flush()
    releaseRead(policy(false)); await flush()
    assert.equal(f.state.policy.value.version, 4)
    const pending = f.state.setEnabled(false)
    f.context.semesterId = 'S2'; await flush()
    releaseWrite(policy(false, 5)); await pending; await flush()
    assert.equal(f.state.selectedGroupId.value, '')
    assert.equal(f.state.policy.value, null)
    assert.equal(f.state.notice.value, '')
  } finally { f.stop() }
})

test('a save conflict invalidates the old switch value and requires an explicit refresh', async () => {
  const f = fixture({ update: async () => { throw new Error('策略已变化，请刷新') } })
  try {
    await flush(); f.state.selectedGroupId.value = 'G1'; await flush()
    await f.state.setEnabled(true)
    assert.equal(f.state.policy.value, null)
    assert.match(f.state.error.value, /刷新/)
    assert.equal(f.calls.filter(row => row[0] === 'get').length, 1)
    await f.state.loadPolicy()
    assert.equal(f.state.policy.value.enabled, false)
  } finally { f.stop() }
})

test('loss of permission clears state immediately and ignores pending group results', async () => {
  let release
  const f = fixture({ listGroups: () => new Promise(resolve => { release = resolve }) })
  try {
    f.context.enabled = false
    assert.equal(f.state.groups.value.length, 0)
    release([group('G1')]); await flush()
    assert.equal(f.state.groups.value.length, 0)
    await f.state.setEnabled(true)
    assert.equal(f.calls.length, 0)
  } finally { f.stop() }
})

test('a failed or malformed read is never shown as a known disabled policy', async () => {
  for (const get of [async () => { throw new Error('尚未启用') }, async () => ({ enabled: 'false', version: 0 })]) {
    const f = fixture({ get })
    try {
      await flush(); f.state.selectedGroupId.value = 'G1'; await flush()
      assert.equal(f.state.policy.value, null)
      assert.ok(f.state.error.value)
      await f.state.setEnabled(true)
      assert.equal(f.calls.filter(row => row[0] === 'update').length, 0)
    } finally { f.stop() }
  }
})
