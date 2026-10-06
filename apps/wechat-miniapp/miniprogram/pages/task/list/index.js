import { getTaskList } from '../../../api/task';

Page({
  data: {
    status: 'TODO',
    tasks: []
  },

  onShow() {
    this.fetchTasks();
  },

  onTabChange(e) {
    this.setData(
      { status: e.detail.value },
      () => {
        this.fetchTasks();
      }
    );
  },

  async fetchTasks() {
    try {
      wx.showLoading({ title: '加载中' });
      const res = await getTaskList();
      const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
      const listData = Array.isArray(res) ? res : (res?.items || []);
      const allTasks = listData.map(item => {
        // 兼容新旧字段名
        const dateStr = item.inspection_date || item.date;
        const d = new Date(dateStr);
        const dayStr = Number.isNaN(d.getDay()) ? '' : ' 星期' + dayNames[d.getDay()];
        const week = item.week_no || item.academicWeek;
        const periodStr = (item.start_period && item.end_period) 
            ? `${item.start_period}-${item.end_period}` 
            : item.period;

        return {
          ...item,
          courseName: item.course_name_snapshot || item.courseName,
          classroom: item.classroom_snapshot || item.classroom,
          className: item.class_name_snapshot || item.className,
          status: item.status, // 后端已经返回中文如 '待执行', '已逾期'
          timeStr: `第${week}周${dayStr} ${periodStr}节`
        };
      });

      const currentTab = this.data.status;
      const tasks = allTasks.filter(item => {
        if (currentTab === 'TODO') {
          return item.status === '待执行';
        } else if (currentTab === 'DONE') {
          return item.status === '待审核' || item.status === '已完成';
        } else if (currentTab === 'CLOSED') {
          return item.status === '已逾期';
        }
        return false;
      });

      this.setData({ tasks });
    } catch (err) {
      console.error(err);
    } finally {
      wx.hideLoading();
    }
  },

  goToDetail(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: `/pages/task/detail/index?id=${id}`
    });
  }
});
