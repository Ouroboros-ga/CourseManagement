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
