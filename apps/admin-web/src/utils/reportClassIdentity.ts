import type { AbnormalDetailItem, ClassStatsItem, TaskStatsItem } from '../api/reports'

export function detailBelongsToClass(row: ClassStatsItem, detail: AbnormalDetailItem): boolean {
  if (row.class_id) return detail.administrative_class_id_snapshot === row.class_id
  return !detail.administrative_class_id_snapshot && detail.class_name_snapshot === row.class_name
    && (detail.college_id_snapshot || null) === (row.college_id || null)
}

export function taskBelongsToClass(row: ClassStatsItem, task: TaskStatsItem): boolean {
  return !!row.class_id && !!task.administrative_class_ids?.includes(row.class_id)
}
