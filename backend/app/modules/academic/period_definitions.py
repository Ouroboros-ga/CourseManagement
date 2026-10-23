"""学校教学节次的完整性；独立自习时段不写入本表。"""

from datetime import time

from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.modules.academic.models import CourseSchedule, PeriodDefinition

STANDARD_PERIODS = [
    ("08:10", "08:55"),
    ("09:00", "09:45"),
    ("10:05", "10:50"),
    ("10:55", "11:40"),
    ("13:30", "14:15"),
    ("14:20", "15:05"),
    ("15:25", "16:10"),
    ("16:15", "17:00"),
    ("17:05", "17:50"),
    ("18:50", "19:35"),
    ("19:40", "20:25"),
    ("20:30", "21:15"),
]


def snapshot(row):
    return {
        "period_no": row.period_no,
        "semester_id": str(row.semester_id),
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "end_time": row.end_time.isoformat() if row.end_time else None,
    }


def referenced(db, sid, no):
    # 即使教学班有方案，也保守保留学校定义，避免解绑方案后出现悬空引用。
    return (
        db.scalar(
            select(CourseSchedule.id)
            .where(
                CourseSchedule.semester_id == sid,
                CourseSchedule.start_period <= no,
                CourseSchedule.end_period >= no,
            )
            .limit(1)
        )
        is not None
    )


def validate_order(rows):
    rows = sorted(rows, key=lambda p: p.period_no)
    if any(
        p.start_time is None
        or p.end_time is None
        or p.start_time >= p.end_time
        or any(t.tzinfo or t.second or t.microsecond for t in (p.start_time, p.end_time))
        for p in rows
    ):
        raise ConflictError(message="教学节次须有完整、分钟精度的有效起止时刻")
    if any(a.end_time > b.start_time for a, b in zip(rows, rows[1:], strict=False)):
        raise ConflictError(message="教学节次时间须按编号递增且不重叠；早晚自习请使用独立起止时间")


def initialize(service, actor, sid, request_id):
    rows = list(
        service._session.scalars(
            select(PeriodDefinition).where(PeriodDefinition.semester_id == sid)
        )
    )
    existing = {p.period_no for p in rows}
    missing = [
        PeriodDefinition(
            semester_id=sid,
            period_no=i,
            start_time=time.fromisoformat(start),
            end_time=time.fromisoformat(end),
        )
        for i, (start, end) in enumerate(STANDARD_PERIODS, 1)
        if i not in existing
    ]
    validate_order([*rows, *missing])
    for row in missing:
        service._session.add(row)
    service._record_audit(
        actor_user_id=actor.id,
        action="academic.period_definition.initialize",
        resource_type="semester",
        resource_id=str(sid),
        before={"periods": [snapshot(r) for r in rows]},
        after={"created_periods": [r.period_no for r in missing]},
        reason=None,
        request_id=request_id,
    )
    service._session.commit()
    return {"created": len(missing), "preserved": len(rows)}
