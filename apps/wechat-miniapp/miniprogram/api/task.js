import { request } from '../utils/request.js';

export const getTaskList = (params) => {
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
