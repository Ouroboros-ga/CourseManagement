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
function fixture() {
  const cid = vue.shallowRef('A'), callbacks = [], calls = [], writes = []
  const session = vue.reactive({ currentUser: { id: '1' } })
  const api = {
    previewAcademicPublication: (...args) => new Promise(resolve => calls.push({ args, resolve })),
    publishAcademicTimetable: async (...args) => { writes.push(args); return { version: 2, changed: true } }
  }
  const { useAcademicPublication } = load('../src/composables/useAcademicPublication.ts', {
    vue: { ...vue, onUnmounted: callback => callbacks.push(callback) },
    '../api/academicPublication': api,
    '../stores/session': { useSessionStore: () => session },
    '../utils/contextEpoch': load('../src/utils/contextEpoch.ts')
  })
  const scope = vue.effectScope()
  const state = scope.run(() => useAcademicPublication(() => cid.value))
  return { cid, state, calls, writes, stop: () => { callbacks.forEach(callback => callback()); scope.stop() } }
}
const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }

test('college change discards publication preview and cannot publish old college source', async () => {
  const f = fixture()
  try {
    f.state.semesterId.value = '11'
    await flush()
    const promise = f.state.preview()
    f.cid.value = 'B'
    await flush()
    f.calls[0].resolve({ source_revision: 'old', changed: true })
    await promise
    assert.equal(f.state.previewResult.value, null)
    await f.state.publish()
    assert.equal(f.writes.length, 0)
  } finally { f.stop() }
})

test('semester change invalidates confirmed preview; fresh preview sends its exact revision', async () => {
  const f = fixture()
  try {
    f.state.semesterId.value = '11'
    await flush()
    let promise = f.state.preview()
    f.calls[0].resolve({ source_revision: 'rev11', changed: true })
    await promise
    f.state.semesterId.value = '12'
    await flush()
    await f.state.publish()
    assert.equal(f.writes.length, 0)
    promise = f.state.preview()
    f.calls[1].resolve({ source_revision: 'rev12', changed: true })
    await promise
    await f.state.publish()
    assert.equal(JSON.stringify(f.writes[0]), JSON.stringify(['A', '12', 'rev12']))
  } finally { f.stop() }
})
