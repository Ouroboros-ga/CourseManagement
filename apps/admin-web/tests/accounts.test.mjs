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

// 界面上曾经同时出现 系统管理员/学院管理员/教师管理员/管理员/平台管理员/专职辅导员/任课教师 七个词，
// 实际只有三个层级，而且角色标签表里有后端不存在的角色。这里钉死：标签表只含真实角色，
// 三档称呼互不重叠，不再出现孤零零的「管理员」。
const REAL_ROLES = ['STUDENT', 'STUDENT_AFFAIRS_MANAGER', 'SUPER_ADMIN', 'TEACHER_ADMIN', 'VOLUNTEER']

test('角色标签表只包含 role 表里真实存在的五个角色', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  for (const [name, path] of [['AppShell.vue', '../src/views/AppShell.vue'], ['UsersView.vue', '../src/views/UsersView.vue']]) {
    const block = source(path).match(/const roleNameMap: Record<string, string> = \{([^}]*)\}/)
    assert.ok(block, `${name} 的角色标签表结构变了，守门测试需要一起更新`)
    const keys = [...block[1].matchAll(/^\s*([A-Z_]+): '/gm)].map(match => match[1])
    assert.deepEqual(keys.sort(), REAL_ROLES, `${name} 的角色标签表与 role 表不一致`)
  }
})

test('三档权限各有一个不重叠的名字', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  const shell = source('../src/views/AppShell.vue')
  const users = source('../src/views/UsersView.vue')
  const panel = source('../src/components/accounts/AdministratorAccounts.vue')
  const table = source('../src/components/accounts/AdministratorAccountTable.vue')
  assert.match(shell, /SUPER_ADMIN: '超级管理员'/)
  assert.match(users, /SUPER_ADMIN: '超级管理员'/)
  for (const [name, text] of [['AppShell', shell], ['UsersView', users], ['管理员面板', panel], ['身份列', table]]) {
    assert.doesNotMatch(text, /系统管理员/, `${name} 仍在用已废弃的角色叫法`)
    assert.doesNotMatch(text, /COUNSELOR/, `${name} 把教工职责当成了登录角色`)
  }
  assert.match(table, /can_manage_administrators \? '平台管理员' : '超级管理员'/)
  assert.match(panel, /标为「平台管理员」的/)
  assert.match(panel, /只标为「超级管理员」的/)
  assert.doesNotMatch(panel, /标为「管理员」的/, '不应再出现没有范围限定的裸「管理员」')
})
