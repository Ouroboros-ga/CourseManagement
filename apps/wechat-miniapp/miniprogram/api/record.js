import { request } from '../utils/request.js';

export const getRecordList = () => {
  return request({
    url: '/api/v1/me/attendance',
    method: 'GET'
  });
};

export const submitAppeal = (recordId, data) => {
  const payload = {
    desired_type: 'NORMAL',
    reason: data.reason,
    file_ids: data.file_ids || []
  };

  return request({
    url: `/api/v1/attendance/${recordId}/objections`,
    method: 'POST',
    data: payload
  });
};

export const getMyObjections = () => {
  return request({
    url: '/api/v1/objections',
    method: 'GET'
  });
};

export const getCampusRuntime = () => request({
  url: '/api/v1/me/campus-runtime',
  method: 'GET'
});

export const getObjectionProgress = (objectionId) => {
  if (typeof objectionId !== 'string' || !/^[1-9][0-9]{0,18}$/.test(objectionId)
    || (objectionId.length === 19 && objectionId > '9223372036854775807')) {
    return Promise.reject(new Error('申诉编号无效，请刷新记录'));
  }
  return request({
    url: `/api/v1/me/objections/${objectionId}/progress`,
    method: 'GET'
  });
};
