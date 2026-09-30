import { getApprovalList, initialReview, finalReview } from '../../api/admin';
import { getRecord } from '../../api/record';
import { getFileAccess } from '../../api/file';
import { getUserInfo } from '../../api/user';
import Toast from 'tdesign-miniprogram/toast/index';

const typeNames = { NORMAL: '正常', LEAVE: '请假', LATE: '迟到', ABSENT: '旷课' };

function confirmAction(content) {
  return new Promise(resolve => {
    wx.showModal({ title: '确认审核', content, success: result => resolve(result.confirm), fail: () => resolve(false) });
  });
}

Page({
  data: {
    approvals: [], mode: 'initial', page: 0, total: 0,
    canInitialReview: false, canFinalReview: false, canCorrectAttendance: false,
    loading: false, workingId: '',
  },

  async onShow() {
    try {
      const user = await getUserInfo();
      const permissions = user.permissions || [];
      const canInitialReview = permissions.includes('objection.initial_review');
      const canFinalReview = permissions.includes('objection.final_review');
      this.setData({
        canInitialReview, canFinalReview,
        canCorrectAttendance: permissions.includes('attendance.correct'),
        mode: canInitialReview ? 'initial' : 'final',
      });
      if (canInitialReview || canFinalReview) await this.refreshList();
    } catch (error) {
      Toast({ context: this, selector: '#t-toast', message: error.message || '无法获取审核权限' });
    }
  },

  async onModeChange(e) {
    const mode = e.currentTarget.dataset.mode;
    if ((mode === 'initial' && !this.data.canInitialReview) ||
        (mode === 'final' && !this.data.canFinalReview)) return;
    this.setData({ mode });
    await this.refreshList();
  },

  onReachBottom() {
    if (this.data.approvals.length < this.data.total) return this.fetchData();
    return undefined;
  },

  async refreshList() {
    const activeFetch = this._activeFetch;
    this.setData({ page: 0, approvals: [], total: 0 });
    if (activeFetch) await activeFetch;
    await this.fetchData();
  },

  fetchData() {
    if (this._activeFetch) return this._activeFetch;
    const { mode, canInitialReview, canFinalReview } = this.data;
    if ((mode === 'initial' && !canInitialReview) || (mode === 'final' && !canFinalReview)) return Promise.resolve();
    const request = this._fetchPage(mode);
    this._activeFetch = request;
    request.then(() => { if (this._activeFetch === request) this._activeFetch = null; });
    return request;
  },

  async _fetchPage(mode) {
    this.setData({ loading: true });
    try {
      wx.showLoading({ title: '加载中' });
      const nextPage = this.data.page + 1;
      const response = await getApprovalList({
        page: nextPage, page_size: 20, final_status: 'PENDING',
        ...(mode === 'initial' ? { initial_status: 'PENDING' } : {}),
      });
      const approvals = await Promise.all((response.items || []).map(async item => {
        let attendance;
        try { attendance = await getRecord(item.attendance_record_id); } catch { attendance = null; }
        return {
          ...item,
          studentName: attendance?.name || `学生 #${item.student_id}`,
          studentNo: attendance?.student_no || '',
          courseName: attendance?.task?.course_name_snapshot || '查课记录',
          date: attendance?.task?.inspection_date || '',
          currentTypeName: typeNames[attendance?.effective_type] || attendance?.effective_type || '未知',
          desiredTypeName: typeNames[item.desired_type] || item.desired_type,
          finalType: item.desired_type,
          currentVersion: attendance?.current_version || null,
          fileIds: item.file_ids || [],
        };
      }));
      if (mode === this.data.mode) this.setData({
        approvals: this.data.approvals.concat(approvals), page: nextPage, total: response.total || 0,
      });
    } catch (error) {
      Toast({ context: this, selector: '#t-toast', message: error.message || '异议列表加载失败' });
    } finally {
      wx.hideLoading();
      this.setData({ loading: false });
    }
  },

  async previewImage(e) {
    try {
      const access = await getFileAccess(e.currentTarget.dataset.id);
      wx.previewImage({ current: access.url, urls: [access.url] });
    } catch (error) {
      Toast({ context: this, selector: '#t-toast', message: error.message || '材料预览失败' });
    }
  },

  onFinalTypeChange(e) {
    const id = e.currentTarget.dataset.id;
    const value = e.detail.value;
    if (!Object.prototype.hasOwnProperty.call(typeNames, value)) return;
    this.setData({
      approvals: this.data.approvals.map(item => item.id === id ? { ...item, finalType: value } : item),
    });
  },

  async handleApprove(e) {
    await this.review(e.currentTarget.dataset.id, true);
  },

  async handleReject(e) {
    await this.review(e.currentTarget.dataset.id, false);
  },

  async review(id, approve) {
    if (this.data.workingId) return;
    const item = this.data.approvals.find(candidate => candidate.id === id);
    if (!item) return;
    const { mode } = this.data;
    this.setData({ workingId: id });
    try {
      let record;
      if (mode === 'final') {
        record = await getRecord(item.attendance_record_id);
        if (approve && record.effective_type !== item.finalType && !this.data.canCorrectAttendance) {
          throw new Error('终审改判还需要考勤更正权限');
        }
      }
      const content = mode === 'initial'
        ? `确认${approve ? '初核通过' : '初核驳回'}？初核不会改变考勤结果。`
        : `确认${approve ? `终审通过，认定为${typeNames[item.finalType]}` : '终审驳回'}？当前认定为${typeNames[record.effective_type] || record.effective_type}。`;
      if (!await confirmAction(content)) return;
      wx.showLoading({ title: '处理中' });
      if (mode === 'initial') {
        await initialReview(id, { decision: approve ? 'PASSED' : 'REJECTED' });
      } else {
        await finalReview(id, {
          decision: approve ? 'APPROVED' : 'REJECTED',
          ...(approve ? { final_type: item.finalType } : {}),
          current_version: record.current_version,
        });
      }
      Toast({ context: this, selector: '#t-toast', message: mode === 'initial' ? '初核已记录' : '终审已完成', theme: 'success' });
      await this.refreshList();
    } catch (error) {
      Toast({ context: this, selector: '#t-toast', message: error.message || '审核失败' });
      if (error.code === 'VERSION_CONFLICT' || error.code === 'STATE_CONFLICT') await this.refreshList();
    } finally {
      wx.hideLoading();
      this.setData({ workingId: '' });
    }
  },
});
