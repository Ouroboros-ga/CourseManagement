import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const source = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')

// 学校与学院管理曾经同时承载学院结构、学院改名停用、跨范围授权和学校作息模板四种作用域，
// 使用者无法判断当前操作的对象是谁。以下约束把这几类作用域固定分开。
test('学院与授权组件不再承载作息编辑和学院改名', () => {
  const text = source('../src/components/campus/CampusAdministration.vue')
  for (const removed of ['SchoolTimeTemplates', 'CollegeTimeConfiguration', 'TimePeriodEditor', 'updateCollege'])
    assert.doesNotMatch(text, new RegExp(removed), `${removed} 属于其他作用域，不应回到学院与授权组件`)
})

test('管理对象只有页面上下文条一个学院选择器', () => {
  assert.match(source('../src/views/SchoolView.vue'), /aria-label="管理对象学院"/)
  assert.doesNotMatch(source('../src/components/campus/CampusAdministration.vue'), /el-select/)
})

test('学院作息在管理端没有入口，也不再渲染只能读提示的空页签', () => {
  const academic = source('../src/views/AcademicView.vue')
  assert.doesNotMatch(academic, /学院作息业务尚未启用/)
  assert.doesNotMatch(academic, /^\s*import CollegeTimeConfiguration/m)
  // 组件与后端 time-versions 入口刻意保留；恢复页签时必须同时接回
  // business_scoped && scheduling 门控，否则会重现“点进去只有一条提示”的死页签。
  assert.ok(existsSync(new URL('../src/components/campus/CollegeTimeConfiguration.vue', import.meta.url)))
})

test('全校作息模板在平台与学期设置内编辑，且只对超管开放', () => {
  const settings = source('../src/views/SettingsView.vue')
  assert.match(settings, /SchoolTimeTemplates/)
  assert.match(settings, /hasAnyRole\('SUPER_ADMIN'\)[\s\S]*campusRuntime\?\.scheduling/)
})

test('已下线的学院与组织配置整页没有被重新接回路由', () => {
  assert.throws(
    () => readFileSync(new URL('../src/components/campus/CampusConfiguration.vue', import.meta.url), 'utf8'),
    { code: 'ENOENT' }
  )
  assert.doesNotMatch(source('../src/router/index.ts'), /CampusConfiguration/)
})
