import { request } from './http'
import type { TeacherAccountItem } from './accounts'

export interface AdministratorAccount extends TeacherAccountItem { can_manage_administrators: boolean }
export interface AdministratorCreate { username: string; display_name: string; initial_password: string; can_manage_administrators: boolean }
export function listAdministrators(page = 1) {
  return request<{ items: AdministratorAccount[]; total: number }>(`/api/v1/administrator-accounts?page=${page}&page_size=20`)
}
export function createAdministrator(body: AdministratorCreate) {
  return request<AdministratorAccount>('/api/v1/administrator-accounts', { method: 'POST', body: JSON.stringify(body) })
}
export function updateAdministrator(id: string, body: { lock_version: number; status?: 'ACTIVE' | 'DISABLED'; can_manage_administrators?: boolean }) {
  return request<AdministratorAccount>(`/api/v1/administrator-accounts/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}
export function resetAdministratorPassword(id: string, newPassword: string, version: number) {
  return request<void>(`/api/v1/administrator-accounts/${id}/password-reset`, { method: 'POST', body: JSON.stringify({ new_password: newPassword, lock_version: version }) })
}
