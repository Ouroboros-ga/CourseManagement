import { getTaskList, getMyAssignmentChangeRequests } from '../../../api/task';
import { formatPeriodText } from '../../../utils/period';

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
      const [res, changeReqRes] = await Promise.all([
        getTaskList({ page_size: 100, include_canceled: true }),
        getMyAssignmentChangeRequests({ page_size: 100 }).catch(() => ({ items: [] }))
      ]);
      const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
      const listData = Array.isArray(res) ? res : (res?.items || []);
      const changeReqList = Array.isArray(changeReqRes) ? changeReqRes : (changeReqRes?.items || []);

      // 构建针对每个任务的最新调班申请映射
      const changeReqMap = {};
      changeReqList.forEach(req => {
        const tid = req.task_id;
        if (!tid) return;
        const existing = changeReqMap[tid];
        if (!existing || Number(req.id) > Number(existing.id)) {
          changeReqMap[tid] = req;
        }
      });

      const allTasks = listData.map(item => {
        // 兼容新旧字段名
        const dateStr = item.inspection_date || item.date;
        const d = new Date(dateStr);
        const dayStr = Number.isNaN(d.getDay()) ? '' : ' 星期' + dayNames[d.getDay()];
        const week = item.week_no || item.academicWeek;
        const periodText = formatPeriodText(item.start_period, item.end_period, true);

        // 换班申请状态派生
        const req = changeReqMap[item.id];
        let displayStatus = item.status;
        let statusTagClass = 'tag-primary';
        let isChangePending = false;
        let isChangeRejected = false;
        let changeRejectComment = '';

        if (req && req.status === 'PENDING') {
          displayStatus = '待换班审核';
          statusTagClass = 'tag-warning';
          isChangePending = true;
        } else if (req && req.status === 'REJECTED') {
          // 换班被驳回，恢复原任务状态，并记录驳回理由
          isChangeRejected = true;
          changeRejectComment = req.comment || '';
          if (item.status === '待执行') {
            statusTagClass = 'tag-primary';
          } else if (item.status === '已逾期') {
            statusTagClass = 'tag-danger';
          } else if (item.status === '已完成') {
            statusTagClass = 'tag-success';
          } else {
            statusTagClass = 'tag-default';
          }
        } else {
          // 默认根据系统任务状态分类
          if (item.status === '待执行') {
            statusTagClass = 'tag-primary';
          } else if (item.status === '已逾期') {
            statusTagClass = 'tag-danger';
          } else if (item.status === '已完成') {
            statusTagClass = 'tag-success';
          } else {
            statusTagClass = 'tag-default';
          }
        }

        return {
          ...item,
          courseName: item.course_name_snapshot || item.courseName,
          classroom: item.classroom_snapshot || item.classroom,
          className: item.class_name_snapshot || item.className,
          status: item.status, // 后端已经返回中文如 '待执行', '已逾期', '已取消'
          cancel_reason: item.cancel_reason,
          displayStatus,
          statusTagClass,
          isChangePending,
          isChangeRejected,
          changeRejectComment,
          timeStr: `第${week}周${dayStr} ${periodText || (item.period ? item.period + '节' : '')}`
        };
      });

      const currentTab = this.data.status;
      const tasks = allTasks.filter(item => {
        if (currentTab === 'TODO') {
          return item.displayStatus === '待执行' || item.displayStatus === '待换班审核';
        } else if (currentTab === 'DONE') {
          return item.status === '待审核' || item.status === '已完成';
        } else if (currentTab === 'CLOSED') {
          return item.status === '已逾期' || item.status === '已取消';
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
