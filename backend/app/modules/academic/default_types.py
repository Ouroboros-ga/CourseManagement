"""Three initial data rows, not a closed course-type enumeration."""

from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.modules.academic.campus_models import CourseType

INITIAL_TYPES = (("regular", "普通课"), ("morning_study", "早自习"), ("evening_study", "晚自习"))


def ensure_initial_types(db, cid):
    for key, name in INITIAL_TYPES:
        row = db.scalar(
            select(CourseType).where(CourseType.college_id == cid, CourseType.builtin_key == key)
        )
        if row is not None:
            continue
        row = db.scalar(
            select(CourseType).where(
                CourseType.college_id == cid, CourseType.normalized_name == name
            )
        )
        if row is None:
            db.add(
                CourseType(
                    college_id=cid,
                    code=f"builtin_{key}",
                    builtin_key=key,
                    name=name,
                    normalized_name=name,
                )
            )
        else:
            row.builtin_key = key
    db.flush()


def regular_type(db, cid):
    row = db.scalar(
        select(CourseType)
        .where(CourseType.college_id == cid, CourseType.builtin_key == "regular")
        .with_for_update(read=True)
    )
    if row is None or row.status != "ACTIVE":
        raise ConflictError(message="本学院默认普通课类型不存在或已停用，请先恢复配置")
    return row
