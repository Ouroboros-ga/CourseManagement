import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../miniprogram/pages/record/list/index.js', import.meta.url), 'utf8')
  .replace(/^import .*;\s*$/gm, '');
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
const record = (id = '9') => ({ id: '6', courseName: '合成课程', objection: { id, final_status: 'PENDING', reason: '合成理由' } });
const progress = (id = '9', stage = 'ACADEMIC_REVIEW') => ({ objection_id: id, stage, label: '等待教务审核', description: '预审不代表正式结论', final_status: 'PENDING', updated_at: null });

function fixture(overrides = {}) {
  let options, token = 'synthetic-token';
  const calls = [];
  const wx = { getStorageSync: () => token, showLoading() {}, hideLoading() {}, navigateTo() {} };
  vm.runInNewContext(source, {
    Page: value => { options = value; }, wx, console,
    getCampusRuntime: async () => { calls.push(['runtime']); return { objection_precheck: true }; },
    getObjectionProgress: async id => { calls.push(['progress', id]); return progress(id); },
    getRecordList: async () => ({ items: [] }), getMyObjections: async () => ({ items: [] }),
    ...overrides,
  });
  const page = { ...options, data: { ...options.data }, setData(value) { Object.assign(this.data, value); } };
  const open = item => page.showObjectionDetail({ currentTarget: { dataset: { record: item || record() } } });
  return { page, calls, open, setToken: value => { token = value; } };
}

test('detail reads only selected objection and presents progress separately from the formal record', async () => {
  const f = fixture();
  await f.open();
  assert.deepEqual(f.calls, [['runtime'], ['progress', '9']]);
  assert.equal(f.page.data.progressData.stage, 'ACADEMIC_REVIEW');
  assert.equal(f.page.data.selectedRecord.objection.final_status, 'PENDING');
  assert.equal(f.page.data.progressLoading, false);
});
test('feature explicitly disabled hides the progress block and skips the progress endpoint', async () => {
  const f = fixture({ getCampusRuntime: async () => ({ objection_precheck: false }) });
  await f.open();
  assert.equal(f.page.data.progressVisible, false);
  assert.equal(f.page.data.progressData, null);
  assert.equal(f.calls.length, 0);
});
test('missing runtime flag and failed reads remain visible errors, never disabled or submitted', async () => {
  for (const overrides of [
    { getCampusRuntime: async () => ({}) },
    { getCampusRuntime: async () => { throw new Error('network'); } },
    { getObjectionProgress: async () => { throw { code: 'NOT_FOUND' }; } },
  ]) {
    const f = fixture(overrides); await f.open();
    assert.equal(f.page.data.progressVisible, true);
    assert.equal(f.page.data.progressData, null);
    assert.match(f.page.data.progressError, /无法读取/);
  }
});
test('new selected case wins over a delayed response from the old case', async () => {
  let release;
  const f = fixture({ getObjectionProgress: async id => id === '9' ? new Promise(resolve => { release = resolve; }) : progress(id) });
  const old = f.open(); await flush();
  await f.open(record('10'));
  release(progress()); await old;
  assert.equal(f.page.data.progressData.objection_id, '10');
});
test('closing or leaving the page prevents late responses from restoring private content', async () => {
  for (const exit of ['closeDetailModal', 'onHide', 'onUnload']) {
    let release;
    const f = fixture({ getObjectionProgress: () => new Promise(resolve => { release = resolve; }) });
    const pending = f.open(); await flush(); f.page[exit]();
    release(progress()); await pending;
    assert.equal(f.page.data.progressData, null);
  }
});
test('account/token changes discard old data before another endpoint is called', async () => {
  let release;
  const f = fixture({ getCampusRuntime: () => new Promise(resolve => { release = resolve; }) });
  const pending = f.open(); await flush(); f.setToken('different-session');
  release({ objection_precheck: true }); await pending;
  assert.equal(f.page.data.showDetailModal, false);
  assert.equal(f.page.data.selectedRecord, null);
  assert.equal(f.page.data.progressData, null);
  assert.equal(f.calls.length, 0);
});
test('refresh clears old progress on failure and does not automatically retry or submit', async () => {
  let fail = false, calls = 0;
  const f = fixture({ getObjectionProgress: async id => { calls++; if (fail) throw new Error('timeout'); return progress(id); } });
  await f.open(); fail = true;
  await f.page.refreshProgress();
  assert.equal(calls, 2);
  assert.equal(f.page.data.progressData, null);
  assert.match(f.page.data.progressError, /刷新/);
  assert.equal(f.page.data.selectedRecord.objection.final_status, 'PENDING');
});
test('wrong-case, malformed and contradictory progress responses cannot be displayed', async () => {
  for (const value of [progress('10'), { ...progress(), stage: 'PRIVATE_INTERNAL' }, { ...progress(), stage: 'COMPLETED' }]) {
    const f = fixture({ getObjectionProgress: async () => value }); await f.open();
    assert.equal(f.page.data.progressData, null);
    assert.match(f.page.data.progressError, /无法读取/);
  }
});
test('extra execution fields are never copied into page data', async () => {
  const f = fixture({ getObjectionProgress: async () => ({ ...progress(), run_token: 'private', job_id: '99', result: { secret: true } }) });
  await f.open();
  assert.equal(JSON.stringify(Object.keys(f.page.data.progressData).sort()), JSON.stringify(['objection_id', 'stage', 'label', 'description', 'final_status', 'updated_at'].sort()));
});
test('list chooses latest 64-bit objection ID without converting it to a Number', async () => {
  const f = fixture({ getRecordList: async () => ({ items: [{ id: '6', effective_type: 'ABSENT' }] }), getMyObjections: async () => ({ items: [
    { id: '9007199254740992', attendance_record_id: '6', final_status: 'PENDING' },
    { id: '9007199254740993', attendance_record_id: '6', final_status: 'PENDING' },
  ] }) });
  await f.page.fetchData();
  assert.equal(f.page.data.records[0].objection.id, '9007199254740993');
});

