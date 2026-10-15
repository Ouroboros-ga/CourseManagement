"""正式任务时间在生成时冻结；历史缺时间不借当前作息补造。"""

from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.academic.time_service import TimeResolver
from app.modules.inspection.models import InspectionTask, TaskScheduleSource


def freeze_time(db: Session, task: InspectionTask):
    resolver = TimeResolver(db)
    resolver.prefetch(task.college_id, task.semester_id)
    interval = resolver.interval(task.college_id, task.semester_id, task.inspection_date,
        task.start_period, task.end_period, teaching_class_id=task.teaching_class_id)
    for teaching_id in db.scalars(select(TaskScheduleSource.teaching_class_id).where(TaskScheduleSource.task_id == task.id).distinct()):
        other = resolver.interval(task.college_id, task.semester_id, task.inspection_date,
            task.start_period, task.end_period, teaching_class_id=teaching_id)
        if (other["start_minute"], other["end_minute"]) != (interval["start_minute"], interval["end_minute"]):
            raise ConflictError(message="原合班教学班已采用不同作息，请先处置合班任务后再调整时间")
    offset = get_settings().app_utc_offset_hours
    midnight = datetime.combine(task.inspection_date, time.min)
    task.activity_start_at = midnight + timedelta(minutes=interval["start_minute"], hours=-offset)
    task.activity_end_at = midnight + timedelta(minutes=interval["end_minute"], hours=-offset)
    task.time_snapshot = {
        **interval,
        "utc_offset_hours": offset,
        "date": task.inspection_date.isoformat(),
    }


def task_minutes(task: InspectionTask) -> tuple[int, int]:
    if not task.time_snapshot or task.activity_start_at is None or task.activity_end_at is None:
        raise ConflictError(message="任务历史实际时间未确认，不能以当前作息推断")
    offset = task.time_snapshot["utc_offset_hours"]
    start, end = (
        task.activity_start_at + timedelta(hours=offset),
        task.activity_end_at + timedelta(hours=offset),
    )
    if start.date() != task.inspection_date or end.date() != task.inspection_date or start >= end:
        raise ConflictError(message="任务时间快照与执行日期不一致")
    return start.hour * 60 + start.minute, end.hour * 60 + end.minute


def overlaps(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return first[0] < second[1] and second[0] < first[1]
