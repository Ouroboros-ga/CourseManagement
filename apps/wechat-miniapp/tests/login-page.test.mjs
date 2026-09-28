import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { test } from 'node:test';

const pagePath = fileURLToPath(new URL('../miniprogram/pages/login/index.js', import.meta.url));

function mountLoginPage({ loginResult = { need_binding: true }, userInfo = { binding_required: true }, loginCode = 'wx-once' } = {}) {
  const calls = { login: [], binding: [], switchTab: [], errors: [], warnings: [] };
  let pageOptions;
  const wx = {
    login: ({ success }) => success({ code: loginCode }),
    showLoading: () => {},
    hideLoading: () => {},
    switchTab: (options) => calls.switchTab.push(options),
  };
  // The WeChat runtime supplies Page and resolves these app imports. Evaluate the
  // real page methods with only those external boundaries replaced.
  const source = readFileSync(pagePath, 'utf8').replace(/^import .*;\s*$/gm, '');
  vm.runInNewContext(source, {
    Page: (options) => { pageOptions = options; },
    wx,
    login: async (data) => { calls.login.push(data); return loginResult; },
    getUserInfo: async () => userInfo,
    hasSession: () => false,
    bindStudent: async (data) => { calls.binding.push(data); return { student_no: data.student_no }; },
    Toast: () => {},
    Message: {
      error: (options) => calls.errors.push(options),
      warning: (options) => calls.warnings.push(options),
    },
    setTimeout: (callback) => callback(),
    console,
  }, { filename: pagePath });
  const page = {
    ...pageOptions,
    data: { ...pageOptions.data },
    setData(data) { Object.assign(this.data, data); },
  };
  return { page, calls };
}

const plain = (value) => JSON.parse(JSON.stringify(value));

test('binding page sends WeChat code then student number and one-time code', async () => {
  const { page, calls } = mountLoginPage();
  await page.handleWechatLogin();
  assert.equal(page.data.needBinding, true);
  page.data.studentNo = '2026001';
  page.data.bindingCode = 'bind-once';
  await page.handleBind();
  assert.deepEqual(plain(calls.login), [{ code: 'wx-once' }]);
  assert.deepEqual(plain(calls.binding), [{ student_no: '2026001', binding_code: 'bind-once' }]);
  assert.deepEqual(plain(calls.switchTab), [{ url: '/pages/index/index' }]);
  assert.equal(page.data.bindingCode, '');
  assert.equal(calls.errors.length, 0);
});

test('already bound WeChat user reaches home without a binding request', async () => {
  const { page, calls } = mountLoginPage({ loginResult: { need_binding: false }, userInfo: { binding_required: false } });
  await page.handleWechatLogin();
  assert.deepEqual(plain(calls.login), [{ code: 'wx-once' }]);
  assert.equal(calls.binding.length, 0);
  assert.deepEqual(plain(calls.switchTab), [{ url: '/pages/index/index' }]);
});

test('missing one-time code never sends student identity to backend', async () => {
  const { page, calls } = mountLoginPage();
  page.data.studentNo = '2026001';
  await page.handleBind();
  assert.equal(calls.binding.length, 0);
  assert.equal(calls.switchTab.length, 0);
  assert.ok(calls.warnings.length + calls.errors.length > 0);
});
