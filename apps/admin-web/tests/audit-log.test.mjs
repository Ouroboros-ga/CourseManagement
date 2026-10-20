import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function load(path, modules = {}) {
  const source = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(source, {
    module, exports: module.exports, console, URLSearchParams,
    require: name => modules[name] || {}
  })
  return module.exports
}

// 生产 business_scoped 为真，workspaceHttp 会把 /audit-logs 改写成 /colleges/{cid}/audit-logs，
// 全校日志页会静默退化成只看当前学院，而且看不出来。
test('全校日志接口不经过学院工作区改写', () => {
  const source = readFileSync(new URL('../src/api/auditLogs.ts', import.meta.url), 'utf8')
  assert.match(source, /from '\.\/http'/)
  assert.doesNotMatch(source, /from '\.\/workspaceHttp'/)
})

test('查询把北京日界换算成 UTC 时刻并只带上已填的筛选项', () => {
  const calls = []
  const api = load('../src/api/auditLogs.ts', {
    './http': { request: url => { calls.push(url); return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 }) } }
  })
  api.listAuditLogs({ from: '2026-10-01', to: '2026-10-07', action: 'file.purge', page: 2 })
  const query = new URLSearchParams(calls[0].split('?')[1])
  assert.ok(calls[0].startsWith('/api/v1/audit-logs?'))
  assert.equal(query.get('date_from'), '2026-09-30T16:00:00.000Z')
  assert.equal(query.get('date_to'), '2026-10-07T15:59:59.000Z')
  assert.equal(query.get('action'), 'file.purge')
  assert.equal(query.get('page'), '2')
  assert.equal(query.get('page_size'), '50')
  assert.equal(query.get('resource_type'), null)
  assert.equal(query.get('resource_id'), null)
})

test('超出服务端窗口上限时在前端就挡下', () => {
  const api = load('../src/api/auditLogs.ts', { './http': { request: () => Promise.resolve({}) } })
  assert.equal(api.auditWindowDays('2026-10-01', '2026-10-31'), 31)
  assert.equal(api.auditWindowDays('2026-10-01', '2026-11-01'), 32)
  assert.equal(api.auditWindowDays('2026-10-09', '2026-10-09'), 1)
})

test('动作与资源翻译有词典也保留原文兜底', () => {
  const labels = load('../src/utils/auditActions.ts')
  assert.equal(labels.describeAuditAction('academic.teaching_class.roster.replace'), '教务·替换教学班名单')
  assert.equal(labels.describeAuditAction('account.administrator.bootstrap'), '账号·初始化平台管理员')
  assert.equal(labels.describeAuditAction('volunteer.unavailability.decide'), '志愿者·处理不可用申请')
  assert.equal(labels.describeAuditAction('mystery.domain.code'), 'mystery·domain·code')
  assert.equal(labels.describeAuditResource('teaching_class'), '教学班')
  assert.equal(labels.describeAuditResource('not_indexed'), 'not_indexed')
  assert.ok(labels.AUDIT_ACTION_CODES.includes('campus.grant.create'))
  assert.ok(labels.AUDIT_ACTION_CODES.every(code => code.includes('.')))
})
