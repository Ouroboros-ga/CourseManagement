import { request } from './http'

export interface CollegePeriodTime {
  slot_id?: string | null
  name?: string
  period_no: number
  start_time: string
  end_time: string
}

export interface CollegeCalendarOverride {
  date: string
  override_type: 'STOP' | 'MAKEUP'
  source_teaching_week?: number | null
  source_teaching_weekday?: number | null
}

export interface CollegeTimeConfiguration {
  effective_from: string
  periods: CollegePeriodTime[]
  calendar: CollegeCalendarOverride[]
  grid_slot_mapping?: Record<string, number>
  confirm_existing_tasks: boolean
}

export interface CollegeTimeVersion {
  id: string
  version: number
  effective_from: string
  configuration: Omit<CollegeTimeConfiguration, 'confirm_existing_tasks'>
}

export interface CollegeTimePreview {
  revision: string
  next_version: number
  retained_future_task_ids: string[]
  existing_tasks_keep_snapshot: true
}

export interface CollegeTimePublished extends CollegeTimePreview {
  id: string
  version: number
}

const root = (collegeId: string, semesterId: string) =>
  `/api/v1/colleges/${encodeURIComponent(collegeId)}/academic/semesters/${encodeURIComponent(semesterId)}/time-versions`

export function listCollegeTimeVersions(collegeId: string, semesterId: string) {
  return request<CollegeTimeVersion[]>(root(collegeId, semesterId))
}

export function previewCollegeTime(collegeId: string, semesterId: string, configuration: CollegeTimeConfiguration) {
  return request<CollegeTimePreview>(`${root(collegeId, semesterId)}/preview`, {
    method: 'POST', body: JSON.stringify(configuration)
  })
}

export function publishCollegeTime(collegeId: string, semesterId: string, configuration: CollegeTimeConfiguration, revision: string) {
  return request<CollegeTimePublished>(`${root(collegeId, semesterId)}/publish`, {
    method: 'POST', body: JSON.stringify({ ...configuration, revision })
  })
}
