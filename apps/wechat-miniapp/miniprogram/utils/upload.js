import { getBaseURL } from './env.js';

export const uploadFile = (filePath, category = 'SUBMISSION_PHOTO') => {
  return new Promise((resolve, reject) => {
    const baseURL = getBaseURL();
    const token = wx.getStorageSync('token');
    
    wx.uploadFile({
      url: `${baseURL}/api/v1/files`,
      filePath: filePath,
      name: 'file',
      formData: {
        category: category
      },
      header: {
        'Authorization': `Bearer ${token}`
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const data = JSON.parse(res.data);
          // 适配 { data: { id: ... } } 的返回格式
          resolve(data.data ? data.data : data);
        } else {
          reject(new Error(`Upload failed with status code ${res.statusCode}`));
        }
      },
      fail: (err) => {
        reject(err);
      }
    });
  });
};
