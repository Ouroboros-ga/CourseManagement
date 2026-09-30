import { getBaseURL } from '../utils/env.js';
import { getAccessToken } from '../utils/session.js';
import { refreshSession, request } from '../utils/request.js';

function upload(path, accessToken, category) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getBaseURL()}/api/v1/files`,
      filePath: path,
      name: 'file',
      formData: { category },
      header: { Authorization: `Bearer ${accessToken}` },
      success: (response) => {
        let body;
        try {
          body = JSON.parse(response.data || '{}');
        } catch {
          reject(new Error('上传响应格式错误'));
          return;
        }
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(body.data);
        } else {
          const error = new Error(body.message || '上传失败');
          error.status = response.statusCode;
          error.code = body.code;
          reject(error);
        }
      },
      fail: reject,
    });
  });
}

async function uploadByCategory(path, category) {
  const token = getAccessToken() || await refreshSession();
  try {
    return await upload(path, token, category);
  } catch (error) {
    if (error.status !== 401) throw error;
    return upload(path, await refreshSession(), category);
  }
}

export function uploadSubmissionPhoto(path) {
  return uploadByCategory(path, 'SUBMISSION_PHOTO');
}

export function uploadObjectionProof(path) {
  return uploadByCategory(path, 'OBJECTION_PROOF');
}

export async function getFileAccess(fileId) {
  const access = await request({ url: `/api/v1/files/${fileId}/access`, method: 'GET' });
  return {
    ...access,
    url: access.url.startsWith('/') ? `${getBaseURL()}${access.url}` : access.url,
  };
}
