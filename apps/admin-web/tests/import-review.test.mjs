import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const module = { exports: {} }
const source = readFileSync(new URL('../src/components/academic/importReviewPresentation.ts', import.meta.url), 'utf8')
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText,
  { module, exports: module.exports })
const { describeImportValue, groupIssues, personLinkNotice } = module.exports

const file = { summary: { class_name: '测试2601' }, changes: [{ key: '测试2601_C_AA/C_AA/2/1-2', after: { course_name: '高等数学' } }], issues: [
  { code: 'PERSON_LINK_PENDING', severity: 'warning', message: '测试2601_C_AA · 张老师：未找到有效教职工档案，请先补录档案' },
  { severity: 'error', row: 4, message: '工号与姓名不一致' },
  { severity: 'warning', message: '重复行已跳过' }
] }

test('pending staff links are separated from blocking errors and ordinary warnings', () => {
  const groups = groupIssues(file)
  assert.equal(groups.errors.length, 1)
  assert.equal(groups.warnings.length, 1)
  assert.equal(groups.people.length, 1)
  assert.equal(groups.people[0].context, '测试2601 · 高等数学')
  assert.equal(groups.people[0].person, '张老师')
  assert.equal(groups.people[0].reason, '未找到有效教职工档案，请先补录档案')
})

test('review fields translate business values and remove duplicated technical metadata', () => {
  const text = describeImportValue({ source_row: 3, source_sheet: 'Sheet0', source_column: 4,
    student_count: 93, weekday: 2, course_name: '高等数学', weeks: [1,2,3,5], teacher: '张老师', staff_id: '99' })
  assert.match(text, /名单人数：93/)
  assert.match(text, /星期：星期二/)
  assert.match(text, /周次：第1—3、5周/)
  assert.doesNotMatch(text, /source_|staff_id|student_count/)
})

test('legacy pending messages still display readable course names without altering real conflicts', () => {
  const legacy = { ...file, issues: [{ severity: 'warning', message: file.issues[0].message }] }
  assert.equal(groupIssues(legacy).people[0].context, '测试2601 · 高等数学')
  assert.equal(groupIssues(file).errors[0].message, '工号与姓名不一致')
})

test('pending notice states import and permission boundaries with relation counts', () => {
  assert.match(personLinkNotice(273), /273 项关系/)
  assert.match(personLinkNotice(273), /不影响课表保存/)
  assert.match(personLinkNotice(273), /教师权限/)
})
