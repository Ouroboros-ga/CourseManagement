import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const miniRoot = new URL('../miniprogram/', import.meta.url);

function mountPage(relativePath, dependencies = {}) {
  const path = fileURLToPath(new URL(relativePath, miniRoot));
  const source = readFileSync(path, 'utf8').replace(/^import .*;\s*$/gm, '');
  const storage = new Map();
  const calls = { toasts: [], navigation: [] };
  const wx = {
    showLoading() {},
    hideLoading() {},
    showToast: (options) => calls.toasts.push(options),
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    navigateBack: () => calls.navigation.push('back'),
    navigateTo: (options) => calls.navigation.push(options.url),
  };
  let options;
  vm.runInNewContext(source, {
    Page: (value) => { options = value; },
    wx,
    Toast: () => {},
    setTimeout: (callback) => callback(),
    console,
    ...dependencies,
  }, { filename: path });
  const page = {
    ...options,
    data: { ...options.data },
    setData(changes, callback) {
      Object.assign(this.data, changes);
      callback?.();
    },
  };
  return { page, storage, calls };
}

const task = (id, status, startPeriod = 1) => ({
  id,
  task_key: `task-${id}`,
  semester_id: '2',
  inspection_date: '2026-09-28',
  week_no: 3,
  inspection_type: 'COURSE',
  start_period: startPeriod,
  end_period: startPeriod + 1,
  course_name_snapshot: '高数',
  class_name_snapshot: 'A班',
  classroom_snapshot: '101',
  require_photo_snapshot: false,
  expected_count_current: 32,
  status,
});

test('task list reads later pages before filtering backend Chinese statuses', async () => {
  const requestedPages = [];
  const { page } = mountPage('pages/task/list/index.js', {
    getTaskList: async (params) => {
      requestedPages.push(params.page);
      return params.page === 1
        ? { items: [task('1', '已完成')], page: 1, page_size: 1, total: 2 }
        : { items: [task('2', '待执行', 3)], page: 2, page_size: 1, total: 2 };
    },
  });

  await page.fetchTasks();
  assert.deepEqual(requestedPages, [1, 2]);
  assert.equal(page.data.tasks.length, 1);
  assert.equal(page.data.tasks[0].id, '2');
  assert.equal(page.data.tasks[0].timeStr, '第3周 星期一 第3-4节');

  page.data.status = 'DONE';
  await page.fetchTasks();
  assert.equal(page.data.tasks.length, 1);
  assert.equal(page.data.tasks[0].status, '已完成');
});

test('overdue task remains available for a late submission', async () => {
  const { page } = mountPage('pages/task/detail/index.js', {
    getTaskDetail: async () => task('9', '已逾期'),
  });
  await page.fetchDetail('9');
  assert.equal(page.data.task.canSubmit, true);
  assert.equal(page.data.task.expectedCount, 32);
});

test('roster search keeps internal student ID separate from displayed student number', async () => {
  const { page, storage } = mountPage('pages/task/abnormal/index.js', {
    getTaskRoster: async () => ({
      task_id: '9',
      roster_version: 1,
      items: [
        { student_id: '18', student_no: '20260001', name: '王明' },
        { student_id: '19', student_no: '20260002', name: '李晨' },
      ],
    }),
  });
  page.data.taskId = '9';
  await page.loadRoster('9');
  page.onKeywordChange({ detail: { value: '20260001' } });
  await page.handleSearch();
  assert.equal(page.data.searchResults.length, 1);
  page.addStudent({ currentTarget: { dataset: { item: page.data.searchResults[0] } } });
  page.handleConfirm();

  const selected = storage.get('selectedAbnormal');
  assert.equal(selected.taskId, '9');
  assert.equal(selected.items[0].studentId, '18');
  assert.equal(selected.items[0].studentNo, '20260001');
  assert.equal(selected.items[0].type, 'ABSENT');
});

test('submission sends backend student IDs and uploaded file IDs, then disables resubmission', async () => {
  let submission;
  const { page } = mountPage('pages/task/detail/index.js', {
    submitTaskResult: async (_id, body) => { submission = body; },
  });
  Object.assign(page.data, {
    taskId: '9',
    task: { ...task('9', '待执行'), requirePhoto: true, canSubmit: true },
    resultType: 'ABNORMAL',
    abnormalList: [{ studentId: '18', studentNo: '20260001', name: '王明', type: 'ABSENT' }],
    fileList: [{ id: '7', url: 'wxfile://photo' }],
  });

  await page.handleSubmit();
  assert.deepEqual(JSON.parse(JSON.stringify(submission)), {
    result: 'ABNORMAL',
    abnormal_items: [{ student_id: '18', attendance_type: 'ABSENT' }],
    file_ids: ['7'],
  });
  assert.equal(page.data.task.status, '待审核');
  assert.equal(page.data.task.canSubmit, false);
});

test('selected abnormal students from another task are discarded', () => {
  const { page, storage } = mountPage('pages/task/detail/index.js');
  page.data.taskId = '9';
  storage.set('selectedAbnormal', {
    taskId: '8',
    items: [{ studentId: '18', studentNo: '20260001', name: '王明', type: 'ABSENT' }],
  });
  page.onShow();
  assert.equal(page.data.abnormalList.length, 0);
  assert.equal(storage.has('selectedAbnormal'), false);
});

test('photo upload retains an earlier successful file when a later file fails', async () => {
  let count = 0;
  const { page } = mountPage('pages/task/detail/index.js', {
    uploadSubmissionPhoto: async () => {
      count += 1;
      if (count === 2) throw new Error('第二张失败');
      return { id: '7', status: 'READY' };
    },
  });
  await page.onAddPhoto({ detail: { files: [{ url: 'wxfile://one' }, { url: 'wxfile://two' }] } });
  assert.equal(page.data.fileList.length, 1);
  assert.equal(page.data.fileList[0].id, '7');
  assert.equal(page.data.uploading, false);
});
