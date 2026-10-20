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

// 「系统管理员」原先是 SUPER_ADMIN 角色的界面叫法，与逐人权限派生的「平台管理员」并排出现时，
// 使用者无法判断自己到底能不能维护管理员账号。角色统一叫超级管理员，两档身份只叫管理员/平台管理员。
test('超级管理员角色与平台管理能力使用两套不重叠的称呼', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  const shell = source('../src/views/AppShell.vue')
  const users = source('../src/views/UsersView.vue')
  assert.match(shell, /SUPER_ADMIN: '超级管理员'/)
  assert.match(users, /SUPER_ADMIN: '超级管理员'/)
  for (const [name, text] of [['AppShell', shell], ['UsersView', users]])
    assert.doesNotMatch(text, /系统管理员/, `${name} 仍在用已废弃的角色叫法`)
  const panel = source('../src/components/accounts/AdministratorAccounts.vue')
  assert.match(panel, /标为「平台管理员」/)
  assert.match(panel, /标为「管理员」/)
})
