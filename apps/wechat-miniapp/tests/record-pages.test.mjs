import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const miniRoot = new URL('../miniprogram/', import.meta.url);

function mountPage(relativePath, dependencies = {}) {
  const path = fileURLToPath(new URL(relativePath, miniRoot));
  const source = readFileSync(path, 'utf8').replace(/^import .*;\s*$/gm, '');
  const events = { navigation: [], toasts: [] };
  const wx = {
    showLoading() {}, hideLoading() {},
    showToast: (options) => events.toasts.push(options),
    navigateTo: (options) => events.navigation.push(options.url),
    navigateBack: () => events.navigation.push('back'),
    reLaunch: (options) => events.navigation.push(options.url),
  };
  let options;
  vm.runInNewContext(source, {
    Page: (value) => { options = value; }, wx,
    Toast: (options) => events.toasts.push(options),
    setTimeout: (callback) => callback(), console,
    ...dependencies,
  }, { filename: path });
  const page = {
    ...options, data: { ...options.data },
    setData(changes, callback) { Object.assign(this.data, changes); callback?.(); },
  };
  return { page, events };
}

const record = (id, type = 'ABSENT') => ({
  id, effective_type: type, current_version: 2,
  task: { inspection_date: '2026-09-28', course_name_snapshot: '高数', class_name_snapshot: '计科一班' },
});

test('home uses current permissions to expose student and review entries', async () => {
  const { page } = mountPage('pages/index/index.js', {
    hasSession: () => true,
    getUserInfo: async () => ({
      display_name: '李同学', roles: ['STUDENT_AFFAIRS_MANAGER'],
      permissions: ['attendance.read', 'objection.initial_review'],
    }),
  });
  await page.fetchUserInfo();
  assert.equal(page.data.isVolunteer, false);
  assert.equal(page.data.canViewRecords, false);
  assert.equal(page.data.canReviewObjections, true);
  page.goToAdminPanel();
});

test('student record page reads paged own attendance and maps actual DTO fields', async () => {
  const pages = [];
  const { page } = mountPage('pages/record/list/index.js', {
    getRecordList: async (params) => {
      pages.push(params.page);
      return params.page === 1
        ? { items: [record('11')], page: 1, page_size: 1, total: 2 }
        : { items: [record('12', 'NORMAL')], page: 2, page_size: 1, total: 2 };
    },
  });
  await page.fetchData();
  assert.equal(page.data.records[0].courseName, '高数');
  assert.equal(page.data.records[0].statusName, '旷课');
  assert.equal(page.data.records[0].className, '计科一班');
  await page.onReachBottom();
  assert.deepEqual(pages, [1, 2]);
  assert.equal(page.data.records.length, 2);
});

test('record appeal entry opens history even when an objection may be pending', async () => {
  const { page, events } = mountPage('pages/record/list/index.js', {
    getObjections: async () => ({ items: [{ id: '6', final_status: 'PENDING' }], total: 1 }),
  });
  await page.goToAppeal({ currentTarget: { dataset: { id: '11' } } });
  assert.deepEqual(events.navigation, ['/pages/record/appeal/index?id=11']);
});

test('appeal page shows pending review status and blocks another submission', async () => {
  const { page } = mountPage('pages/record/appeal/index.js', {
    getRecord: async () => record('11'),
    getObjections: async () => ({ items: [{ id: '6', reason: '已请假', initial_status: 'PASSED', final_status: 'PENDING' }] }),
  });
  await page.onLoad({ id: '11' });
  assert.equal(page.data.blocked, true);
  assert.equal(page.data.latestStatusName, '待终审');
  assert.equal(page.data.latestReason, '已请假');
});

test('appeal uploads proof to file IDs and submits explicit desired type', async () => {
  const uploads = [];
  let body;
  const { page, events } = mountPage('pages/record/appeal/index.js', {
    getRecord: async () => record('11'),
    getObjections: async () => ({ items: [], total: 0 }),
    uploadObjectionProof: async (path) => { uploads.push(path); return { id: '7' }; },
    submitAppeal: async (_id, data) => { body = data; },
  });
  await page.onLoad({ id: '11' });
  page.onDesiredTypeChange({ detail: { value: 'NORMAL' } });
  page.onReasonChange({ detail: { value: '误判' } });
  await page.onAddPhoto({ detail: { files: [{ url: 'wxfile://proof' }] } });
  await page.handleSubmit();
  assert.deepEqual(uploads, ['wxfile://proof']);
  assert.deepEqual(JSON.parse(JSON.stringify(body)), {
    desired_type: 'NORMAL', reason: '误判', file_ids: ['7'],
  });
  assert.deepEqual(events.navigation, ['back']);
});

test('appeal permits submitting without a reason', async () => {
  let body;
  const { page, events } = mountPage('pages/record/appeal/index.js', {
    submitAppeal: async (_id, data) => { body = data; },
  });
  Object.assign(page.data, { recordId: '11', currentType: 'ABSENT', desiredType: 'NORMAL', reason: '' });
  await page.handleSubmit();
  assert.equal(body?.reason, '');
  assert.deepEqual(events.navigation, ['back']);
});

test('appeal blocks same desired type and duplicate submission while uploading', async () => {
  let calls = 0;
  const { page } = mountPage('pages/record/appeal/index.js', {
    submitAppeal: async () => { calls += 1; },
  });
  Object.assign(page.data, { recordId: '11', currentType: 'ABSENT', desiredType: 'ABSENT', reason: '误判' });
  await page.handleSubmit();
  assert.equal(calls, 0);
  Object.assign(page.data, { desiredType: 'NORMAL', uploading: true });
  await page.handleSubmit();
  assert.equal(calls, 0);
});
