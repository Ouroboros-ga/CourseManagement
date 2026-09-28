import { getTaskDetail, submitTaskResult } from '../../../api/task';
import { uploadSubmissionPhoto } from '../../../api/file';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    taskId: '',
    task: {},
    resultType: 'NORMAL',
    abnormalList: [], // studentId is the internal ID, studentNo is display-only.
    fileList: [],
    uploading: false,
    submitting: false
  },

  onLoad(options) {
    if (options.id) {
      this.setData({ taskId: options.id });
      this.fetchDetail(options.id);
    }
  },

  onShow() {
    const selectedAbnormal = wx.getStorageSync('selectedAbnormal');
    if (selectedAbnormal) {
      wx.removeStorageSync('selectedAbnormal');
      if (selectedAbnormal.taskId === this.data.taskId && Array.isArray(selectedAbnormal.items)) {
        this.setData({ abnormalList: selectedAbnormal.items });
      }
    }
  },

  async fetchDetail(id) {
    try {
      wx.showLoading();
      const task = await getTaskDetail(id);
      if (task && task.inspection_date) {
        const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
        const d = new Date(`${task.inspection_date}T00:00:00`);
        const dayStr = Number.isNaN(d.getDay()) ? '' : ' 星期' + dayNames[d.getDay()];
        const periods = task.start_period === task.end_period
          ? `${task.start_period}` : `${task.start_period}-${task.end_period}`;
        task.timeStr = `第${task.week_no}周${dayStr} 第${periods}节`;
      }
      this.setData({ task: {
        ...task,
        courseName: task.course_name_snapshot || (task.inspection_type === 'MORNING_STUDY' ? '早自习' : '晚自习'),
        className: task.class_name_snapshot || '—',
        classroom: task.classroom_snapshot || '—',
        expectedCount: task.expected_count_current,
        requirePhoto: task.require_photo_snapshot,
        canSubmit: task.status === '待执行' || task.status === '已逾期'
      } });
    } catch (err) {
      wx.showToast({ title: err.message || '任务加载失败', icon: 'none' });
    } finally {
      wx.hideLoading();
    }
  },

  onResultTypeChange(e) {
    this.setData({ resultType: e.detail.value });
    if (e.detail.value === 'NORMAL') {
      this.setData({ abnormalList: [] });
    }
  },

  goToAbnormalPage() {
    wx.setStorageSync('currentAbnormal', {
      taskId: this.data.taskId,
      items: this.data.abnormalList
    });
    wx.navigateTo({
      url: `/pages/task/abnormal/index?taskId=${this.data.taskId}`
    });
  },

  async onAddPhoto(e) {
    const files = e.detail.files || [];
    this.setData({ uploading: true });
    try {
      for (const file of files) {
        const path = file.url || file.tempFilePath;
        const record = await uploadSubmissionPhoto(path);
        this.setData({
          fileList: this.data.fileList.concat({
            id: record.id, url: path, name: file.name || 'photo', type: 'image'
          })
        });
      }
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: err.message || '照片上传失败' });
    } finally {
      this.setData({ uploading: false });
    }
  },

  onRemovePhoto(e) {
    const { index } = e.detail;
    const fileList = [...this.data.fileList];
    fileList.splice(index, 1);
    this.setData({ fileList });
  },

  async handleSubmit() {
    const { resultType, abnormalList, fileList, task, taskId } = this.data;

    if (this.data.submitting || this.data.uploading || !task.canSubmit) {
      Toast({ context: this, selector: '#t-toast', message: '当前任务不可提交或照片仍在上传' });
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
      this.setData({ submitting: true });
      wx.showLoading({ title: '提交中' });
      await submitTaskResult(taskId, {
        result: resultType,
        abnormal_items: resultType === 'NORMAL' ? [] : abnormalList.map(student => ({
          student_id: student.studentId,
          attendance_type: student.type
        })),
        file_ids: fileList.map(file => file.id)
      });

      this.setData({ task: { ...task, status: '待审核', canSubmit: false } });
      Toast({ context: this, selector: '#t-toast', message: '提交成功', theme: 'success' });
      setTimeout(() => {
        wx.navigateBack();
      }, 1500);
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: err.message || '提交失败' });
    } finally {
      wx.hideLoading();
      this.setData({ submitting: false });
    }
  }
});
