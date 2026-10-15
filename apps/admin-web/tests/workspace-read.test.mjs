import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

test('workspace read clears old data and ignores late responses after context change or unmount', async () => {
  const source = readFileSync(new URL('../src/composables/useWorkspaceRead.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const module = { exports: {} }, cleanups = [], pending = []
  vm.runInNewContext(code, { module, exports: module.exports, require: () => ({ ...vue, onUnmounted: fn => cleanups.push(fn) }) })
  const key = vue.ref('A'), scope = vue.effectScope()
  const state = scope.run(() => module.exports.useWorkspaceRead(() => key.value, () => !!key.value,
    () => new Promise(resolve => pending.push(resolve))))
  const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }
  try {
    await flush()
    key.value = 'B'; await flush()
    pending[0]({ owner: 'A' }); await flush()
    assert.equal(state.data.value, null)
    pending[1]({ owner: 'B' }); await flush()
    assert.equal(state.data.value.owner, 'B')
    key.value = 'C'; await flush()
    assert.equal(state.data.value, null)
    cleanups.forEach(fn => fn()); scope.stop()
    pending[2]({ owner: 'C' }); await flush()
    assert.equal(state.data.value, null)
  } finally { scope.stop() }
})
