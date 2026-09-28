const ACCESS_KEY = 'access_token';
const REFRESH_KEY = 'refresh_token';

export function getAccessToken() {
  return wx.getStorageSync(ACCESS_KEY) || '';
}

export function getRefreshToken() {
  return wx.getStorageSync(REFRESH_KEY) || '';
}

export function hasSession() {
  return Boolean(getAccessToken() || getRefreshToken());
}

export function setSession(tokens) {
  if (!tokens?.access_token || !tokens?.refresh_token) {
    throw new Error('后端未返回完整登录凭证');
  }
  wx.setStorageSync(ACCESS_KEY, tokens.access_token);
  wx.setStorageSync(REFRESH_KEY, tokens.refresh_token);
}

export function clearSession() {
  wx.removeStorageSync(ACCESS_KEY);
  wx.removeStorageSync(REFRESH_KEY);
}
