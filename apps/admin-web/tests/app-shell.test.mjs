import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'

function compile(source, imports, globals = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(source.replaceAll('import.meta.env.DEV', 'false'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => {
    if (!(name in imports)) throw new Error(`Unexpected import: ${name}`)
    return imports[name]
  }, ...globals })
  return module.exports
}
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }

function fixture(fetchObjections = async () => ({ total: 3 })) {
  const calls = [], warnings = [], mounts = [], unmounts = []
  const session = vue.reactive({
    currentUser: { id: 'U1' }, workspaceCollegeId: 'C1', currentSemesterId: 'S1',
    semesters: [{ id: 'S1' }], hasPermission: () => true
  })
  const route = vue.reactive({ path: '/dashboard/home', meta: { workspacePage: 'home' } })
  const key = vue.computed(() => `${session.currentUser?.id || ''}:${session.workspaceCollegeId}:${session.currentSemesterId}`)
  const epoch = compile(readFileSync(new URL('../src/utils/contextEpoch.ts', import.meta.url), 'utf8'), {})
  const { descriptor } = parse(readFileSync(new URL('../src/views/AppShell.vue', import.meta.url), 'utf8'))
  const component = compile(compileScript(descriptor, { id: 'shell' }).content, {
    vue: { ...vue, onMounted: fn => mounts.push(fn), onUnmounted: fn => unmounts.push(fn) },
    'vue-router': { useRoute: () => route, useRouter: () => ({ replace() {} }) },
    '../stores/session': { useSessionStore: () => session },
    '../api/objections': { listObjections: args => { calls.push(args); return fetchObjections(args) } },
    '../navigation/workspaceNavigation': { primaryPages: [], auxiliaryPages: [], canAccessPage: () => true },
    '../composables/useWorkspaceContext': { useWorkspaceContext: () => ({ key }) },
    '../composables/useWorkspaceChanges': { useWorkspaceChanges() {} },
    '../components/workspace/WorkspaceContextBar.vue': {},
    '../components/assistant/ManagementAssistant.vue': {},
    '../utils/contextEpoch': epoch, '../assets/school-logo.png': {}
  }, {
    console: { warn: (...args) => warnings.push(args) },
    fetch: async () => ({ ok: true, json: async () => ({ status: 'ok', database: 'up' }) }),
    window: { setInterval: () => 1 }, clearInterval() {}
  }).default
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup({}, { expose() {} }))
  return { session, route, state, calls, warnings,
    mount: () => Promise.all(mounts.map(fn => fn())),
    stop() { unmounts.forEach(fn => fn()); scope.stop() } }
}

test('college changes trigger one badge read even when the workspace key also changes', async () => {
  const f = fixture()
  try {
    await f.mount(); await flush()
    assert.equal(f.calls.length, 1)
    f.session.workspaceCollegeId = 'C2'
    f.route.path = '/dashboard/inspections'
    await flush()
    assert.equal(f.calls.length, 2)
    assert.equal(f.state.pendingObjectionsCount.value, 3)
    f.route.path = '/dashboard/academic'
    await flush()
    assert.equal(f.calls.length, 3)
    f.session.currentUser = null
    await flush()
    assert.equal(f.calls.length, 3)
    assert.equal(f.state.pendingObjectionsCount.value, 0)
  } finally { f.stop() }
})

test('late badge errors after switching college do not warn or erase the new badge', async () => {
  const pending = []
  const f = fixture(() => new Promise((resolve, reject) => pending.push({ resolve, reject })))
  try {
    const mounted = f.mount(); await flush()
    f.session.workspaceCollegeId = 'C2'; await flush()
    for (const request of pending.slice(1)) request.resolve({ total: 7 })
    await flush()
    pending[0].reject(new Error('old college request failed'))
    await mounted; await flush()
    assert.equal(f.state.pendingObjectionsCount.value, 7)
    assert.equal(f.warnings.length, 0)
  } finally { f.stop() }
})

test('a failed current badge request remains visible as an error', async () => {
  const f = fixture(async () => { throw new Error('current request unauthorized') })
  try {
    await f.mount(); await flush()
    assert.equal(f.warnings.length, 1)
    assert.equal(f.warnings[0][1].message, 'current request unauthorized')
    assert.equal(f.state.pendingObjectionsCount.value, 0)
  } finally { f.stop() }
})
