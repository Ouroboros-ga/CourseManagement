import { request } from '../utils/request.js';
import { clearSession, setSession } from '../utils/session.js';

export async function login(data) {
  const result = await request({ url: '/api/v1/auth/wechat/login', method: 'POST', data, auth: false });
  setSession(result);
  return result;
}

export function bindStudent(data) {
  return request({ url: '/api/v1/me/student-binding', method: 'POST', data });
}

export function getUserInfo() {
  return request({ url: '/api/v1/me' });
}

export async function logout() {
  try {
    return await request({ url: '/api/v1/auth/logout', method: 'POST' });
  } finally {
    clearSession();
  }
}
