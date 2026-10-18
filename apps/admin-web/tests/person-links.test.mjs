import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function setup(api) {
  const module = { exports: {} }
  const source = readFileSync(new URL('../src/composables/usePersonLinks.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, Error, require: name => ({ vue: { ...vue, onUnmounted: () => {} }, '../api/importer': api })[name] })
  const context = vue.reactive({ cid: '1', kind: 'teaching', semester: '2', identity: 'user-1' })
  const scope = vue.effectScope()
  const state = scope.run(() => module.exports.usePersonLinks(() => context))
  return { context, state, scope }
}

test('late person matching response cannot appear in a different college', async () => {
  let resolve
  const { context, state, scope } = setup({ previewPersonLinks: () => new Promise(r => { resolve = r }) })
  try {
    const pending = state.preview()
    context.cid = '3'
    await vue.nextTick()
    resolve({ revision: 'old', links: [], pending: [] })
    await pending
    assert.equal(state.plan.value, null)
  } finally { scope.stop() }
})

test('confirmation uses reviewed revision and a failed confirmation forces a new review', async () => {
  const calls = []
  const { state, scope } = setup({
    previewPersonLinks: async () => ({ revision: 'reviewed', summary: { person_links_create: 1 }, links: [], pending: [] }),
    confirmPersonLinks: async (...args) => { calls.push(args); throw new Error('资料已变化') }
  })
  try {
    await state.preview()
    assert.equal(state.canConfirm.value, true)
    await state.confirm()
    assert.equal(calls[0][0], '1')
    assert.equal(calls[0][1].revision, 'reviewed')
    assert.equal(state.plan.value, null)
    assert.match(state.error.value, /资料已变化/)
  } finally { scope.stop() }
})
