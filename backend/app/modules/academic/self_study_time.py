"""自习以时刻建模；内部时段索引只在独立方案中使用，不改变学校第1节。"""

from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.modules.academic.time_models import CollegeTimeProfile, CollegeTimeVersion
from app.modules.academic.time_service import CollegeTimeService


def clock_profile(service, semester, body):
    if body.start_time is None:
        return None
    label = f"自习时段 {body.start_time:%H:%M}—{body.end_time:%H:%M}"
    row = service.db.scalar(
        select(CollegeTimeProfile)
        .where(
            CollegeTimeProfile.college_id == service.college_id,
            CollegeTimeProfile.semester_id == semester.id,
            CollegeTimeProfile.normalized_name == label,
        )
        .with_for_update()
    )
    configuration = {
        "effective_from": semester.start_date.isoformat(),
        "time_basis": "CLOCK",
        "periods": [
            {
                "slot_id": "self-study-clock",
                "name": "自习时段",
                "period_no": 1,
                "start_time": body.start_time.isoformat(),
                "end_time": body.end_time.isoformat(),
            }
        ],
    }
    if row is not None:
        versions = list(
            service.db.scalars(
                select(CollegeTimeVersion).where(CollegeTimeVersion.profile_id == row.id)
            )
        )
        # 重复生成只能复用完全相同的不可变时段；手工改过的方案不能悄悄复用。
        if (
            row.status != "ACTIVE"
            or not versions
            or any(
                v.configuration.get("time_basis") != "CLOCK"
                or v.configuration["periods"][0]["start_time"] != body.start_time.isoformat()
                or v.configuration["periods"][0]["end_time"] != body.end_time.isoformat()
                for v in versions
            )
        ):
            raise ConflictError(message="同名自习时段已调整或停用，请先核对作息方案")
        return row
    row = CollegeTimeProfile(
        college_id=service.college_id,
        semester_id=semester.id,
        name=label,
        normalized_name=label,
        draft_configuration=configuration,
    )
    service.db.add(row)
    service.db.flush()
    times = CollegeTimeService(
        service.db, service.actor, service.college_id, semester.id, profile_id=row.id
    )
    times.publish(configuration, times.preview(configuration)["revision"], commit=False)
    return row
