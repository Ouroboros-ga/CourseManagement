import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const module = { exports: {} }
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022
  } }).outputText, { module, exports: module.exports, require: name => imports[name], URLSearchParams, Error })
  return module.exports
}

test('snapshot display pages preserve full data and reset after filtering', async () => {
  const { useDisplayPage } = load('../src/composables/useDisplayPage.ts', { vue })
  const source = vue.ref(Array.from({ length: 105 }, (_, i) => ({ id: String(9007199254740993n + BigInt(i)) })))
  const scope = vue.effectScope()
  const state = scope.run(() => useDisplayPage(() => source.value))
  assert.equal(state.total.value, 105)
  assert.equal(state.rows.value.length, 50)
  state.page.value = 3
  assert.equal(state.rows.value.length, 5)
  assert.equal(source.value.length, 105)
  source.value = source.value.filter(row => row.id.endsWith('7'))
  await vue.nextTick()
  assert.equal(state.page.value, 1)
  assert.equal(state.total.value, source.value.length)
  scope.stop()
})

test('explicit detail collection fetches all pages in bounded requests', async () => {
  const { collectPages } = load('../src/utils/collectPages.ts')
  const source = Array.from({ length: 105 }, (_, i) => ({ id: `00${i}` }))
  const calls = []
  const rows = await collectPages(async (page, size) => {
    calls.push([page, size])
    return { total: source.length, items: source.slice((page - 1) * size, page * size) }
  })
  assert.equal(rows.length, 105)
  assert.equal(rows[0].id, '000')
  assert.deepEqual(calls, [[1, 50], [2, 50], [3, 50]])
})

test('incomplete, changed and obsolete collections are never reported as complete', async () => {
  const { collectPages } = load('../src/utils/collectPages.ts')
  await assert.rejects(collectPages(async () => ({ items: [], total: 2 })), /分页不完整/)
  await assert.rejects(collectPages(async () => ({ items: [{ id: 'same' }], total: 2 })), /发生变化/)
  await assert.rejects(collectPages(async page => ({ items: [{ id: String(page) }], total: page === 1 ? 2 : 3 })), /发生变化/)
  let active = true, calls = 0
  const rows = await collectPages(async () => {
    calls++; active = false
    return { total: 100, items: [{ id: '1' }] }
  }, () => active)
  assert.equal(calls, 1)
  assert.equal(rows.length, 0)
})

test('task filters and export share query serialization with string identifiers', async () => {
  const urls = []
  const { listTasks, exportTasks } = load('../src/api/tasks.ts', {
    './workspaceHttp': { request: async url => { urls.push(url); return { items: [], total: 0 } } }
  })
  const query = { page: 3, page_size: 50, keyword: '高数%', status: 'OVERDUE',
    pending_change: true, teaching_class_id: '9007199254740993', inspection_date: '2026-10-20' }
  await listTasks(query)
  await exportTasks(query)
  const list = new URL(urls[0], 'https://example.invalid')
  const exported = new URL(urls[1], 'https://example.invalid')
  assert.equal(list.search, exported.search)
  assert.equal(list.searchParams.get('teaching_class_id'), query.teaching_class_id)
  assert.equal(list.searchParams.get('keyword'), query.keyword)
  assert.equal(list.searchParams.get('pending_change'), 'true')
  assert.equal(exported.pathname, '/api/v1/inspection-tasks/export')
})
