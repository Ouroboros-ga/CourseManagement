import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const source = await readFile(new URL('../src/utils/contextEpoch.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { ContextEpoch, identityContext } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('identity key uses actual /me id contract without bigint conversion', () => {
  assert.equal(identityContext({ id: '9007199254740993', user_id: 'wrong' }), '9007199254740993')
  assert.equal(identityContext(null), '')
  assert.equal(identityContext({ id: 12 }), '')
})

test('newer request wins even within the same college', () => {
  const context = new ContextEpoch(() => 'user:A')
  const oldRequest = context.begin()
  const newRequest = context.begin()
  assert.equal(oldRequest.isCurrent(), false)
  assert.equal(newRequest.isCurrent(), true)
})

test('college and account changes invalidate old responses', () => {
  let key = 'user:A'
  const context = new ContextEpoch(() => key)
  const request = context.begin()
  key = 'user:B'
  assert.equal(request.isCurrent(), false)
  const collegeRequest = context.begin()
  key = 'another-user:B'
  assert.equal(collegeRequest.isCurrent(), false)
})

test('invalidation blocks writes after unmount or logout', () => {
  const context = new ContextEpoch(() => 'user:A')
  const request = context.begin()
  context.invalidate()
  assert.equal(request.isCurrent(), false)
})
