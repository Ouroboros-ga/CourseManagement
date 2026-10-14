import { getApprovalList, approveAppeal, rejectAppeal, initialReviewObjection } from '../../api/admin';
import { getUserInfo } from '../../api/user';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    approvals: [],
    canFinalReview: true
  },

  async onShow() {
    await this.checkPermissions();
    this.fetchData();
  },

  async onPullDownRefresh() {
    await this.fetchData();
    wx.stopPullDownRefresh();
  },

  async checkPermissions() {
    try {
      const data = await getUserInfo();
      const perms = data.permissions || [];
      this.setData({ canFinalReview: perms.includes('objection.final_review') });
    } catch (err) {
      console.error(err);
    }
  },

  async fetchData() {
    try {
      wx.showLoading({ title: '加载中' });
      const params = this.data.canFinalReview ? { final_status: 'PENDING' } : { initial_status: 'PENDING' };
      const res = await getApprovalList(params);
      const listData = Array.isArray(res) ? res : (res?.items || []);
      const formattedList = listData.map(item => {
        const t = item.task || {};
        return {
          ...item,
          studentName: item.student_name || item.name || '未知学生',
          studentId: item.student_no || item.student_id || '-',
          courseName: t.course_name_snapshot || item.course_name || '未知课程',
          date: t.inspection_date || item.date || '未知时间',
          className: t.class_name_snapshot || item.class_name || '-',
          type: item.desired_type === 'NORMAL' ? '正常' : (item.desired_type === 'ABSENT' ? '旷课' : item.desired_type === 'LATE' ? '迟到' : item.desired_type === 'LEAVE' ? '请假' : item.desired_type)
        };
      });
      this.setData({ approvals: formattedList });
    } catch (err) {
      console.error(err);
    } finally {
      wx.hideLoading();
    }
  },

  previewImage(e) {
    const { url, urls } = e.currentTarget.dataset;
    wx.previewImage({ current: url, urls });
  },

  async handleApprove(e) {
    const id = e.currentTarget.dataset.id;
    const version = e.currentTarget.dataset.version;
    try {
      wx.showLoading({ title: '处理中' });
      if (this.data.canFinalReview) {
        await approveAppeal(id, version);
      } else {
        await initialReviewObjection(id, 'PASSED');
      }
      Toast({ context: this, selector: '#t-toast', message: '已同意', theme: 'success' });
      this.fetchData();
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '操作失败' });
    } finally {
      wx.hideLoading();
    }
  },

  async handleReject(e) {
    const id = e.currentTarget.dataset.id;
    const version = e.currentTarget.dataset.version;

    try {
      const comment = await new Promise((resolve, reject) => {
        wx.showModal({
          title: '驳回异议审批',
          content: '',
          editable: true,
          placeholderText: '请输入驳回理由（必填）',
          success: (res) => {
            if (res.confirm) {
              if (!res.content.trim()) {
                wx.showToast({ title: '理由不能为空', icon: 'none' });
                reject(new Error('empty'));
              } else {
                resolve(res.content);
              }
            } else {
              reject(new Error('cancel'));
            }
          }
        });
      });

      wx.showLoading({ title: '处理中' });
      if (this.data.canFinalReview) {
        await rejectAppeal(id, version, comment);
      } else {
        await initialReviewObjection(id, 'REJECTED', comment);
      }
      Toast({ context: this, selector: '#t-toast', message: '已驳回', theme: 'success' });
      this.fetchData();
    } catch (err) {
      if (err.message !== 'cancel' && err.message !== 'empty') {
        Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '操作失败' });
      }
    } finally {
      wx.hideLoading();
    }
  }
});
