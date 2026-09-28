import { request } from '../utils/request.js';

export const getTaskList = (params) => request({
  url: '/api/v1/me/inspection-tasks',
  method: 'GET',
  data: params
});

export const getTaskDetail = (taskId) => request({
  url: `/api/v1/inspection-tasks/${taskId}`,
  method: 'GET'
});

export const submitTaskResult = (taskId, data) => request({
  url: `/api/v1/inspection-tasks/${taskId}/submissions`,
  method: 'POST',
  data
});

export const getTaskRoster = (taskId) => request({
  url: `/api/v1/inspection-tasks/${taskId}/students`,
  method: 'GET'
});
