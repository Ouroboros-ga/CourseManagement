import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => {
    if (!(name in imports)) throw new Error(`Unexpected import ${name}`)
    return imports[name]
  } })
  return module.exports
}

const flush = async () => {
  await vue.nextTick()
  await new Promise(resolve => setImmediate(resolve))
  await vue.nextTick()
}

function fixture(overrides = {}) {
  const pending = [], unmount = []
  const session = vue.reactive({
    currentUser: { id: 'user-1' },
    workspaceCollegeId: 'A',
    workspaces: [{ id: 'A', status: 'ACTIVE' }, { id: 'B', status: 'ACTIVE' }],
    selectWorkspace(id) {
      if (this.workspaces.some(row => row.id === id && row.status === 'ACTIVE')) this.workspaceCollegeId = id
    },
    async refreshWorkspaces() {},
    hasAnyRole: () => false,
    ...overrides
  })
  const api = {
    getCollegeCapabilities: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
    listCourseTypes: async () => [],
    listGroups: async () => []
  }
  const { useCampusConfiguration } = load('../src/composables/useCampusConfiguration.ts', {
    vue: { ...vue, onUnmounted: callback => unmount.push(callback) },
    '../stores/session': { useSessionStore: () => session },
    '../utils/contextEpoch': load('../src/utils/contextEpoch.ts'),
    '../api/campus': api
  })
  const scope = vue.effectScope()
  const state = scope.run(() => useCampusConfiguration())
  const settle = async (index, value, asError = false) => {
    if (asError) pending[index].reject(value)
    else pending[index].resolve(value)
    await flush()
  }
  return {
    session, state, pending, settle,
    capability: (capabilities = []) => ({ id: session.workspaceCollegeId, capabilities, business_ready: true }),
    stop() { unmount.forEach(callback => callback()); scope.stop() }
  }
}

test('a settled capabilities read always releases the loading state', async () => {
  const f = fixture()
  try {
    assert.equal(f.state.busy.value, true, 'the first read starts loading')
    await f.settle(0, f.capability(['academic.read']))
    assert.equal(f.state.busy.value, false)
    assert.deepEqual(f.state.college.value?.capabilities, ['academic.read'])
    assert.equal(f.state.error.value, '')
  } finally { f.stop() }
})

test('a rejected capabilities read reports the error instead of an empty area', async () => {
  const f = fixture()
  try {
    await f.settle(0, new Error('获取配置失败'), true)
    assert.equal(f.state.college.value, null)
    assert.equal(f.state.busy.value, false)
    assert.equal(f.state.error.value, '获取配置失败')
  } finally { f.stop() }
})

test('clearing the workspace while a read is pending cannot leave loading stuck', async () => {
  const f = fixture()
  try {
    f.session.workspaceCollegeId = ''
    await f.settle(0, f.capability())
    assert.equal(f.state.busy.value, false, 'loading must not stay on with no in-flight read')
    assert.equal(f.state.college.value, null)
  } finally { f.stop() }
})

test('signing out while a read is pending cannot leave loading stuck', async () => {
  const f = fixture()
  try {
    f.session.currentUser = null
    await f.settle(0, f.capability())
    assert.equal(f.state.busy.value, false, 'loading must not stay on after the account is gone')
    assert.equal(f.state.college.value, null)
  } finally { f.stop() }
})

test('out-of-order responses keep the last selected college and release loading', async () => {
  const f = fixture()
  try {
    f.session.workspaceCollegeId = 'B'
    await flush()
    assert.equal(f.pending.length, 2)
    await f.settle(1, { id: 'B', capabilities: ['academic.manage'], business_ready: true })
    await f.settle(0, { id: 'A', capabilities: ['stale'], business_ready: true })
    assert.deepEqual(f.state.college.value?.capabilities, ['academic.manage'])
    assert.equal(f.state.busy.value, false)
  } finally { f.stop() }
})
