import { request } from '../utils/request.js';

export const getTaskList = (params = { page_size: 100, include_canceled: false }) => {
  return request({
    url: '/api/v1/me/inspection-tasks',
    method: 'GET',
    data: params
  });
};

export const getTaskDetail = (taskId) => {
  return request({
    url: `/api/v1/inspection-tasks/${taskId}`,
    method: 'GET'
  });
};

export const submitTaskResult = (taskId, data) => {
  return request({
    url: `/api/v1/inspection-tasks/${taskId}/submissions`,
    method: 'POST',
    data
  });
};

export const searchStudents = (taskId, keyword) => {
  return request({
    url: `/api/v1/inspection-tasks/${taskId}/students`,
    method: 'GET',
    data: { keyword }
  });
};

export const getMySubmissions = (taskId) => {
  return request({
    url: '/api/v1/me/submissions',
    method: 'GET',
    data: { task_id: taskId }
  });
};

export const createChangeRequest = (assignmentId, reason) => {
  return request({
    url: '/api/v1/assignment-change-requests',
    method: 'POST',
    data: {
      assignment_id: String(assignmentId),
      reason: reason || ''
    }
  });
};

export const getMyChangeRequests = (params = { page_size: 50 }) => {
  return request({
    url: '/api/v1/me/assignment-change-requests',
    method: 'GET',
    data: params
  });
};

// 保留本地调用名，并兼容新上游页面的调用名。
export const requestChangeAssignment = createChangeRequest;
export const getMyAssignmentChangeRequests = getMyChangeRequests;
