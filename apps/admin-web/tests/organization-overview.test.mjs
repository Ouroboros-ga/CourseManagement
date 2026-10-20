import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function moduleAt(path, imports) {
  const module = { exports: {} }
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText,
    { module, exports: module.exports, require: name => imports[name], Promise, Error })
  return module.exports
}
function setup(api, groups = [{ id: '9007199254740993', config_version: 1, lock_version: 1 }]) {
  const { useWorkspaceRead } = moduleAt('../src/composables/useWorkspaceRead.ts', {
    vue: { ...vue, onUnmounted: vue.onScopeDispose }
  })
  const { useOrganizationOverview } = moduleAt('../src/composables/useOrganizationOverview.ts', {
    vue,
    '../api/groupMembers': { groupMemberApi: { list: async () => [] } },
    '../api/organizationManagement': { organizationOverview: api },
    './useWorkspaceRead': { useWorkspaceRead }
  })
  const context = vue.reactive({ key: 'actor:1:term-1', collegeId: '1', semesterId: 'term-1', enabled: true,
    groups })
  const scope = vue.effectScope()
  const state = scope.run(() => useOrganizationOverview(() => ({ ...context })))
  return { context, scope, state }
}
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await vue.nextTick() }

test('switching semester discards late organization rules and members', async () => {
  let releaseOld
  const old = new Promise(resolve => { releaseOld = resolve })
  const { context, scope, state } = setup(async (_cid, sid) => sid === 'term-1' ? old
    : { items: { '9007199254740993': { configuration: { course_type_ids: ['new'] }, member_count: 7, specific: true } } })
  try {
    context.key = 'actor:1:term-2'; context.semesterId = 'term-2'
    await flush()
    releaseOld({ items: { '9007199254740993': { configuration: { course_type_ids: ['old'] }, member_count: 1, specific: false } } })
    await flush()
    assert.equal(state.data.value['9007199254740993'].configuration.course_type_ids[0], 'new')
    assert.equal(state.data.value['9007199254740993'].specific, true)
    assert.equal(state.data.value['9007199254740993'].member_count, 7)
  } finally { scope.stop() }
})

test('authorization failures remain explicit and disabling the feature clears cached data', async () => {
  const { context, scope, state } = setup(async () => { throw new Error('scope denied') })
  try {
    await flush()
    assert.equal(state.data.value['9007199254740993'].error, 'scope denied')
    assert.equal(state.busy.value, false)
    context.enabled = false
    await flush()
    assert.equal(state.data.value, null)
  } finally { scope.stop() }
})

test('many organizations use one summary request and disabling clears the late result', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  let requests = 0
  const { context, scope } = setup(async () => { requests++; await gate; return { items: {} } },
    Array.from({ length: 6 }, (_, index) => ({ id: String(index + 1), config_version: 1, lock_version: 1 })))
  try {
    assert.equal(requests, 1)
    context.enabled = false
    await flush()
    release()
    await flush()
    assert.equal(requests, 1)
  } finally { scope.stop() }
})
