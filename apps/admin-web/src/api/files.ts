import { request } from './http'

export interface FileAccessInfo {
  url: string
  method: string
  expires_in: number
  expires_at: string
}

export type UploadCategory = 'SUBMISSION_PHOTO' | 'OBJECTION_PROOF' | 'TEMP'

export interface FileUploadInfo {
  id: string
  category: string
  status: string
  original_name: string | null
  content_type: string
  size_bytes: number
  width: number
  height: number
  sha256: string
  expires_at: string | null
}

export function uploadFile(file: File, category: UploadCategory): Promise<FileUploadInfo> {
  const body = new FormData()
  body.append('file', file)
  body.append('category', category)
  // 浏览器生成 multipart boundary；统一 request 负责认证与单次 401 重试。
  return request<FileUploadInfo>('/api/v1/files', { method: 'POST', body })
}

export function getFileAccess(fileId: string): Promise<FileAccessInfo> {
  return request<FileAccessInfo>(`/api/v1/files/${encodeURIComponent(fileId)}/access`)
}
