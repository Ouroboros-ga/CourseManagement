"""名单快照的教学班归属来源（审查 F1：合班任务逐学生判定授课归属）。

考勤记录只带 (task_id, student_id)，行政班快照也回答不了“这个学生属于本任务里的哪个
教学班”。把归属在名单生成时冻结进 ``task_roster_member_class``，读取与写入都按同一份
事实判断，不再回头用当前选课名单猜历史——学生转班后，原属 B 班的记录不会被 A 班教师读到
或改写。

名单改版（管理员重建名单、学籍异动同步未来正式名单）时按任务课次日重新解析：解析不到
归属的学生不写来源行，本人写入口对其关闭并保持可见提示，不猜测。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.academic.roster_index import RosterIndex
from app.modules.inspection.models import TaskRosterMemberClass, TaskScheduleSource


def source_class_ids(session: Session, task_id: int, primary_class_id: int | None) -> list[int]:
    """任务引用的全部教学班：主教学班加每条来源课表的教学班。"""
    ids = {primary_class_id} if primary_class_id else set()
    ids.update(
        session.scalars(
            select(TaskScheduleSource.teaching_class_id).where(
                TaskScheduleSource.task_id == task_id
            )
        )
    )
    return sorted({i for i in ids if i})


def map_students_to_classes(
    session: Session, teaching_class_ids: list[int], student_ids: list[int], on_date: date
) -> dict[int, list[int]]:
    """按课次日的课班参与关系，还原学生属于哪些教学班（与名单生成同一规则）。"""
    ids = [i for i in dict.fromkeys(teaching_class_ids) if i]
    students = [s for s in dict.fromkeys(student_ids) if s]
    if not ids or not students:
        return {}
    index = RosterIndex(session, ids, student_ids=set(students))
    by_class = index.at(on_date)
    collected: dict[int, set[int]] = defaultdict(set)
    for class_id, members in by_class.items():
        for student in members:
            collected[student.id].add(class_id)
    return {sid: sorted(classes) for sid, classes in collected.items() if classes}


def provenance_rows(
    session: Session,
    *,
    task_id: int,
    roster_version: int,
    primary_class_id: int | None,
    student_ids: list[int],
    inspection_date: date,
) -> list[TaskRosterMemberClass]:
    """为新名单版本生成来源行；解析不到归属的学生留空，由读取端按待核对处理。"""
    mapping = map_students_to_classes(
        session,
        source_class_ids(session, task_id, primary_class_id),
        student_ids,
        inspection_date,
    )
    return [
        TaskRosterMemberClass(
            task_id=task_id,
            roster_version=roster_version,
            student_id=sid,
            teaching_class_id=cid,
        )
        for sid, class_ids in sorted(mapping.items())
        for cid in class_ids
    ]


__all__ = ["map_students_to_classes", "provenance_rows", "source_class_ids"]
