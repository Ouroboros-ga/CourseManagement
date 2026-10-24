"""组织总览只读摘要；不读取全体成员档案，不逐组加载学期准备资料。"""

from datetime import date

from sqlalchemy import func, or_, select, tuple_

from app.core.exceptions import NotFoundError
from app.modules.academic.models import Semester
from app.modules.organization.service import CampusService
from app.modules.volunteer.member_models import VolunteerGroupMember
from app.modules.volunteer.models import GroupConfigVersion
from app.modules.volunteer.preparation_models import GroupSemesterPreparation


def semester_overview(db, actor, college_id: int, semester_id: int, as_of: date):
    # 复用组读取授权、组范围上限及已删除资源过滤。
    groups = CampusService(db).list_groups(actor, college_id)
    if db.get(Semester, semester_id) is None:
        raise NotFoundError("学期不存在")
    ids = {int(group["id"]) for group in groups}
    if not ids:
        return {"items": {}}
    prepared = {
        row.group_id: row
        for row in db.scalars(
            select(GroupSemesterPreparation).where(
                GroupSemesterPreparation.college_id == college_id,
                GroupSemesterPreparation.group_id.in_(ids),
                GroupSemesterPreparation.semester_id == semester_id,
            )
        )
    }
    configs = list(
        db.scalars(
            select(GroupConfigVersion).where(
                GroupConfigVersion.college_id == college_id,
                GroupConfigVersion.group_id.in_(ids),
                or_(
                    GroupConfigVersion.id.in_({row.config_id for row in prepared.values()}),
                    tuple_(GroupConfigVersion.group_id, GroupConfigVersion.version).in_(
                        {(int(group["id"]), group["config_version"]) for group in groups}
                    ),
                ),
            )
        )
    )
    by_id = {row.id: row for row in configs}
    by_version = {(row.group_id, row.version): row for row in configs}
    from app.modules.volunteer.college_membership import local_student_ids

    counts = dict(
        db.execute(
            select(
                VolunteerGroupMember.group_id,
                func.count(func.distinct(VolunteerGroupMember.student_id)),
            )
            .where(
                VolunteerGroupMember.college_id == college_id,
                VolunteerGroupMember.group_id.in_(ids),
                VolunteerGroupMember.student_id.in_(local_student_ids(college_id, as_of)),
                VolunteerGroupMember.semester_id == semester_id,
                VolunteerGroupMember.status == "ACTIVE",
                VolunteerGroupMember.effective_from <= as_of,
                VolunteerGroupMember.effective_to > as_of,
            )
            .group_by(VolunteerGroupMember.group_id)
        ).all()
    )
    result = {}
    for group in groups:
        gid = int(group["id"])
        preparation = prepared.get(gid)
        config = (
            by_id.get(preparation.config_id)
            if preparation
            else by_version.get((gid, group["config_version"]))
        )
        valid = config is not None and config.group_id == gid
        result[str(gid)] = {
            "configuration": config.configuration if valid else None,
            "member_count": counts.get(gid, 0),
            "specific": preparation is not None,
            "error": "本学期规则不可读取，请核对配置"
            if not valid and (preparation or group["config_version"])
            else "",
        }
    return {"items": result}
