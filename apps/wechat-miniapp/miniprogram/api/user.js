import { request } from '../utils/request.js';

export const webLogin = (data) => {
  return request({
    url: '/api/v1/auth/web/login',
    method: 'POST',
    data
  });
};

export const login = (data) => {
  return request({
    url: '/api/v1/auth/wechat/login',
    method: 'POST',
    data
  });
};

export const bindStudent = (data) => {
  const payload = {
    student_no: data.student_no || data.studentId,
    binding_code: data.binding_code || data.name || data.bindingCode,
  };

  return request({
    url: '/api/v1/me/student-binding',
    method: 'POST',
    data: payload
  });
};

export const unbindStudent = () => {
  return request({
    url: '/api/v1/me/student-binding',
    method: 'DELETE'
  });
};

export const getUserInfo = () => {
  return request({
    url: '/api/v1/me',
    method: 'GET'
  });
};

export const logout = () => {
  return request({
    url: '/api/v1/auth/logout',
    method: 'POST'
  });
};
