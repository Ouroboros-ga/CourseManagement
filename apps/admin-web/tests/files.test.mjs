import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { readFileSync } from 'node:fs'

function load(relative, imports = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports = {}
  new Function('require', 'exports', js)(name => imports[name], exports)
  return exports
}

test('upload sends FormData through authenticated request without JSON content type', async () => {
  let captured
  const api = load('../src/api/files.ts', { './http': { request: async (...args) => { captured = args; return { id: '9007199254740993' } } } })
  const result = await api.uploadFile(new File(['image'], 'test.png', { type: 'image/png' }), 'OBJECTION_PROOF')
  assert.equal(result.id, '9007199254740993')
  assert.equal(captured[0], '/api/v1/files')
  assert.equal(captured[1].body.get('category'), 'OBJECTION_PROOF')
  assert.equal(captured[1].body.get('file').name, 'test.png')
  assert.equal(captured[1].headers, undefined)
})

test('Web explicitly requests direct delivery without changing file identifiers', async () => {
  let captured
  const api = load('../src/api/files.ts', { './http': { request: async path => {
    captured = path
    return { url: 'https://private-bucket.example/photo?signed', expires_in: 30 }
  } } })
  await api.getFileAccess('9007199254740993')
  assert.equal(captured, '/api/v1/files/9007199254740993/access?delivery=direct')
})

test('file links are cached only before expiry and parallel requests are merged', async () => {
  let time = 1000, calls = 0
  const { createFileAccessCache } = load('../src/utils/fileAccessCache.ts')
  const cache = createFileAccessCache(async id => {
    calls++
    return { url: `/api/${id}?v=${calls}`, expires_in: 30 }
  }, () => time)
  const [first, second] = await Promise.all([cache.get('1'), cache.get('1')])
  assert.equal(first, second)
  assert.equal(calls, 1)
  assert.equal(await cache.get('1'), first)
  time += 31000
  assert.notEqual(await cache.get('1'), first)
  assert.equal(calls, 2)
})

test('failed requests can retry and cleared requests cannot populate a new session', async () => {
  const { createFileAccessCache } = load('../src/utils/fileAccessCache.ts')
  let complete, calls = 0
  const cache = createFileAccessCache(() => {
    calls++
    if (calls === 1) return Promise.reject(new Error('offline'))
    if (calls === 2) return new Promise(resolve => { complete = resolve })
    return Promise.resolve({ url: '/new', expires_in: 300 })
  })
  await assert.rejects(cache.get('1'), /offline/)
  const pending = cache.get('1')
  cache.clear()
  complete({ url: '/old', expires_in: 300 })
  await assert.rejects(pending, /访问上下文已变化/)
  assert.equal(await cache.get('1'), '/new')
})

test('image failures retry once automatically and clear removes previous context', async () => {
  let calls = 0, cleanup
  const { createFileAccessCache } = load('../src/utils/fileAccessCache.ts')
  const vue = { ref: value => ({ value }), watch: (_, cb) => { cleanup = cb }, onBeforeUnmount() {} }
  const { useFileAccess } = load('../src/composables/useFileAccess.ts', {
    vue, '../utils/fileAccessCache': { createFileAccessCache },
    '../api/files': { getFileAccess: async () => ({ url: `/image?v=${++calls}`, expires_in: 300 }) }
  })
  const photos = useFileAccess({ value: 'context-1' })
  await photos.getUrl('1')
  await photos.retry('1')
  assert.equal(photos.urls.value['1'], '/image?v=2')
  await photos.retry('1')
  assert.equal(calls, 2)
  assert.ok(photos.errors.value['1'])
  await photos.retry('1', true)
  assert.equal(calls, 3)
  cleanup()
  assert.deepEqual(photos.urls.value, {})
  assert.deepEqual(photos.errors.value, {})
})
