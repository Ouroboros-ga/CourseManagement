import { request } from '../utils/request.js';

export function getApprovalList(params) {
  return request({ url: '/api/v1/objections', method: 'GET', data: params });
}

export function initialReview(objectionId, data) {
  return request({ url: `/api/v1/objections/${objectionId}/initial-review`, method: 'POST', data });
}

export function finalReview(objectionId, data) {
  return request({ url: `/api/v1/objections/${objectionId}/final-review`, method: 'POST', data });
}
