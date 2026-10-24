import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function fixture(fetch) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL('../src/api/http.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, Headers, fetch, Error, console })
  module.exports.setAccessToken('synthetic-token')
  return module.exports
}
test('authenticated download returns the blob and server UTF-8 filename', async () => {
  const calls = []
  const api = fixture(async (...args) => {
    calls.push(args)
    return new Response('report bytes', { headers: { 'Content-Type': 'application/octet-stream',
      'Content-Disposition': "attachment; filename*=UTF-8''%E8%80%83%E5%8B%A4.xlsx" } })
  })
  const file = await api.request('/api/v1/test-report', { method: 'GET' }, false, 'download')
  assert.equal(file.filename, '考勤.xlsx')
  assert.equal(await file.blob.text(), 'report bytes')
  assert.equal(calls[0][1].headers.get('Authorization'), 'Bearer synthetic-token')
  assert.equal(calls[0][1].credentials, 'include')
})
test('401 refresh retries the same download once with the new token', async () => {
  const calls = []
  const api = fixture(async (url, options) => {
    calls.push([url, options])
    if (calls.length === 1) return new Response('{}', { status: 401 })
    if (url === '/api/v1/auth/refresh') return Response.json({ data: { access_token: 'rotated-token' } })
    return new Response('retry report', { headers: { 'Content-Disposition': 'attachment; filename="report.xlsx"' } })
  })
  const file = await api.request('/api/v1/test-report', {}, false, 'download')
  assert.equal(file.filename, 'report.xlsx')
  assert.equal(await file.blob.text(), 'retry report')
  assert.equal(calls.length, 3)
  assert.equal(calls[2][1].headers.get('Authorization'), 'Bearer rotated-token')
})
test('error responses are rejected rather than downloaded as reports', async () => {
  const api = fixture(async () => Response.json({ code: 'PERMISSION_DENIED', message: '权限已变化' }, { status: 403 }))
  await assert.rejects(api.request('/api/v1/test-report', {}, false, 'download'), { status: 403 })
})
test('existing JSON and blob modes keep their original result shapes', async () => {
  const api = fixture(async url => url === '/json' ? Response.json({ data: { ok: true } }) : new Response('old blob'))
  assert.equal((await api.request('/json')).ok, true)
  assert.equal(await (await api.request('/blob', {}, false, 'blob')).text(), 'old blob')
})

test('a second 401 stops without another refresh or any downloaded result', async () => {
  let calls = 0
  const api = fixture(async url => {
    calls++
    return url === '/api/v1/auth/refresh' ? Response.json({ data: { access_token: 'still-invalid' } }) : new Response('{}', { status: 401 })
  })
  await assert.rejects(api.request('/api/v1/test-report', {}, false, 'download'), { status: 401 })
  assert.equal(calls, 3)
})
