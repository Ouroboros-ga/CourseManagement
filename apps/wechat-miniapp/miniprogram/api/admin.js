import { request } from '../utils/request.js';

export const getApprovalList = (params = { final_status: 'PENDING' }) => {
  const queryStr = Object.keys(params).map(k => `${k}=${params[k]}`).join('&');
  return request({
    url: `/api/v1/objections?${queryStr}`,
    method: 'GET'
  });
};

// 异议已改为一次审核：POST /objections/{id}/review（objection.final_review）。
// 旧的 /initial-review 入口在后端只返回 409 提示迁移，小程序不再调用。
export const reviewObjection = (appealId, { decision, finalType, comment, version }) => {
  return request({
    url: `/api/v1/objections/${appealId}/review`,
    method: 'POST',
    data: {
      decision,
      ...(finalType ? { final_type: finalType } : {}),
      ...(comment ? { comment } : {}),
      current_version: version
    }
  });
};

export const approveAppeal = (appealId, version, finalType = 'NORMAL') =>
  reviewObjection(appealId, { decision: 'APPROVED', finalType, version });

export const rejectAppeal = (appealId, version, comment = '') =>
  reviewObjection(appealId, { decision: 'REJECTED', comment, version });
