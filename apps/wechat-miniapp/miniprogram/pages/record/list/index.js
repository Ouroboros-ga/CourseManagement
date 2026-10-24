import { getRecordList, getMyObjections, getCampusRuntime, getObjectionProgress } from '../../../api/record';

function laterId(candidate, previous) {
  const next = String(candidate), old = String(previous);
  return next.length > old.length || (next.length === old.length && next > old);
}

function publicProgress(value, objectionId) {
  const stages = ['SUBMITTED', 'PRECHECK_QUEUED', 'PRECHECK_RUNNING', 'ACADEMIC_REVIEW', 'COMPLETED', 'RECORD_WITHDRAWN', 'ARCHIVED'];
  if (!value || value.objection_id !== objectionId || !stages.includes(value.stage)
    || !['PENDING', 'APPROVED', 'REJECTED'].includes(value.final_status)
    || typeof value.label !== 'string' || typeof value.description !== 'string'
    || !(value.updated_at === null || typeof value.updated_at === 'string')
    || (value.stage === 'COMPLETED' && value.final_status === 'PENDING')
    || (value.final_status !== 'PENDING' && !['COMPLETED', 'RECORD_WITHDRAWN'].includes(value.stage))) {
    throw new Error('办理进度响应不完整');
  }
  // 仅保留学生公开字段，执行身份和模型内容不得进入页面数据。
  return { objection_id: value.objection_id, stage: value.stage, label: value.label,
    description: value.description, final_status: value.final_status, updated_at: value.updated_at };
}

