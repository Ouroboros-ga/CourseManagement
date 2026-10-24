import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
function load(path, imports = {}) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name] })
  return module.exports
}
function fixture() {
  const session = { currentUser: { id: 'user' }, currentSemesterId: '1' }
  let impact, modal
  const { useConfigurationImpact } = load('../src/composables/useConfigurationImpact.ts', {
    vue: { onUnmounted() {} },
    'element-plus': { ElMessageBox: { confirm: () => new Promise(resolve => { modal = resolve }) } },
    '../api/campus': { getConfigurationImpact: () => new Promise(resolve => { impact = resolve }) },
    '../utils/contextEpoch': load('../src/utils/contextEpoch.ts'),
    '../stores/session': { useSessionStore: () => session }
  })
  return { session, confirm: useConfigurationImpact(() => 'A'), impact: value => impact(value), modal: () => modal() }
}
test('switching semester discards a pending impact result', async () => {
  const f = fixture(), pending = f.confirm('groups', '3', '1', true)
  f.session.currentSemesterId = '2'
  f.impact({ revision: 'old', retained_future_task_ids: [] })
  await assert.rejects(pending, /上下文/)
})
test('switching account while the confirmation dialog is open prevents a stale write ticket', async () => {
  const f = fixture(), pending = f.confirm('groups', '3', '1', true)
  f.impact({ revision: 'old', retained_future_task_ids: ['7'] })
  await new Promise(setImmediate)
  f.session.currentUser = { id: 'other' }
  f.modal()
  await assert.rejects(pending, /上下文/)
})
