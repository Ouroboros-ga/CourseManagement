import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const module = { exports: {} }
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/utils/periodDefinitionPresentation.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, { module, exports: module.exports })
const { periodDuration, periodSlotName, periodCoverage } = module.exports

test('07:30 early slot is morning, 20 minutes; coverage uses actual extrema', () => {
  const early = { start_time: '07:30:00', end_time: '07:50:00' }
  assert.equal(periodSlotName(early), '上午')
  assert.equal(periodDuration(early), '20 分钟')
  assert.equal(periodCoverage([{ start_time: '08:10:00', end_time: '08:55:00' },
    { start_time: '20:30:00', end_time: '21:15:00' }, early]), '覆盖 07:30 至 21:15 教学作息')
  assert.equal(periodDuration({}), '时间待核对')
})
