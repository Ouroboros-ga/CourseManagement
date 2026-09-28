import { getTaskList } from '../../../api/task';

const PAGE_SIZE = 100;
const submittedStatuses = new Set(['待审核', '已完成']);

function formatTask(task) {
  const date = new Date(`${task.inspection_date}T00:00:00`);
  const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
  const day = Number.isNaN(date.getDay()) ? '' : ` 星期${dayNames[date.getDay()]}`;
  const periods = task.start_period === task.end_period
    ? `${task.start_period}` : `${task.start_period}-${task.end_period}`;
  return {
    ...task,
    courseName: task.course_name_snapshot || (task.inspection_type === 'MORNING_STUDY' ? '早自习' : '晚自习'),
    className: task.class_name_snapshot || '—',
    classroom: task.classroom_snapshot || '—',
    timeStr: `第${task.week_no}周${day} 第${periods}节`
  };
}

Page({
  data: {
    status: 'TODO',
    tasks: [],
    loading: false
  },

  onShow() {
    this.fetchTasks();
  },

  onTabChange(e) {
    this.setData({ status: e.detail.value }, () => this.fetchTasks());
  },

  async fetchTasks() {
    const selectedStatus = this.data.status;
    this.setData({ loading: true });
    try {
      wx.showLoading({ title: '加载中' });
      const all = [];
      let page = 1;
      while (true) {
        const result = await getTaskList({ page, page_size: PAGE_SIZE, include_canceled: false });
        const items = result.items || [];
        all.push(...items);
        if (!items.length || all.length >= result.total) break;
        page += 1;
      }
      if (selectedStatus !== this.data.status) return;
      const visible = all.filter(task => selectedStatus === 'DONE'
        ? submittedStatuses.has(task.status)
        : task.status === '待执行' || task.status === '已逾期');
      this.setData({ tasks: visible.map(formatTask) });
    } catch (err) {
      console.error('加载查课任务失败', err);
      wx.showToast({ title: err.message || '加载失败', icon: 'none' });
    } finally {
      wx.hideLoading();
      this.setData({ loading: false });
    }
  },

  goToDetail(e) {
    wx.navigateTo({ url: `/pages/task/detail/index?id=${e.currentTarget.dataset.id}` });
  }
});
