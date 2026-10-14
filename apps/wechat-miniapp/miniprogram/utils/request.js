import { getBaseURL } from './env.js';

let refreshPromise = null;

/**
 * 清除会话并强制跳转登录
 */
function handleAuthFailure(errMsg = '请重新登录') {
  wx.removeStorageSync('token');
  wx.removeStorageSync('refresh_token');
  wx.showToast({
    title: errMsg,
    icon: 'none'
  });
  wx.reLaunch({
    url: '/pages/login/index'
  });
}

/**
 * 刷新 Token 会话（单例 Promise，支持并发重入）
 */
function refreshSession() {
  if (refreshPromise) return refreshPromise;

  const refreshToken = wx.getStorageSync('refresh_token');
  if (!refreshToken) {
    return Promise.reject(new Error('未找到刷新凭证'));
  }

  const baseURL = getBaseURL();
  refreshPromise = new Promise((resolve, reject) => {
    wx.request({
      url: `${baseURL}/api/v1/auth/refresh`,
      method: 'POST',
      data: { refresh_token: refreshToken },
      header: { 'Content-Type': 'application/json' },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const payload = res.data?.data !== undefined ? res.data.data : res.data;
          const newAccessToken = payload?.access_token || payload?.token;
          const newRefreshToken = payload?.refresh_token;

          if (newAccessToken) {
            wx.setStorageSync('token', newAccessToken);
          }
          if (newRefreshToken) {
            wx.setStorageSync('refresh_token', newRefreshToken);
          }
          resolve(newAccessToken);
        } else {
          reject(new Error('刷新凭证失效'));
        }
      },
      fail: (err) => {
        reject(err);
      }
    });
  }).finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
}

/**
 * 封装微信的 wx.request，内置 401 静默刷新与单次自动重试
 * @param {Object} options 请求配置
 * @param {boolean} isRetry 是否为 401 刷新后的重试请求
 * @returns {Promise}
 */
export const request = (options, isRetry = false) => {
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

    const requestUrl = options.url.startsWith('http') ? options.url : `${baseURL}${options.url}`;

    wx.request({
      url: requestUrl,
      method: options.method || 'GET',
      data: options.data,
      header: header,
      success: async (res) => {
        // HTTP 状态码 2xx
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data && res.data.data !== undefined ? res.data.data : res.data);
          return;
        }

        // 401 未授权处理
        if (res.statusCode === 401) {
          // 如果当前请求本身就是刷新接口或登录接口，或者已经是重试请求，直接注销
          const isAuthUrl = options.url.includes('/auth/refresh') || options.url.includes('/auth/wechat/login');
          if (isRetry || isAuthUrl) {
            handleAuthFailure('登录已失效，请重新登录');
            reject(new Error('Unauthorized'));
            return;
          }

          // 尝试静默刷新 Token
          try {
            await refreshSession();
            // 刷新成功，使用新 Token 自动重试当前请求
            const retryResult = await request(options, true);
            resolve(retryResult);
          } catch (refreshErr) {
            handleAuthFailure('登录已失效，请重新登录');
            reject(new Error('Unauthorized'));
          }
          return;
        }

        // 其他错误处理
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
