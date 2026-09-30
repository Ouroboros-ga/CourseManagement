import { getRecordList } from '../../../api/record';

const PAGE_SIZE = 20;
const typeNames = { NORMAL: '正常', LEAVE: '请假', LATE: '迟到', ABSENT: '旷课' };

function displayRecord(item) {
  return {
    ...item,
    courseName: item.task?.course_name_snapshot || (item.task?.inspection_type === 'MORNING_STUDY' ? '早自习' : '晚自习'),
    className: item.task?.class_name_snapshot || '—',
    date: item.task?.inspection_date || '—',
    statusName: typeNames[item.effective_type] || item.effective_type,
    statusTheme: item.effective_type === 'NORMAL' ? 'success' : 'warning',
  };
}

Page({
  data: { records: [], page: 0, total: 0, loading: false },

  onShow() {
    this.setData({ records: [], page: 0, total: 0 });
    this.fetchData();
  },

  onReachBottom() {
    if (this.data.records.length < this.data.total) return this.fetchData();
    return undefined;
  },

  async fetchData() {
    if (this.data.loading) return;
    this.setData({ loading: true });
    try {
      wx.showLoading({ title: '加载中' });
      const nextPage = this.data.page + 1;
      const result = await getRecordList({ page: nextPage, page_size: PAGE_SIZE });
      this.setData({
        records: this.data.records.concat((result.items || []).map(displayRecord)),
        page: nextPage,
        total: result.total || 0,
      });
    } catch (error) {
      wx.showToast({ title: error.message || '考勤加载失败', icon: 'none' });
    } finally {
      wx.hideLoading();
      this.setData({ loading: false });
    }
  },

  goToAppeal(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/record/appeal/index?id=${id}` });
  },
});
