import { getBaseURL } from './env.js';
import { clearSession, getAccessToken, getRefreshToken, setSession } from './session.js';

let refreshPromise = null;

function backendError(response) {
  const body = response.data || {};
  const error = new Error(body.message || `请求失败 (${response.statusCode})`);
  error.code = body.code || 'HTTP_ERROR';
  error.status = response.statusCode;
  error.fieldErrors = body.fieldErrors;
  return error;
}

function send(options, token) {
  if (!options.url.startsWith('/api/v1/')) {
    return Promise.reject(new Error('只允许请求本系统的 /api/v1 接口'));
  }
  const header = { 'Content-Type': 'application/json', ...options.header };
  if (token) header.Authorization = `Bearer ${token}`;
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getBaseURL()}${options.url}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      success: (response) => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.statusCode === 204 ? null : response.data?.data ?? null);
        } else reject(backendError(response));
      },
      fail: reject,
    });
  });
}

export function refreshSession() {
  if (refreshPromise) return refreshPromise;
  const refreshToken = getRefreshToken();
  if (!refreshToken) return Promise.reject(new Error('登录已失效'));
  refreshPromise = send({
    url: '/api/v1/auth/refresh', method: 'POST', data: { refresh_token: refreshToken },
  }, '').then((tokens) => {
    setSession(tokens);
    return tokens.access_token;
  }).catch((error) => {
    clearSession();
    throw error;
  }).finally(() => { refreshPromise = null; });
  return refreshPromise;
}

export async function request(options) {
  const token = options.auth === false ? '' : getAccessToken();
  try {
    return await send(options, token);
  } catch (error) {
    if (options.auth === false || error.status !== 401) throw error;
    try {
      // 已由并发请求完成轮换时直接使用新 access，避免旧 refresh 重放。
      const nextToken = token !== getAccessToken() && getAccessToken()
        ? getAccessToken() : await refreshSession();
      return await send(options, nextToken);
    } catch (retryError) {
      if (retryError.status === 401) clearSession();
      throw retryError;
    }
  }
}
