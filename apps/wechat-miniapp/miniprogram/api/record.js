import { request } from '../utils/request.js';

export function getRecordList(params) {
  return request({ url: '/api/v1/me/attendance', method: 'GET', data: params });
}

export function getRecord(recordId) {
  return request({ url: `/api/v1/attendance/${recordId}`, method: 'GET' });
}

export function getObjections(params) {
  return request({ url: '/api/v1/objections', method: 'GET', data: params });
}

export function submitAppeal(recordId, data) {
  return request({ url: `/api/v1/attendance/${recordId}/objections`, method: 'POST', data });
}
