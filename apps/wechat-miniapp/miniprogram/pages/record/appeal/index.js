import { submitAppeal } from '../../../api/record';
import { uploadFile } from '../../../utils/upload';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    recordId: '',
    reason: '',
    fileList: []
  },

  onLoad(options) {
    if (options.id) {
      this.setData({ recordId: options.id });
    }
  },

  onReasonChange(e) {
    this.setData({ reason: e.detail.value });
  },

  async onAddPhoto(e) {
    const { files } = e.detail;
    wx.showLoading({ title: '上传中...' });
    
    try {
      const uploadPromises = files.map(file => uploadFile(file.url, 'OBJECTION_PROOF'));
      const uploadResults = await Promise.all(uploadPromises);
      
      const newFiles = files.map((file, index) => ({
        url: file.url,
        name: 'photo',
        type: 'image',
        file_id: uploadResults[index].id
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
    const { recordId, reason, fileList } = this.data;
    if (!reason.trim()) {
      Toast({ context: this, selector: '#t-toast', message: '请填写异议理由' });
      return;
    }

    try {
      wx.showLoading({ title: '提交中' });
      const fileIds = fileList.map(f => f.file_id).filter(id => id != null).map(Number);
      await submitAppeal(recordId, { reason, file_ids: fileIds });
      
      wx.hideLoading();
      Toast({ context: this, selector: '#t-toast', message: '提交成功', theme: 'success' });
      setTimeout(() => {
        wx.navigateBack();
      }, 1500);
    } catch (err) {
      wx.hideLoading();
      Toast({ context: this, selector: '#t-toast', message: err.msg || err.message || '提交失败' });
    }
  }
});
