import { getBaseURL } from './env.js';

/**
 * 封装微信的 wx.request
 * @param {Object} options 请求配置
 * @returns {Promise}
 */
export const request = (options) => {
  return new Promise((resolve, reject) => {
    const baseURL = getBaseURL();
    const token = wx.getStorageSync('token');
    const header = {
      'Content-Type': 'application/json',
      ...options.header
    };

    if (token) {
      header['Authorization'] = `Bearer ${token}`;
    }

    wx.request({
      url: options.url.startsWith('http') ? options.url : `${baseURL}${options.url}`,
      method: options.method || 'GET',
      data: options.data,
      header: header,
      success: (res) => {
        // HTTP 状态码 2xx
        if (res.statusCode >= 200 && res.statusCode < 300) {
          // 真实后端返回 HTTP 200 即为成功，数据包在 res.data.data
          resolve(res.data && res.data.data !== undefined ? res.data.data : res.data);
        } else if (res.statusCode === 401) {
          // Token 失效或未登录
          wx.removeStorageSync('token');
          wx.showToast({
            title: '请重新登录',
            icon: 'none'
          });
          wx.reLaunch({
            url: '/pages/login/index'
          });
          reject(new Error('Unauthorized'));
        } else {
          let errorData = res.data;
          if (errorData && typeof errorData === 'object') {
            if (Array.isArray(errorData.detail)) {
              // 处理 FastAPI 原生的 422 校验错误数组
              errorData.message = errorData.detail.map(d => d.msg).join('; ');
            } else if (typeof errorData.detail === 'string') {
              // 处理 FastAPI 原生的 HTTPException 字符串错误
              errorData.message = errorData.detail;
            }
          }
          reject(errorData || new Error(`Server error: ${res.statusCode}`));
        }
      },
      fail: (err) => {
        wx.showToast({
          title: '网络异常，请重试',
          icon: 'none'
        });
        reject(err);
      }
    });
  });
};
