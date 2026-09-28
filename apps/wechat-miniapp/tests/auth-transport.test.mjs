import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { getBaseURL } from '../miniprogram/utils/env.js';
import { request } from '../miniprogram/utils/request.js';
import { login, bindStudent, getUserInfo, logout } from '../miniprogram/api/user.js';

const storage = new Map();
const calls = [];
let handler;

function respond(options, statusCode, data) {
  queueMicrotask(() => options.success({ statusCode, data, header: {} }));
}

beforeEach(() => {
  storage.clear();
  calls.length = 0;
  handler = () => assert.fail('Unexpected wx.request');
  globalThis.wx = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    request: (options) => {
      calls.push(options);
      handler(options);
    },
    showToast: () => {},
    reLaunch: () => {},
  };
});

afterEach(() => {
  delete globalThis.wx;
});

test('backend envelope resolves data without an application code field', async () => {
  handler = (options) => respond(options, 200, { data: { id: 17, role: 'STUDENT' }, requestId: 'req-1' });
  assert.deepEqual(await request({ url: '/api/v1/me' }), { id: 17, role: 'STUDENT' });
});

test('backend error preserves its code and message for the caller', async () => {
  handler = (options) => respond(options, 400, { code: 'BINDING_CODE_INVALID', message: '绑定码无效', requestId: 'req-2' });
  await assert.rejects(request({ url: '/api/v1/me/student-binding', method: 'POST' }), (error) => {
    assert.equal(error.code, 'BINDING_CODE_INVALID');
    assert.equal(error.message, '绑定码无效');
    return true;
  });
});

test('login uses WeChat endpoint and stores both tokens for the next authenticated call', async () => {
  handler = (options) => {
    assert.ok(!options.url.includes('apifoxmock.com'));
    if (options.url.endsWith('/api/v1/auth/wechat/login')) {
      assert.equal(options.method, 'POST');
      assert.deepEqual(options.data, { code: 'wx-once' });
      assert.equal(options.header.Authorization, undefined);
      respond(options, 200, { data: { access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer', expires_in: 900, need_binding: true }, requestId: 'req-login' });
    } else if (options.url.endsWith('/api/v1/me')) {
      assert.equal(options.header.Authorization, 'Bearer access-1');
      respond(options, 200, { data: { id: 17 }, requestId: 'req-me' });
    } else assert.fail(`Unexpected URL: ${options.url}`);
  };
  await login({ code: 'wx-once' });
  assert.deepEqual(await getUserInfo(), { id: 17 });
  assert.equal(calls.length, 2);
});

test('binding sends only student number and one-time binding code to current backend', async () => {
  handler = (options) => {
    assert.ok(options.url.endsWith('/api/v1/me/student-binding'));
    assert.ok(!options.url.includes('apifoxmock.com'));
    assert.equal(options.method, 'POST');
    assert.deepEqual(options.data, { student_no: '2026001', binding_code: 'secret-once' });
    respond(options, 200, { data: { student_no: '2026001' }, requestId: 'req-bind' });
  };
  await bindStudent({ student_no: '2026001', binding_code: 'secret-once' });
});

test('one 401 refreshes with JSON token, retries once, and rotates stored credentials', async () => {
  storage.set('access_token', 'access-old');
  storage.set('refresh_token', 'refresh-old');
  handler = (options) => {
    if (options.url.endsWith('/api/v1/auth/refresh')) {
      assert.equal(options.method, 'POST');
      assert.deepEqual(options.data, { refresh_token: 'refresh-old' });
      respond(options, 200, { data: { access_token: 'access-new', refresh_token: 'refresh-new', token_type: 'bearer', expires_in: 900 }, requestId: 'req-refresh' });
    } else if (options.header.Authorization === 'Bearer access-old') {
      respond(options, 401, { code: 'UNAUTHORIZED', message: 'expired', requestId: 'req-old' });
    } else {
      assert.equal(options.header.Authorization, 'Bearer access-new');
      respond(options, 200, { data: { id: 17 }, requestId: 'req-retry' });
    }
  };
  assert.deepEqual(await request({ url: '/api/v1/me' }), { id: 17 });
  assert.equal(calls.length, 3);
  assert.equal(storage.get('refresh_token'), 'refresh-new');
});

test('simultaneous 401 responses share one refresh request', async () => {
  storage.set('access_token', 'access-old');
  storage.set('refresh_token', 'refresh-old');
  handler = (options) => {
    if (options.url.endsWith('/api/v1/auth/refresh')) {
      respond(options, 200, { data: { access_token: 'access-new', refresh_token: 'refresh-new', token_type: 'bearer', expires_in: 900 }, requestId: 'req-refresh' });
    } else if (options.header.Authorization === 'Bearer access-old') {
      respond(options, 401, { code: 'UNAUTHORIZED', message: 'expired', requestId: 'req-old' });
    } else {
      respond(options, 200, { data: { id: 17 }, requestId: 'req-retry' });
    }
  };
  const result = await Promise.all([request({ url: '/api/v1/me' }), request({ url: '/api/v1/me' })]);
  assert.deepEqual(result, [{ id: 17 }, { id: 17 }]);
  assert.equal(calls.filter((call) => call.url.endsWith('/api/v1/auth/refresh')).length, 1);
});

test('a retry that also returns 401 stops instead of refreshing again', async () => {
  storage.set('access_token', 'access-old');
  storage.set('refresh_token', 'refresh-old');
  handler = (options) => {
    if (options.url.endsWith('/api/v1/auth/refresh')) respond(options, 200, { data: { access_token: 'access-new', refresh_token: 'refresh-new', token_type: 'bearer', expires_in: 900 }, requestId: 'req-refresh' });
    else respond(options, 401, { code: 'UNAUTHORIZED', message: 'expired', requestId: 'req-401' });
  };
  await assert.rejects(request({ url: '/api/v1/me' }));
  assert.equal(calls.length, 3);
});

test('logout accepts HTTP 204 and clears local tokens', async () => {
  storage.set('access_token', 'access-1');
  storage.set('refresh_token', 'refresh-1');
  handler = (options) => {
    assert.ok(options.url.endsWith('/api/v1/auth/logout'));
    assert.equal(options.method, 'POST');
    assert.equal(options.header.Authorization, 'Bearer access-1');
    respond(options, 204, undefined);
  };
  await logout();
  assert.equal(storage.get('access_token'), undefined);
  assert.equal(storage.get('refresh_token'), undefined);
});

test('configured backend is concrete and never points at old Apifox mock', () => {
  const baseURL = getBaseURL();
  assert.match(baseURL, /^https?:\/\//);
  assert.ok(!baseURL.includes('apifoxmock.com'));
  assert.ok(!baseURL.includes('<服务器IP>'));
});
