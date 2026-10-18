import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function setup(api) {
  const module = { exports: {} }
  const source = readFileSync(new URL('../src/composables/useDispatchOptions.ts', import.meta.url), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { module, exports: module.exports, Error, require: name => ({ vue, '../api/campus': api })[name] })
  const context = vue.reactive({ collegeId: '1', userId: 'user', enabled: true, readTypes: true, readGroups: true })
  const scope = vue.effectScope()
  const state = scope.run(() => module.exports.useDispatchOptions(() => context))
  return { context, scope, state }
}

test('dispatch options discard responses from a previous workspace', async () => {
  let resolve
  const { context, state, scope } = setup({ listCourseTypes: () => new Promise(r => { resolve = r }), listGroups: async () => [] })
  try {
    const old = resolve
    context.collegeId = '2'
    await vue.nextTick()
    old([{ id: 'foreign' }])
    await new Promise(r => setImmediate(r))
    assert.deepEqual([...state.types.value], [])
    resolve([{ id: 'current' }])
    await new Promise(r => setImmediate(r))
    assert.equal(state.types.value[0].id, 'current')
  } finally { scope.stop() }
})

test('group configuration remains readable before scheduler activation', async () => {
  let calls = 0
  const { state, scope } = setup({ listCourseTypes: async () => [], listGroups: async () => { calls++; return [{ id: 'g', status: 'INACTIVE' }] } })
  try {
    await new Promise(r => setImmediate(r))
    assert.equal(calls, 1)
    assert.equal(state.groups.value[0].status, 'INACTIVE')
  } finally { scope.stop() }
})
