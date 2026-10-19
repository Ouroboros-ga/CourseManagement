import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../miniprogram/utils/env.js', import.meta.url), 'utf8')
  .replace(/export const /g, 'const ');

function load(wx) {
  return vm.runInNewContext(source + ';({ env, getBaseURL })', wx ? { wx } : {});
}

test('defaults to production without WeChat storage or when storage is unavailable', () => {
  for (const wx of [undefined, { getStorageSync() { throw new Error('unavailable'); } }]) {
    const config = load(wx);
    assert.equal(config.env, 'prod');
    assert.equal(config.getBaseURL(), 'https://course.zsitai.xyz');
  }
});

test('uses the explicit local debug address and removes whitespace', () => {
  const config = load({ getStorageSync(key) {
    assert.equal(key, 'debugBaseURL');
    return ' http://127.0.0.1:8000 ';
  } });
  assert.equal(config.env, 'dev');
  assert.equal(config.getBaseURL(), 'http://127.0.0.1:8000');
});

test('empty or non-string storage values keep production mode', () => {
  for (const value of ['', '   ', null, false, 123]) {
    const config = load({ getStorageSync: () => value });
    assert.equal(config.env, 'prod');
    assert.equal(config.getBaseURL(), 'https://course.zsitai.xyz');
  }
});
