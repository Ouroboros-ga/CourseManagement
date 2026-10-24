import assert from 'node:assert/strict';
import test, { afterEach } from 'node:test';
import { getCampusRuntime, getObjectionProgress } from '../miniprogram/api/record.js';

afterEach(() => { delete globalThis.wx; });
function backend() {
  const calls = [];
  globalThis.wx = {
    getStorageSync: key => key === 'token' ? 'synthetic-session' : '',
    request(options) {
      calls.push(options);
      queueMicrotask(() => options.success({ statusCode: 200, data: { data: { ok: true } } }));
    }
  };
  return calls;
}

test('student progress uses current Bearer transport and preserves full string ID', async () => {
  const calls = backend();
  await getCampusRuntime();
  await getObjectionProgress('9007199254740993');
  assert.deepEqual(calls.map(call => [call.method, new URL(call.url).pathname]), [
    ['GET', '/api/v1/me/campus-runtime'],
    ['GET', '/api/v1/me/objections/9007199254740993/progress']
  ]);
  assert.equal(calls[1].header.Authorization, 'Bearer synthetic-session');
  assert.equal(calls[1].data, undefined);
});

test('invalid or rounded IDs never create a request', async () => {
  const calls = backend();
  for (const id of [0, 1, 9007199254740993, null, '', '0', '01', '../1', '9223372036854775808']) {
    await assert.rejects(getObjectionProgress(id), /编号无效/);
  }
  assert.equal(calls.length, 0);
  await getObjectionProgress('9223372036854775807');
  assert.equal(calls.length, 1);
});
