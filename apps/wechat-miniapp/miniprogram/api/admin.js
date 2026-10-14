import { request } from '../utils/request.js';

export const getApprovalList = (params = { final_status: 'PENDING' }) => {
  const queryStr = Object.keys(params).map(k => `${k}=${params[k]}`).join('&');
  return request({
    url: `/api/v1/objections?${queryStr}`,
    method: 'GET'
  });
};

export const initialReviewObjection = (appealId, decision, comment = '') => {
  return request({
    url: `/api/v1/objections/${appealId}/initial-review`,
    method: 'POST',
    data: {
      decision,
      ...(comment ? { comment } : {})
    }
  });
};

export const approveAppeal = (appealId, version) => {
  return request({
    url: `/api/v1/objections/${appealId}/final-review`,
    method: 'POST',
    data: {
      decision: 'APPROVED',
      final_type: 'NORMAL',
      current_version: version
    }
  });
};

export const rejectAppeal = (appealId, version, comment = '') => {
  return request({
    url: `/api/v1/objections/${appealId}/final-review`,
    method: 'POST',
    data: {
      decision: 'REJECTED',
      current_version: version,
      ...(comment ? { comment } : {})
    }
  });
};
