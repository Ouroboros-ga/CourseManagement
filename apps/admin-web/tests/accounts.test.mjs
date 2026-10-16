import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

test('teacher creation sends the selected college and school summary grant', async () => {
  const code = ts.transpileModule(readFileSync(new URL('../src/api/accounts.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }, calls = []
  vm.runInNewContext(code, { module, exports: module.exports, require: () => ({
    request: async (...args) => { calls.push(args); return { id: '12' } }
  }) })
  await module.exports.createTeacherAccount({
    college_id: '9007199254740993', can_view_school_summary: true,
    username: ' T01 ', display_name: ' 教师 ', initial_password: 'Test123456'
  })
  assert.equal(calls[0][0], '/api/v1/teacher-accounts')
  assert.deepEqual(JSON.parse(calls[0][1].body), {
    college_id: '9007199254740993', can_view_school_summary: true,
    username: 'T01', display_name: '教师', initial_password: 'Test123456'
  })
})
