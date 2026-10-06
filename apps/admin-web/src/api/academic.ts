import { request } from './http'

export interface SemesterItem {
  id: string
  code: string
  name: string
  status: 'ACTIVE' | 'ARCHIVED'
  start_date: string
  total_weeks: number
  lock_version: number
  created_at: string
}

export interface TeachingClassItem {
  id: string
  semester_id: string
  course_id: string
  class_code?: string | null
  class_name: string
  status: string
}

export async function listSemesters(status = 'ACTIVE'): Promise<{ items: SemesterItem[]; total: number }> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('page_size', '50')
  return request<{ items: SemesterItem[]; total: number }>(`/api/v1/academic/semesters?${params.toString()}`)
}

export async function listTeachingClasses(semesterId: string): Promise<{ items: TeachingClassItem[]; total: number }> {
  const params = new URLSearchParams()
  params.set('semester_id', semesterId)
  params.set('page_size', '100')
  return request<{ items: TeachingClassItem[]; total: number }>(`/api/v1/academic/teaching-classes?${params.toString()}`)
}
