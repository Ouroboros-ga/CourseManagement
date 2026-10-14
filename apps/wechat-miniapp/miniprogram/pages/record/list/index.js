import { getRecordList, getMyObjections } from '../../../api/record';

Page({
  data: {
    records: [],
    showDetailModal: false,
    selectedRecord: null
  },

  onShow() {
    this.fetchData();
  },

  async fetchData() {
    try {
      wx.showLoading({ title: '加载中' });
      const [res, objRes] = await Promise.all([
        getRecordList(),
        getMyObjections().catch(() => ({ items: [] })) // 失败不阻断考勤记录加载
      ]);
      const listData = Array.isArray(res) ? res : (res?.items || []);
      const objList = Array.isArray(objRes) ? objRes : (objRes?.items || []);

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
        if (!existing || Number(o.id) > Number(existing.id)) {
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
          } else if (objection.initial_status === 'REJECTED') {
            objectionStatusStr = '初核已驳回';
            objectionTagClass = 'tag-danger';
          } else if (objection.initial_status === 'APPROVED') {
            objectionStatusStr = '初核已通过';
            objectionTagClass = 'tag-primary';
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
      this.setData({ records });
    } catch (err) {
      console.error(err);
    } finally {
      wx.hideLoading();
    }
  },

  showObjectionDetail(e) {
    const item = e.currentTarget.dataset.record;
    if (!item || !item.objection) return;
    this.setData({
      selectedRecord: item,
      showDetailModal: true
    });
  },

  closeDetailModal() {
    this.setData({
      showDetailModal: false,
      selectedRecord: null
    });
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
