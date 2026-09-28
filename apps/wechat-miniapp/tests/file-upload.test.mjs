import assert from 'node:assert/strict';
import { beforeEach, afterEach, test } from 'node:test';
import { uploadSubmissionPhoto } from '../miniprogram/api/file.js';

const storage = new Map();
const uploads = [];
const requests = [];
let uploadHandler;
let requestHandler;

function uploadResponse(options, statusCode, body) {
  queueMicrotask(() => options.success({ statusCode, data: JSON.stringify(body), header: {} }));
}

beforeEach(() => {
  storage.clear();
  uploads.length = 0;
  requests.length = 0;
  uploadHandler = () => assert.fail('Unexpected upload');
  requestHandler = () => assert.fail('Unexpected request');
  globalThis.wx = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    uploadFile: (options) => { uploads.push(options); uploadHandler(options); },
    request: (options) => { requests.push(options); requestHandler(options); },
  };
});

afterEach(() => delete globalThis.wx);

test('photo upload uses authenticated multipart field and returns backend file ID', async () => {
  storage.set('access_token', 'access-1');
  uploadHandler = (options) => {
    assert.ok(options.url.endsWith('/api/v1/files'));
    assert.ok(!options.url.includes('apifoxmock.com'));
    assert.equal(options.filePath, 'wxfile://photo-1');
    assert.equal(options.name, 'file');
    assert.deepEqual(options.formData, { category: 'SUBMISSION_PHOTO' });
    assert.equal(options.header.Authorization, 'Bearer access-1');
    uploadResponse(options, 200, { data: { id: '42', category: 'SUBMISSION_PHOTO', status: 'READY' }, requestId: 'req-upload' });
  };
  const file = await uploadSubmissionPhoto('wxfile://photo-1');
  assert.equal(file.id, '42');
  assert.equal(uploads.length, 1);
  assert.equal(requests.length, 0);
});

test('expired upload authorization refreshes once and retries with the rotated access token', async () => {
  storage.set('access_token', 'access-old');
  storage.set('refresh_token', 'refresh-old');
  uploadHandler = (options) => {
    if (options.header.Authorization === 'Bearer access-old') {
      uploadResponse(options, 401, { code: 'UNAUTHORIZED', message: 'expired', requestId: 'req-old' });
    } else {
      assert.equal(options.header.Authorization, 'Bearer access-new');
      uploadResponse(options, 200, { data: { id: '43', category: 'SUBMISSION_PHOTO', status: 'READY' }, requestId: 'req-new' });
    }
  };
  requestHandler = (options) => {
    assert.ok(options.url.endsWith('/api/v1/auth/refresh'));
    assert.deepEqual(options.data, { refresh_token: 'refresh-old' });
    queueMicrotask(() => options.success({ statusCode: 200, data: { data: { access_token: 'access-new', refresh_token: 'refresh-new', token_type: 'bearer', expires_in: 900 }, requestId: 'req-refresh' }, header: {} }));
  };
  const file = await uploadSubmissionPhoto('wxfile://photo-2');
  assert.equal(file.id, '43');
  assert.equal(uploads.length, 2);
  assert.equal(requests.length, 1);
  assert.equal(storage.get('refresh_token'), 'refresh-new');
});

test('server validation error is surfaced without refreshing or uploading twice', async () => {
  storage.set('access_token', 'access-1');
  uploadHandler = (options) => uploadResponse(options, 422, { code: 'VALIDATION_ERROR', message: '图片过大', requestId: 'req-error' });
  await assert.rejects(uploadSubmissionPhoto('wxfile://large'), (error) => {
    assert.equal(error.code, 'VALIDATION_ERROR');
    assert.equal(error.message, '图片过大');
    return true;
  });
  assert.equal(uploads.length, 1);
  assert.equal(requests.length, 0);
});
