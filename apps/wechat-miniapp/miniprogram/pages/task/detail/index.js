import { getTaskDetail, submitTaskResult, getMySubmissions, createChangeRequest } from '../../../api/task';
import { getMyAssignmentChangeRequests } from '../../../api/task';
import { uploadFile } from '../../../utils/upload';
import Toast from 'tdesign-miniprogram/toast/index';
import { formatPeriodText } from '../../../utils/period';

Page({
  data: {
    taskId: '',
    task: {},
    resultType: 'NORMAL',
    abnormalList: [], // { studentId, name, type }
    fileList: [],
    hasSubmission: false,
    showChangeDialog: false,
    changeReason: ''
  },

  onLoad(options) {
    if (options.id) {
      this.setData({ taskId: options.id });
      this.fetchDetail(options.id);
    }
  },

  onShow() {
    // 从异常选择页面返回时，读取全局存储或事件通道获取已选名单
    const selectedAbnormal = wx.getStorageSync('selectedAbnormal');
    if (selectedAbnormal) {
      this.setData({ abnormalList: selectedAbnormal });
      wx.removeStorageSync('selectedAbnormal');
    }
  },

  async fetchDetail(id) {
    try {
      wx.showLoading();
      const [task, changeReqRes] = await Promise.all([
        getTaskDetail(id),
        getMyAssignmentChangeRequests({ page_size: 100 }).catch(() => ({ items: [] }))
      ]);
      if (task) {
        // 兼容新旧字段
        const dateStr = task.inspection_date || task.date;
        const week = task.week_no || task.academicWeek;
        const periodText = formatPeriodText(task.start_period, task.end_period, true);

        let dayStr = '';
        if (dateStr) {
          const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
          const d = new Date(dateStr);
          dayStr = Number.isNaN(d.getDay()) ? '' : ' 星期' + dayNames[d.getDay()];
        }
        task.timeStr = `第${week}周${dayStr} ${periodText || (task.period ? task.period + '节' : '')}`;
        task.courseName = task.course_name_snapshot || task.courseName;
        task.classroom = task.classroom_snapshot || task.classroom;
        task.className = task.class_name_snapshot || task.className;
        task.expectedCount = task.expected_count_current !== undefined ? task.expected_count_current : (task.expectedCount || task.studentCount);
        task.requirePhoto = task.require_photo_snapshot !== undefined ? task.require_photo_snapshot : task.requirePhoto;

        if (task.deadline_at) {
          const dl = new Date(task.deadline_at);
          // 格式化为 YYYY-MM-DD HH:mm
          const year = dl.getFullYear();
          const month = String(dl.getMonth() + 1).padStart(2, '0');
          const date = String(dl.getDate()).padStart(2, '0');
          const hours = String(dl.getHours()).padStart(2, '0');
          const minutes = String(dl.getMinutes()).padStart(2, '0');
          task.deadlineStr = `${year}-${month}-${date} ${hours}:${minutes}`;
        } else {
          task.deadlineStr = '当天最晚节次后自动计算或23:59';
        }

        if (task.canceled_at) {
          const ct = new Date(task.canceled_at);
          const year = ct.getFullYear();
          const month = String(ct.getMonth() + 1).padStart(2, '0');
          const date = String(ct.getDate()).padStart(2, '0');
          const hours = String(ct.getHours()).padStart(2, '0');
          const minutes = String(ct.getMinutes()).padStart(2, '0');
          task.canceledAtStr = `${year}-${month}-${date} ${hours}:${minutes}`;
        }

        // 限制：只能在查课当天及以后上传数据
        const now = new Date();
        const y = now.getFullYear();
        const m = String(now.getMonth() + 1).padStart(2, '0');
        const d = String(now.getDate()).padStart(2, '0');
        const todayStr = `${y}-${m}-${d}`;
        task.isFuture = Boolean(dateStr && dateStr > todayStr);

        // 提取并匹配针对当前任务的最新调班申请
        const changeReqList = Array.isArray(changeReqRes) ? changeReqRes : (changeReqRes?.items || []);
        const myReqs = changeReqList.filter(r => String(r.task_id) === String(id));
        myReqs.sort((a, b) => Number(b.id) - Number(a.id));
        const latestChangeReq = myReqs[0];

        let displayStatus = task.status;
        let isChangePending = false;
        let isChangeRejected = false;

        if (latestChangeReq && latestChangeReq.status === 'PENDING') {
          displayStatus = '待换班审核';
          isChangePending = true;
        } else if (latestChangeReq && latestChangeReq.status === 'REJECTED') {
          // 若被驳回(REJECTED)，恢复正常任务状态，但标记驳回以便展示理由
          displayStatus = task.status;
          isChangeRejected = true;
        } else {
          // 无申请或其它情况
          displayStatus = task.status;
        }

        task.displayStatus = displayStatus;
        task.isChangePending = isChangePending;
        task.isChangeRejected = isChangeRejected;
        task.latestChangeReq = latestChangeReq || null;
      }
      this.setData({ task });
      this.fetchSubmission(id); // 获取提交明细用于查看已完成记录
    } catch (err) {
      console.error(err);
    } finally {
      wx.hideLoading();
    }
  },

  async fetchSubmission(taskId) {
    try {
      const res = await getMySubmissions(taskId);
      const items = res?.items || res || [];
      if (items.length > 0) {
        const sub = items[0];
        if (this.data.task.status !== '待执行') {
          const reverseTypeMap = {
            'LATE': '迟到',
            'ABSENT': '旷课',
            'LEAVE': '请假'
          };
          const abItems = (sub.abnormal_items || []).map(item => ({
            studentId: item.student_id || item.studentId,
            name: item.name || '未知姓名',
            type: reverseTypeMap[item.attendance_type] || item.attendance_type
          }));

          this.setData({
            resultType: sub.result === 'NORMAL' ? 'NORMAL' : 'ABNORMAL',
            abnormalList: abItems,
            hasSubmission: true
          });
        }
      }
    } catch(err) {
      console.error('获取提交记录失败', err);
    }
  },

  onResultTypeChange(e) {
    this.setData({ resultType: e.detail.value });
    if (e.detail.value === 'NORMAL') {
      this.setData({ abnormalList: [] });
    }
  },

  goToAbnormalPage() {
    wx.setStorageSync('currentAbnormal', this.data.abnormalList);
    wx.navigateTo({
      url: `/pages/task/abnormal/index?taskId=${this.data.taskId}`
    });
  },

  async onAddPhoto(e) {
    const { files } = e.detail;
    wx.showLoading({ title: '上传中...' });

    try {
      const uploadPromises = files.map(file => uploadFile(file.url, 'SUBMISSION_PHOTO'));
      const uploadResults = await Promise.all(uploadPromises);

      const newFiles = files.map((file, index) => ({
        url: file.url, // 用于本地预览
        name: 'photo',
        type: 'image',
        file_id: uploadResults[index].id // 后端返回的文件ID
      }));

      const currentFiles = this.data.fileList;
      this.setData({ fileList: currentFiles.concat(newFiles) });
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: '图片上传失败' });
    } finally {
      wx.hideLoading();
    }
  },

  onRemovePhoto(e) {
    const { index } = e.detail;
    const { fileList } = this.data;
    fileList.splice(index, 1);
    this.setData({ fileList });
  },

  async handleSubmit() {
    const { resultType, abnormalList, fileList, task, taskId } = this.data;

    const dateStr = task.inspection_date || task.date;
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    const todayStr = `${y}-${m}-${d}`;
    if (dateStr && dateStr > todayStr) {
      Toast({ context: this, selector: '#t-toast', message: '尚未到查课日期，只能在查课当天及以后上传数据' });
      return;
    }

    if (resultType === 'ABNORMAL' && abnormalList.length === 0) {
      Toast({ context: this, selector: '#t-toast', message: '请添加异常学生名单' });
      return;
    }

    if (task.requirePhoto && fileList.length === 0) {
      Toast({ context: this, selector: '#t-toast', message: '必须上传现场照片' });
      return;
    }

    try {
      wx.showLoading({ title: '提交中' });

      // 提取上传后获得的文件 IDs
      const fileIds = fileList.map(f => f.file_id).filter(id => id != null).map(String);

      const typeMap = {
        '迟到': 'LATE',
        '旷课': 'ABSENT',
        '请假': 'LEAVE'
      };

      // 组装符合后端要求的异常明细结构
      const abnormalItems = resultType === 'NORMAL' ? [] : abnormalList.map(record => ({
        student_id: String(record.studentId),
        attendance_type: typeMap[record.type] || record.type,
        note: record.note || null
      }));

      await submitTaskResult(taskId, {
        result: resultType, // 'NORMAL' or 'ABNORMAL'
        abnormal_items: abnormalItems,
        file_ids: fileIds,
        note: null
      });

      wx.hideLoading();
      Toast({ context: this, selector: '#t-toast', message: '提交成功', theme: 'success' });
      setTimeout(() => {
        wx.navigateBack();
      }, 1500);
    } catch (err) {
      wx.hideLoading();
      Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '提交失败' });
    }
  },

  onOpenChangeDialog() {
    this.setData({
      showChangeDialog: true,
      changeReason: ''
    });
  },

  onCloseChangeDialog() {
    this.setData({
      showChangeDialog: false
    });
  },

  onChangeReasonChange(e) {
    this.setData({
      changeReason: e.detail.value
    });
  },

  async onConfirmChangeRequest() {
    const { task, changeReason } = this.data;
    const assignmentId = task?.assignment?.id;
    if (!assignmentId) {
      Toast({ context: this, selector: '#t-toast', message: '未找到任务分配记录' });
      return;
    }
    const reason = (changeReason || '').trim();
    if (!reason) {
      Toast({ context: this, selector: '#t-toast', message: '请填写调班原因' });
      return;
    }

    try {
      wx.showLoading({ title: '提交中...' });
      await createChangeRequest(assignmentId, reason);
      wx.hideLoading();
      this.setData({ showChangeDialog: false });
      Toast({ context: this, selector: '#t-toast', message: '申请已提交，等待管理员处理', theme: 'success' });
      // 重新拉取任务详情刷新状态
      this.fetchDetail(this.data.taskId);
    } catch (err) {
      wx.hideLoading();
      Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '提交失败' });
    }
  }
});