test('historical initial review does not become the current formal outcome', async () => {
  const f = fixture({ getRecordList: async () => ({ items: [{ id: '6', effective_type: 'ABSENT' }] }), getMyObjections: async () => ({ items: [
    { id: '9', attendance_record_id: '6', initial_status: 'REJECTED', final_status: 'PENDING' },
  ] }) });
  await f.page.fetchData();
  assert.equal(f.page.data.records[0].objectionStatusStr, '异议处理中');
});

test('an account change also rejects a delayed attendance list response', async () => {
  let release;
  const f = fixture({ getRecordList: () => new Promise(resolve => { release = resolve; }) });
  const pending = f.page.fetchData(); await flush(); f.setToken('different-account');
  release({ items: [{ id: '6', effective_type: 'ABSENT' }] }); await pending;
  assert.equal(f.page.data.records.length, 0);
  assert.match(f.page.data.recordsError, /登录状态已变化/);
});

test('refresh is single-flight while progress is loading', async () => {
  let release, reads = 0;
  const f = fixture({ getObjectionProgress: () => { reads++; return new Promise(resolve => { release = resolve; }); } });
  const pending = f.open(); await flush(); await f.page.refreshProgress();
  assert.equal(reads, 1);
  release(progress()); await pending;
});

test('completed progress can report a final outcome without pretending to update attendance', async () => {
  const f = fixture({ getObjectionProgress: async () => ({ ...progress(), stage: 'COMPLETED', final_status: 'APPROVED' }) });
  await f.open();
  assert.equal(f.page.data.progressData.final_status, 'APPROVED');
  assert.equal(f.page.data.selectedRecord.objection.final_status, 'PENDING');
});

test('token changes while progress is in flight also close and clear the detail', async () => {
  let release;
  const f = fixture({ getObjectionProgress: () => new Promise(resolve => { release = resolve; }) });
  const pending = f.open(); await flush(); f.setToken('different-session');
  release(progress()); await pending;
  assert.equal(f.page.data.showDetailModal, false);
  assert.equal(f.page.data.progressData, null);
  assert.equal(f.page.data.selectedRecord, null);
});

test('leaving the page discards delayed attendance data as well as progress', async () => {
  let release;
  const f = fixture({ getRecordList: () => new Promise(resolve => { release = resolve; }) });
  const pending = f.page.fetchData(); await flush(); f.page.onHide();
  release({ items: [{ id: '6', effective_type: 'ABSENT' }] }); await pending;
  assert.equal(f.page.data.records.length, 0);
});

test('failure to read objections keeps attendance visible without claiming no appeal exists', async () => {
  const f = fixture({ getRecordList: async () => ({ items: [{ id: '6', effective_type: 'ABSENT' }] }), getMyObjections: async () => { throw new Error('unavailable'); } });
  await f.page.fetchData();
  assert.equal(f.page.data.records.length, 1);
  assert.equal(f.page.data.objectionsReady, false);
  assert.match(f.page.data.objectionsError, /无法读取申诉状态/);
});
