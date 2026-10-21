import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

test('staff export uses current college, string IDs and the existing binary client', async () => {
  const code = ts.transpileModule(readFileSync(new URL('../src/api/staff.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }, calls = []
  vm.runInNewContext(code, { module, exports: module.exports, URLSearchParams,
    require: () => ({ request: async (...args) => { calls.push(args); return 'blob' } }) })
  const body = { staff_ids: ['9007199254740993'], days_valid: 30 }
  assert.equal(await module.exports.exportStaffBindingTokens('1', body), 'blob')
  assert.equal(calls[0][0], '/api/v1/colleges/1/staff/export-binding-tokens')
  assert.deepEqual(JSON.parse(calls[0][1].body), body)
  assert.equal(calls[0][3], 'blob')
  await module.exports.exportStaffBindingTokens('2', { keyword: '张', days_valid: 14 })
  assert.equal(calls[1][0], '/api/v1/colleges/2/staff/export-binding-tokens')
  assert.deepEqual(JSON.parse(calls[1][1].body), { keyword: '张', days_valid: 14 })
})
