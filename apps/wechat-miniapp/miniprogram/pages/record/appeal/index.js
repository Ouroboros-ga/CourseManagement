import { getObjections, getRecord, submitAppeal } from '../../../api/record';
import { uploadObjectionProof } from '../../../api/file';
import Toast from 'tdesign-miniprogram/toast/index';

const typeNames = { NORMAL: '正常', LEAVE: '请假', LATE: '迟到', ABSENT: '旷课' };

Page({
  data: {
    recordId: '', currentType: '', currentTypeName: '', desiredType: '',
    latestStatusName: '', latestReason: '',
    reason: '', fileList: [], uploading: false, submitting: false, blocked: false,
  },

  async onLoad(options) {
    if (!options.id) return;
    this.setData({ recordId: options.id });
    try {
      const record = await getRecord(options.id);
      const history = await getObjections({ attendance_record_id: options.id, page: 1, page_size: 1 });
      const latest = (history.items || [])[0];
      const latestStatusName = !latest ? '' : latest.final_status === 'APPROVED' ? '已通过'
        : latest.final_status === 'REJECTED' ? '已驳回'
        : latest.initial_status === 'PENDING' ? '待初核' : '待终审';
      this.setData({
        currentType: record.effective_type,
        currentTypeName: typeNames[record.effective_type] || record.effective_type,
        latestStatusName,
        latestReason: latest?.reason || '',
        blocked: latest?.final_status === 'PENDING',
      });
    } catch (error) {
      this.setData({ blocked: true });
      Toast({ context: this, selector: '#t-toast', message: error.message || '考勤记录不可读取' });
    }
  },

  onDesiredTypeChange(e) {
    this.setData({ desiredType: e.detail.value });
  },

  onReasonChange(e) {
    this.setData({ reason: e.detail.value });
  },

  async onAddPhoto(e) {
    if (this.data.uploading) return;
    const files = e.detail.files || [];
    if (this.data.fileList.length + files.length > 3) {
      Toast({ context: this, selector: '#t-toast', message: '证明材料最多 3 张' });
      return;
    }
    this.setData({ uploading: true });
    try {
      for (const file of files) {
        const path = file.url || file.tempFilePath;
        const uploaded = await uploadObjectionProof(path);
        this.setData({ fileList: this.data.fileList.concat({ id: uploaded.id, url: path, name: file.name || '证明', type: 'image' }) });
      }
    } catch (error) {
      Toast({ context: this, selector: '#t-toast', message: error.message || '材料上传失败' });
    } finally {
      this.setData({ uploading: false });
    }
  },

  onRemovePhoto(e) {
    const list = [...this.data.fileList];
    list.splice(e.detail.index, 1);
    this.setData({ fileList: list });
  },

  async handleSubmit() {
    const { recordId, currentType, desiredType, reason, fileList, blocked, uploading, submitting } = this.data;
    if (blocked || uploading || submitting) return;
    if (!recordId || !currentType || !desiredType || desiredType === currentType) {
      Toast({ context: this, selector: '#t-toast', message: '请选择不同的期望认定' });
      return;
    }
    this.setData({ submitting: true });
    try {
      wx.showLoading({ title: '提交中' });
      await submitAppeal(recordId, {
        desired_type: desiredType, reason: reason.trim(), file_ids: fileList.map(file => file.id),
      });
      this.setData({ blocked: true });
      Toast({ context: this, selector: '#t-toast', message: '提交成功', theme: 'success' });
      setTimeout(() => wx.navigateBack(), 1500);
    } catch (error) {
      Toast({ context: this, selector: '#t-toast', message: error.message || '提交失败' });
    } finally {
      wx.hideLoading();
      this.setData({ submitting: false });
    }
  },
});
