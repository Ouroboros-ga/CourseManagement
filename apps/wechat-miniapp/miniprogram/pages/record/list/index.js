import { getRecordList } from '../../../api/record';

Page({
  data: {
    records: []
  },

  onShow() {
    this.fetchData();
  },

  async fetchData() {
    try {
      wx.showLoading({ title: '加载中' });
      const res = await getRecordList();
      const listData = Array.isArray(res) ? res : (res?.items || []);
      const typeMap = {
        'NORMAL': '正常',
        'LATE': '迟到',
        'ABSENT': '旷课',
        'LEAVE': '请假'
      };
      
      const records = listData.map(item => {
        const t = item.task || {};
        return {
          ...item,
          courseName: t.course_name_snapshot || t.courseName || '未知课程',
          status: typeMap[item.effective_type] || item.status || '正常',
          date: t.inspection_date || item.date || '未知时间',
          period: item.period || '-',
          classroom: t.classroom_snapshot || item.classroom || '-',
          hasAppealed: item.objection_status === 'PENDING' || item.hasAppealed
        };
      });
      this.setData({ records });
    } catch (err) {
      console.error(err);
    } finally {
      wx.hideLoading();
    }
  },

  goToAppeal(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: `/pages/record/appeal/index?id=${id}`
    });
  }
});
