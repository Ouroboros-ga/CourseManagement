import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const miniRoot = new URL('../miniprogram/', import.meta.url);

function mountAdmin(dependencies = {}) {
  const path = fileURLToPath(new URL('pages/admin/index.js', miniRoot));
  const source = readFileSync(path, 'utf8').replace(/^import .*;\s*$/gm, '');
  const events = { toasts: [], previews: [], modals: [] };
  const wx = {
    showLoading() {}, hideLoading() {},
    showToast: (options) => events.toasts.push(options),
    previewImage: (options) => events.previews.push(options),
    showModal: (options) => { events.modals.push(options); options.success({ confirm: true }); },
  };
  let options;
  vm.runInNewContext(source, {
    Page: (value) => { options = value; }, wx,
    Toast: (options) => events.toasts.push(options),
    console, ...dependencies,
  }, { filename: path });
  const page = {
    ...options, data: { ...options.data },
    setData(changes, callback) { Object.assign(this.data, changes); callback?.(); },
  };
  return { page, events };
}

const objection = {
  id: '9', attendance_record_id: '11', student_id: '18', reason: '已请假',
  desired_type: 'LEAVE', initial_status: 'PENDING', final_status: 'PENDING', file_ids: ['7'],
};
const attendance = {
  id: '11', student_no: '20260001', name: '王明', effective_type: 'ABSENT', current_version: 2,
  task: { course_name_snapshot: '高数', inspection_date: '2026-09-28' },
};

test('student affairs manager sees initial-review list and cannot final-review', async () => {
  const calls = [];
  const { page } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.initial_review'] }),
    getApprovalList: async (params) => { calls.push(params); return { items: [objection], total: 1 }; },
    getRecord: async () => attendance,
  });
  await page.onShow();
  assert.equal(page.data.canInitialReview, true);
  assert.equal(page.data.canFinalReview, false);
  assert.equal(page.data.mode, 'initial');
  assert.equal(calls[0].initial_status, 'PENDING');
  assert.equal(page.data.approvals[0].studentName, '王明');
  assert.equal(page.data.approvals[0].currentVersion, 2);
});

test('review list loads later pages without hiding pending objections', async () => {
  const pages = [];
  const { page } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.initial_review'] }),
    getApprovalList: async (params) => {
      pages.push(params.page);
      return { items: [{ ...objection, id: String(params.page) }], total: 2 };
    },
    getRecord: async () => attendance,
  });
  await page.onShow();
  await page.onReachBottom();
  assert.deepEqual(pages, [1, 2]);
  assert.equal(page.data.approvals.length, 2);
});

test('initial approval sends PASSED and never calls final endpoint', async () => {
  let initialBody;
  let finalCalled = false;
  const { page } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.initial_review'] }),
    getApprovalList: async () => ({ items: [objection], total: 1 }),
    getRecord: async () => attendance,
    initialReview: async (_id, body) => { initialBody = body; },
    finalReview: async () => { finalCalled = true; },
  });
  await page.onShow();
  await page.handleApprove({ currentTarget: { dataset: { id: '9' } } });
  assert.deepEqual(JSON.parse(JSON.stringify(initialBody)), { decision: 'PASSED' });
  assert.equal(finalCalled, false);
});

test('final approval uses desired type and current attendance version', async () => {
  let body;
  const { page, events } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.final_review', 'attendance.correct'] }),
    getApprovalList: async () => ({ items: [objection], total: 1 }),
    getRecord: async () => attendance,
    finalReview: async (_id, data) => { body = data; },
  });
  await page.onShow();
  await page.handleApprove({ currentTarget: { dataset: { id: '9' } } });
  assert.equal(page.data.mode, 'final');
  assert.deepEqual(JSON.parse(JSON.stringify(body)), {
    decision: 'APPROVED', final_type: 'LEAVE', current_version: 2,
  });
  assert.ok(events.modals[0].content.includes('请假'));
});

test('final reviewer may choose a supported classification different from the request', async () => {
  let body;
  const { page, events } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.final_review', 'attendance.correct'] }),
    getApprovalList: async () => ({ items: [objection], total: 1 }),
    getRecord: async () => attendance,
    finalReview: async (_id, data) => { body = data; },
  });
  await page.onShow();
  page.onFinalTypeChange({ currentTarget: { dataset: { id: '9' } }, detail: { value: 'LATE' } });
  await page.handleApprove({ currentTarget: { dataset: { id: '9' } } });
  assert.equal(body.final_type, 'LATE');
  assert.ok(events.modals[0].content.includes('迟到'));
});

test('switching review modes while loading fetches the newly selected list', async () => {
  let releaseInitial;
  let markInitialStarted;
  const initialStarted = new Promise(resolve => { markInitialStarted = resolve; });
  const calls = [];
  const { page } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.initial_review', 'objection.final_review'] }),
    getApprovalList: async (params) => {
      calls.push(params);
      if (params.initial_status) return new Promise(resolve => { releaseInitial = resolve; markInitialStarted(); });
      return { items: [{ ...objection, id: 'final-item' }], total: 1 };
    },
    getRecord: async () => attendance,
  });
  const showing = page.onShow();
  await initialStarted;
  const switching = page.onModeChange({ currentTarget: { dataset: { mode: 'final' } } });
  releaseInitial({ items: [objection], total: 1 });
  await Promise.all([showing, switching]);
  assert.equal(page.data.mode, 'final');
  assert.equal(page.data.approvals[0]?.id, 'final-item');
  assert.equal(calls.length, 2);
});

test('version conflict refreshes instead of showing approval success', async () => {
  let loads = 0;
  const { page, events } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['objection.final_review', 'attendance.correct'] }),
    getApprovalList: async () => { loads += 1; return { items: [objection], total: 1 }; },
    getRecord: async () => attendance,
    finalReview: async () => { const error = new Error('版本冲突'); error.code = 'VERSION_CONFLICT'; throw error; },
  });
  await page.onShow();
  await page.handleApprove({ currentTarget: { dataset: { id: '9' } } });
  assert.equal(loads, 2);
  assert.ok(events.toasts.every(item => item.message !== '处理成功'));
});

test('proof preview requests authorized signed URL on demand', async () => {
  const ids = [];
  const { page, events } = mountAdmin({
    getFileAccess: async (id) => { ids.push(id); return { url: 'https://example.edu/proof' }; },
  });
  await page.previewImage({ currentTarget: { dataset: { id: '7' } } });
  assert.deepEqual(ids, ['7']);
  assert.deepEqual(JSON.parse(JSON.stringify(events.previews[0])), {
    current: 'https://example.edu/proof', urls: ['https://example.edu/proof'],
  });
});

test('review page with no review permission never loads cross-student objections', async () => {
  let called = false;
  const { page } = mountAdmin({
    getUserInfo: async () => ({ permissions: ['attendance.read'] }),
    getApprovalList: async () => { called = true; },
  });
  await page.onShow();
  assert.equal(called, false);
  assert.equal(page.data.canInitialReview, false);
  assert.equal(page.data.canFinalReview, false);
});
