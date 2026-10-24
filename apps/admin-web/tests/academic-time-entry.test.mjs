import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
function load(code, imports) {
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(code, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022
  } }).outputText, { module, exports: module.exports, require: name => imports(name) })
  return module.exports
}
function setup(tab = 'timetable') {
  const route = vue.reactive({ path: '/dashboard/academic', query: { tab, workspace_id: '9007199254740993' } })
  const router = { replace: async ({ query }) => { route.query = query } }
  const session = vue.reactive({ hasPermission: () => true, campusRuntime: { scheduling: true },
    workspace: { capabilities: ['staff.manage'] } })
  const routing = { useRoute: () => route, useRouter: () => router }
  const tabs = load(readFileSync(new URL('../src/composables/usePageTabs.ts', import.meta.url), 'utf8'),
    name => name === 'vue' ? vue : routing)
  const { descriptor } = parse(readFileSync(new URL('../src/views/AcademicView.vue', import.meta.url), 'utf8'))
  const component = load(compileScript(descriptor, { id: 'academic-time-entry' }).content, name => {
    if (name === 'vue') return vue
    if (name === 'vue-router') return routing
    if (name.endsWith('/stores/session')) return { useSessionStore: () => session }
    if (name.endsWith('/composables/usePageTabs')) return tabs
    return {}
  })
  const scope = vue.effectScope()
  const state = scope.run(() => component.default.setup({}, { expose() {} }))
  return { state, route, stop: () => scope.stop() }
}
test('college time editor stays hidden even with all academic permissions and scheduling enabled', () => {
  const f = setup()
  try {
    assert.equal(f.state.tabs.value.some(row => row.id === 'time'), false)
    assert.ok(f.state.tabs.value.some(row => row.id === 'imports'))
    assert.ok(f.state.tabs.value.some(row => row.id === 'publication'))
  } finally { f.stop() }
})
test('old time URL normalizes to an available tab and preserves college bigint', async () => {
  const f = setup('time')
  try {
    await vue.nextTick()
    assert.equal(f.state.tab.value, 'timetable')
    assert.equal(f.route.query.tab, 'timetable')
    assert.equal(f.route.query.workspace_id, '9007199254740993')
  } finally { f.stop() }
})
