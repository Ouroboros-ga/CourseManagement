"""同一教学班同周同日的排课不可重叠；不通过显示去重隐藏源数据错误。"""

from collections import defaultdict

from app.core.exceptions import ConflictError, ErrorCode


def require_no_schedule_overlap(schedules, weeks):
    occupied = defaultdict(list)
    for schedule in schedules:
        for week in set(weeks[schedule.id]):
            key = (schedule.teaching_class_id, schedule.weekday, week)
            for other in occupied[key]:
                if (
                    schedule.start_period <= other.end_period
                    and other.start_period <= schedule.end_period
                ):
                    raise ConflictError(
                        ErrorCode.STATE_CONFLICT,
                        f"排课重叠：教学班 {schedule.teaching_class_id}，"
                        f"第 {week} 周星期 {schedule.weekday}，"
                        f"排课 {other.id} 与 {schedule.id or '待导入'}；"
                        "请核对导入批次并处理旧排课后重试，不会自动覆盖历史任务",
                    )
            occupied[key].append(schedule)
