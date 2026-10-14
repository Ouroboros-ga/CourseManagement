import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => {
    if (!(name in imports)) throw new Error(`Unexpected import ${name}`)
    return imports[name]
  } })
  return module.exports
}
function fixture() {
  const cid = vue.shallowRef('A')
  const calls = []
  const cleanup = []
  const session = vue.reactive({ currentUser: { id: '1' } })
  const api = { listScopedAcademic: (...args) => new Promise(resolve => calls.push({ args, resolve })) }
  const { useScopedAcademicData } = load('../src/composables/useScopedAcademicData.ts', {
    vue: { ...vue, onUnmounted: fn => cleanup.push(fn) },
    '../api/scopedAcademic': api,
    '../stores/session': { useSessionStore: () => session },
    '../utils/contextEpoch': load('../src/utils/contextEpoch.ts')
  })
  const scope = vue.effectScope()
  const state = scope.run(() => useScopedAcademicData(() => cid.value, () => ['academic.read']))
  return { state, calls, cid, stop: () => { cleanup.forEach(fn => fn()); scope.stop() } }
}
const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }

test('one initial request and draft search cannot strand loading state', async () => {
  const f = fixture()
  try {
    await flush()
    assert.equal(f.calls.length, 1)
    f.state.keyword.value = 'draft'
    f.calls[0].resolve({ items: [{ id: 'A1' }], total: 1 })
    await flush()
    assert.equal(f.state.busy.value, false)
    assert.equal(f.state.rows.value[0].id, 'A1')
    f.state.search()
    await flush()
    assert.equal(f.calls.at(-1).args[3], 'draft')
  } finally { f.stop() }
})

test('college change discards old result and unmount rejects pending writeback', async () => {
  const f = fixture()
  try {
    await flush()
    const old = f.calls.at(-1)
    f.cid.value = 'B'
    await flush()
    const current = f.calls.at(-1)
    assert.equal(current.args[0], 'B')
    old.resolve({ items: [{ id: 'foreign' }], total: 1 })
    await flush()
    assert.equal(f.state.rows.value.length, 0)
    f.stop()
    current.resolve({ items: [{ id: 'after-unmount' }], total: 1 })
    await flush()
    assert.equal(f.state.rows.value.length, 0)
  } finally { f.stop() }
})
