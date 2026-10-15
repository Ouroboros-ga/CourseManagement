import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

test('change request aliases preserve exact BIGINT strings and backend paths', async () => {
  const calls = [];
  const source = readFileSync(new URL('../miniprogram/api/task.js', import.meta.url), 'utf8')
    .replace(/^import .*;\s*$/gm, '').replace(/export const /g, 'const ');
  const api = vm.runInNewContext(source + ';({createChangeRequest,requestChangeAssignment,getMyAssignmentChangeRequests})', {
    request: options => { calls.push(options); return Promise.resolve({}); }
  });
  await api.requestChangeAssignment('9007199254740993', '');
  await api.getMyAssignmentChangeRequests({ page: 2 });
  assert.equal(calls[0].url, '/api/v1/assignment-change-requests');
  assert.equal(calls[0].data.assignment_id, '9007199254740993');
  assert.equal(calls[1].url, '/api/v1/me/assignment-change-requests');
});

test('upstream UI does not remove the future inspection date gate', async () => {
  let options;
  const source = readFileSync(new URL('../miniprogram/pages/task/detail/index.js', import.meta.url), 'utf8')
    .replace(/^import .*;\s*$/gm, '');
  vm.runInNewContext(source, {
    Page: value => { options = value; },
    wx: { showLoading() {}, hideLoading() {} }, console,
    getTaskDetail: async () => ({ id: '1', status: '待执行', inspection_date: '2099-01-01' }),
    getMyAssignmentChangeRequests: async () => ({ items: [] }),
    getMySubmissions: async () => ({ items: [] }), formatPeriodText: () => '', Toast() {}
  });
  const page = { ...options, data: { ...options.data }, setData(value) { Object.assign(this.data, value); } };
  await page.fetchDetail('1');
  assert.equal(page.data.task.isFuture, true);
});

test('submission keeps student and file BIGINT ids as strings', async () => {
  let options;
  let submitted;
  const source = readFileSync(new URL('../miniprogram/pages/task/detail/index.js', import.meta.url), 'utf8')
    .replace(/^import .*;\s*$/gm, '');
  vm.runInNewContext(source, {
    Page: value => { options = value; },
    wx: { showLoading() {}, hideLoading() {}, navigateBack() {} },
    Toast() {}, setTimeout() {},
    submitTaskResult: async (_id, value) => { submitted = value; }
  });
  await options.handleSubmit.call({ data: {
    taskId: '1', task: { inspection_date: '2020-01-01' }, resultType: 'ABNORMAL',
    abnormalList: [{ studentId: '9007199254740993', type: '迟到' }],
    fileList: [{ file_id: '9007199254740995' }]
  }});
  assert.equal(submitted.abnormal_items[0].student_id, '9007199254740993');
  assert.equal(submitted.file_ids[0], '9007199254740995');
});
