import assert from 'node:assert/strict';
import { beforeEach, afterEach, test } from 'node:test';
import { setSession, getAccessToken, getRefreshToken, clearSession, hasSession } from '../miniprogram/utils/session.js';

const storage = new Map();

beforeEach(() => {
  storage.clear();
  globalThis.wx = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
  };
});

afterEach(() => delete globalThis.wx);

test('saving login credentials makes the authenticated session readable', () => {
  setSession({ access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer', expires_in: 900 });
  assert.equal(getAccessToken(), 'access-1');
  assert.equal(getRefreshToken(), 'refresh-1');
  assert.equal(hasSession(), true);
});

test('clearing session removes both credentials and authenticated state', () => {
  setSession({ access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer', expires_in: 900 });
  clearSession();
  assert.equal(getAccessToken(), '');
  assert.equal(getRefreshToken(), '');
  assert.equal(hasSession(), false);
});
