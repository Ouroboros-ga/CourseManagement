import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

test('group summary and detail preserve the same filters and string identifiers', async () => {
  const calls = [], module = { exports: {} }
  const source = readFileSync(new URL('../src/api/attendance.ts', import.meta.url), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022
  } }).outputText, { module, exports: module.exports, URLSearchParams,
    require: () => ({ request: async url => { calls.push(url); return {} } }) })
  const params = { semester_id: '9007199254740993', keyword: '张 同学',
    administrative_class_id: '9007199254740995', start_date: '2026-10-19', end_date: '2026-10-23',
    effective_type: 'LATE', course_type_id: '8', abnormal_only: true, page_size: 50, page: 2 }
  await module.exports.listAttendanceGroups('administrative_class', params)
  await module.exports.listAttendance({ ...params, task_id: '9007199254740997' })
  const group = new URL(calls[0], 'http://example.test'), detail = new URL(calls[1], 'http://example.test')
  for (const [key, value] of Object.entries(params)) {
    assert.equal(group.searchParams.get(key), String(value))
    assert.equal(detail.searchParams.get(key), String(value))
  }
  assert.equal(group.pathname, '/api/v1/attendance/groups')
  assert.equal(detail.searchParams.get('task_id'), '9007199254740997')
  assert.equal(group.searchParams.get('group_by'), 'administrative_class')
})