Page({
  data: {
    records: [],
    showDetailModal: false,
    selectedRecord: null,
    progressVisible: false,
    progressLoading: false,
    progressError: '',
    progressData: null,
    recordsError: '',
    objectionsReady: false,
    objectionsError: ''
  },

  onShow() {
    this._progressDisposed = false;
    this.closeDetailModal();
    this.setData({ records: [], recordsError: '' });
    return this.fetchData();
  },

  onHide() {
    this._listRequest = (this._listRequest || 0) + 1;
    this.closeDetailModal();
    wx.hideLoading();
  },

  onUnload() {
    this._progressDisposed = true;
    this._progressRequest = (this._progressRequest || 0) + 1;
    this._listRequest = (this._listRequest || 0) + 1;
    wx.hideLoading();
  },

  async onPullDownRefresh() {
    this.closeDetailModal();
    try { await this.fetchData(); } finally { wx.stopPullDownRefresh(); }
  },

  async fetchData() {
    const ticket = this._listRequest = (this._listRequest || 0) + 1;
    const token = wx.getStorageSync('token');
    this.setData({ recordsError: '', objectionsReady: false, objectionsError: '' });
    try {
      wx.showLoading({ title: '加载中' });
      let objectionsUnavailable = false;
      const [res, objRes] = await Promise.all([
        getRecordList(),
        getMyObjections().catch(() => {
          objectionsUnavailable = true;
          return { items: [] };
        }) // 申诉失败仍保留考勤，但不能把未知状态当作没有申诉。
      ]);
      if (ticket !== this._listRequest) return;
      if (token !== wx.getStorageSync('token')) {
        this.closeDetailModal();
        this.setData({ records: [], recordsError: '登录状态已变化，请下拉刷新记录' });
        return;
      }
      if (!Array.isArray(res) && !Array.isArray(res?.items)) throw new Error('考勤响应不完整');
      const listData = Array.isArray(res) ? res : res.items;
      const objectionsReady = !objectionsUnavailable && (Array.isArray(objRes) || Array.isArray(objRes?.items));
      const objList = objectionsReady ? (Array.isArray(objRes) ? objRes : objRes.items) : [];

      const typeMap = {
        'NORMAL': '正常',
        'LATE': '迟到',
        'ABSENT': '旷课',
        'LEAVE': '请假'
      };

      const objMap = {};
      objList.forEach(o => {
        // 保留最新的一笔异议记录
        const existing = objMap[o.attendance_record_id];
        if (!existing || laterId(o.id, existing.id)) {
          objMap[o.attendance_record_id] = o;
        }
      });

      const records = listData.map(item => {
        const t = item.task || {};
        const objection = objMap[item.id];

        let objectionStatusStr = '';
        let objectionTagClass = 'tag-primary';
        let canReAppeal = false;

        if (objection) {
          if (objection.final_status === 'APPROVED') {
            objectionStatusStr = '申诉已通过';
            objectionTagClass = 'tag-success';
          } else if (objection.final_status === 'REJECTED') {
            objectionStatusStr = '终审已驳回';
            objectionTagClass = 'tag-danger';

            // 终审驳回归档后，若在 7 天申诉窗口期内且当前考勤仍为异常，支持重新申诉
            const createdTime = item.created_at ? new Date(item.created_at).getTime() : 0;
            const now = Date.now();
            const isWithinWindow = createdTime > 0 ? (now - createdTime < 7 * 24 * 3600 * 1000) : true;
            if (isWithinWindow && item.effective_type !== 'NORMAL' && item.status !== '正常' && item.status !== '已撤销') {
              canReAppeal = true;
            }
          } else {
            objectionStatusStr = '异议处理中';
            objectionTagClass = 'tag-primary';
          }
        }

        const statusText = typeMap[item.effective_type] || item.status || '正常';
        let statusTagClass = 'tag-success';
        if (statusText === '旷课' || item.effective_type === 'ABSENT') {
          statusTagClass = 'tag-absent';
        } else if (statusText === '迟到' || item.effective_type === 'LATE') {
          statusTagClass = 'tag-late';
        } else if (statusText === '请假' || item.effective_type === 'LEAVE') {
          statusTagClass = 'tag-warning';
        } else if (statusText === '已撤销') {
          statusTagClass = 'tag-default';
        }

        return {
          ...item,
          courseName: t.course_name_snapshot || t.courseName || '未知课程',
          status: statusText,
          statusTagClass,
          date: t.inspection_date || item.date || '未知时间',
          className: t.class_name_snapshot || '-',
          objectionStatusStr,
          objectionTagClass,
          canReAppeal,
          objection: objection || null
        };
      });
      this.setData({ records, objectionsReady,
        objectionsError: objectionsReady ? '' : '暂时无法读取申诉状态，请下拉刷新；考勤记录仍可查看' });
    } catch (err) {
      if (ticket === this._listRequest) this.setData({ records: [], recordsError: '暂时无法读取记录，请下拉刷新' });
    } finally {
      if (ticket === this._listRequest) wx.hideLoading();
    }
  },

  showObjectionDetail(e) {
    const item = e.currentTarget.dataset.record;
    if (!item || !item.objection) return;
    this._progressRequest = (this._progressRequest || 0) + 1;
    this.setData({
      selectedRecord: item,
      showDetailModal: true,
      progressLoading: false,
      progressData: null,
      progressError: '',
      progressVisible: true
    });
    return this.refreshProgress();
  },

  closeDetailModal() {
    this._progressRequest = (this._progressRequest || 0) + 1;
    this.setData({
      showDetailModal: false,
      selectedRecord: null,
      progressVisible: false,
      progressLoading: false,
      progressData: null,
      progressError: ''
    });
  },

  progressTicketCurrent(ticket, objectionId, token) {
    if (this._progressDisposed || ticket !== this._progressRequest || !this.data.showDetailModal
      || this.data.selectedRecord?.objection?.id !== objectionId) return false;
    if (token !== wx.getStorageSync('token')) {
      this.closeDetailModal();
      this._listRequest = (this._listRequest || 0) + 1;
      this.setData({ records: [], recordsError: '登录状态已变化，请下拉刷新记录' });
      wx.hideLoading();
      return false;
    }
    return true;
  },

  async refreshProgress() {
    if (this._progressDisposed || this.data.progressLoading || !this.data.showDetailModal) return;
    const objectionId = this.data.selectedRecord?.objection?.id;
    if (!objectionId) return;
    const ticket = this._progressRequest = (this._progressRequest || 0) + 1;
    const token = wx.getStorageSync('token');
    this.setData({ progressVisible: true, progressLoading: true, progressError: '', progressData: null });
    try {
      const runtime = await getCampusRuntime();
      if (!this.progressTicketCurrent(ticket, objectionId, token)) return;
      if (runtime?.objection_precheck === false) {
        this.setData({ progressVisible: false });
        return;
      }
      if (runtime?.objection_precheck !== true) throw new Error('功能状态未知');
      const value = await getObjectionProgress(objectionId);
      if (!this.progressTicketCurrent(ticket, objectionId, token)) return;
      this.setData({ progressData: publicProgress(value, objectionId) });
    } catch (err) {
      if (this.progressTicketCurrent(ticket, objectionId, token)) {
        this.setData({ progressData: null, progressError: '暂时无法读取办理进度，请稍后刷新' });
      }
    } finally {
      if (this.progressTicketCurrent(ticket, objectionId, token)) this.setData({ progressLoading: false });
    }
  },

  handleModalReAppeal() {
    const item = this.data.selectedRecord;
    this.closeDetailModal();
    if (item) {
      wx.navigateTo({
        url: `/pages/record/appeal/index?id=${item.id}&isReAppeal=1`
      });
    }
  },

  preventBubble() {},

  goToAppeal(e) {
    const id = e.currentTarget.dataset.id;
    const isReAppeal = e.currentTarget.dataset.reappeal ? 1 : 0;
    wx.navigateTo({
      url: `/pages/record/appeal/index?id=${id}&isReAppeal=${isReAppeal}`
    });
  }
});
