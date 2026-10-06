import { request } from '../utils/request.js';

export const getApprovalList = () => {
  return request({ 
    url: '/api/v1/objections?final_status=PENDING', 
    method: 'GET' 
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

export const getSubmissionList = () => {
  return request({
    url: '/api/v1/management/submissions?review_status=PENDING',
    method: 'GET'
  });
};

export const reviewSubmission = (submissionId, decision, comment = '') => {
  return request({
    url: `/api/v1/submissions/${submissionId}/review`,
    method: 'POST',
    data: {
      decision: decision,
      ...(comment ? { comment } : {})
    }
  });
};
