import { getApprovalList, approveAppeal, rejectAppeal, getSubmissionList, reviewSubmission } from '../../api/admin';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    approvals: [],
    submissions: []
  },

  onShow() {
    this.fetchData();
    this.fetchSubmissions();
  },

  async fetchData() {
    try {
      wx.showLoading({ title: '加载中' });
      const res = await getApprovalList();
      const listData = Array.isArray(res) ? res : (res?.items || []);
      this.setData({ approvals: listData });
    } catch (err) {
      console.error(err);
    } finally {
      wx.hideLoading();
    }
  },

  async fetchSubmissions() {
    try {
      const res = await getSubmissionList();
      const listData = Array.isArray(res) ? res : (res?.items || []);
      this.setData({ submissions: listData });
    } catch (err) {
      console.error('获取提交列表失败', err);
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
      await approveAppeal(id, version);
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
      await rejectAppeal(id, version, comment);
      Toast({ context: this, selector: '#t-toast', message: '已驳回', theme: 'success' });
      this.fetchData();
    } catch (err) {
      if (err.message !== 'cancel' && err.message !== 'empty') {
        Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '操作失败' });
      }
    } finally {
      wx.hideLoading();
    }
  },

  async handleReviewSubmit(e) {
    const id = e.currentTarget.dataset.id;
    const decision = e.currentTarget.dataset.decision; // 'APPROVED' | 'REJECTED'
    
    let comment = '';
    if (decision === 'REJECTED') {
      try {
        const res = await new Promise((resolve, reject) => {
          wx.showModal({
            title: '驳回查课提交',
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
        comment = res;
      } catch (err) {
        return;
      }
    }

    try {
      wx.showLoading({ title: '处理中' });
      await reviewSubmission(id, decision, comment);
      Toast({ context: this, selector: '#t-toast', message: '处理成功', theme: 'success' });
      this.fetchSubmissions();
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '操作失败' });
    } finally {
      wx.hideLoading();
    }
  }
});
