import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { getRecordList, getRecord, getObjections, submitAppeal } from '../miniprogram/api/record.js';
import { getApprovalList, initialReview, finalReview } from '../miniprogram/api/admin.js';
import { getFileAccess, uploadObjectionProof } from '../miniprogram/api/file.js';

afterEach(() => delete globalThis.wx);

function backend(body) {
  const calls = [];
  globalThis.wx = {
    getStorageSync: (key) => key === 'access_token' ? 'access-1' : undefined,
    getExtConfigSync: () => ({}),
    request: (options) => {
      calls.push(options);
      queueMicrotask(() => options.success({ statusCode: 200, data: { data: body } }));
    },
    uploadFile: (options) => {
      calls.push(options);
      queueMicrotask(() => options.success({ statusCode: 200, data: JSON.stringify({ data: { id: '7', category: 'OBJECTION_PROOF' } }) }));
    },
  };
  return calls;
}

test('student record adapters use scoped paged attendance and objection endpoints', async () => {
  const calls = backend({ items: [], total: 0 });
  await getRecordList({ page: 2, page_size: 20 });
  await getRecord('42');
  await getObjections({ attendance_record_id: '42', final_status: 'PENDING' });
  await submitAppeal('42', { desired_type: 'NORMAL', reason: '误判', file_ids: ['7'] });
  assert.deepEqual(calls.map(c => [c.method, new URL(c.url).pathname]), [
    ['GET', '/api/v1/me/attendance'],
    ['GET', '/api/v1/attendance/42'],
    ['GET', '/api/v1/objections'],
    ['POST', '/api/v1/attendance/42/objections'],
  ]);
  assert.deepEqual(calls[0].data, { page: 2, page_size: 20 });
  assert.deepEqual(calls[2].data, { attendance_record_id: '42', final_status: 'PENDING' });
  assert.deepEqual(calls[3].data, { desired_type: 'NORMAL', reason: '误判', file_ids: ['7'] });
});

test('review adapters keep initial and final decisions distinct', async () => {
  const calls = backend({ items: [], total: 0 });
  await getApprovalList({ page: 1, page_size: 20, final_status: 'PENDING' });
  await initialReview('5', { decision: 'PASSED', comment: '材料属实' });
  await finalReview('5', { decision: 'APPROVED', final_type: 'NORMAL', current_version: 2 });
  assert.deepEqual(calls.map(c => [c.method, new URL(c.url).pathname]), [
    ['GET', '/api/v1/objections'],
    ['POST', '/api/v1/objections/5/initial-review'],
    ['POST', '/api/v1/objections/5/final-review'],
  ]);
  assert.deepEqual(calls[2].data, { decision: 'APPROVED', final_type: 'NORMAL', current_version: 2 });
});

test('proof upload sends authenticated OBJECTION_PROOF and preview resolves signed URL', async () => {
  const calls = backend({ url: '/api/v1/files/7/download?expires=1&sig=abc', expires_in: 60 });
  const uploaded = await uploadObjectionProof('wxfile://photo');
  const access = await getFileAccess('7');
  assert.equal(uploaded.id, '7');
  assert.equal(calls[0].formData.category, 'OBJECTION_PROOF');
  assert.equal(calls[0].filePath, 'wxfile://photo');
  assert.equal(calls[0].header.Authorization, 'Bearer access-1');
  assert.equal(new URL(calls[1].url).pathname, '/api/v1/files/7/access');
  assert.equal(access.url, 'http://127.0.0.1:18080/api/v1/files/7/download?expires=1&sig=abc');
});
