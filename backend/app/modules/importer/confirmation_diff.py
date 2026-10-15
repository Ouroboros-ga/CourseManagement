"""新向导的只读差异。无法确定替换对象的课表变更明确阻断，不猜测删除旧课表。"""

import copy
import hashlib

from sqlalchemy import select

from app.common.parsing.grid import normalize_class_name
from app.core.exceptions import AppError
from app.modules.academic.enrollment_models import TeachingClassAudience
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
)


def changes_for(service, batch):
    db, academic = service._session, service._academic
    payload = copy.deepcopy(batch.payload_json or {})
    changes, issues = [], []

    def issue(message, row=None):
        issues.append(
            {
                "code": "CONFIRMATION_CONFLICT",
                "severity": "error",
                "message": message,
                "row": row,
                "filename": batch.filename,
            }
        )

    def change(action, entity, key, before, after, row=None, sheet=None, column=None):
        changes.append(
            {
                "action": action,
                "entity": entity,
                "key": key,
                "before": before,
                "after": after,
                "source": {
                    "filename": batch.filename,
                    "row": row,
                    "sheet": sheet,
                    "column": column,
                },
            }
        )

    if batch.target == "volunteer":
        for row in payload.get("rows", []):
            student = academic.get_student_by_no(row["student_no"])
            existing = (
                academic.get_volunteer_qualification_by_sem_student(batch.semester_id, student.id)
                if student
                else None
            )
            before = {"enabled": existing.enabled} if existing else None
            after = {"enabled": row["enabled"]}
            change(
                "CREATE" if existing is None else "UNCHANGED" if before == after else "UPDATE",
                "qualification",
                row["student_no"],
                before,
                after,
                row.get("source_row"),
                row.get("source_sheet"),
            )
    elif batch.target == "admin_roster":
        classes = list(db.scalars(select(AdministrativeClass)))
        for row in payload.get("students", []):
            student = academic.get_student_by_no(row["student_no"])
            ac = next(
                (
                    c
                    for c in classes
                    if normalize_class_name(c.class_name) == normalize_class_name(row["class_name"])
                    or c.class_code == row["class_name"]
                ),
                None,
            )
            if student and (ac is None or student.administrative_class_id != ac.id):
                issue(
                    "学生所属行政班不同，请使用学籍变更与交接，不能通过重导转班",
                    row.get("source_row"),
                )
            before = {"name": student.name} if student else None
            after = {"name": row["name"]}
            change(
                "CREATE" if student is None else "UNCHANGED" if before == after else "UPDATE",
                "student",
                row["student_no"],
                before,
                after,
                row.get("source_row"),
            )
            metadata = {
                key: row[key]
                for key in ("head_teacher", "counselor", "grade_year", "college")
                if row.get(key) and (ac is None or not getattr(ac, key))
            }
            if metadata:
                before_metadata = {key: getattr(ac, key) for key in metadata} if ac else None
                change(
                    "CREATE" if ac is None else "UPDATE",
                    "class_metadata",
                    row["class_name"],
                    before_metadata,
                    metadata,
                    row.get("source_row"),
                )
        for row in payload.get("class_duties", []):
            ac = next(
                (
                    c
                    for c in classes
                    if normalize_class_name(c.class_name) == normalize_class_name(row["class_name"])
                    or c.class_code == row["class_name"]
                ),
                None,
            )
            after = {key: row[key] for key in ("head_teacher", "counselor") if row.get(key)}
            before = {key: getattr(ac, key) for key in after} if ac else None
            change(
                "CREATE" if ac is None else "UNCHANGED" if before == after else "UPDATE",
                "class_duties",
                row["class_name"],
                before,
                after,
                row.get("source_row"),
            )
    elif batch.target == "roster":
        existing = academic.get_roster_students(batch.teaching_class_id)
        old_nos = {student.student_no for student in existing}
        if db.scalar(
            select(TeachingClassAudience.teaching_class_id)
            .where(TeachingClassAudience.teaching_class_id == batch.teaching_class_id)
            .limit(1)
        ):
            issue("此教学班由行政班学籍驱动，请通过学籍流程维护名单")
        for no in payload.get("student_nos", []):
            source = payload.get("student_sources", {}).get(no, {})
            change(
                "UNCHANGED" if no in old_nos else "CREATE",
                "roster_member",
                no,
                {"present": no in old_nos},
                {"present": True},
                source.get("row"),
                source.get("sheet"),
            )
        payload["preserve_existing"] = True
    else:
        grid = batch.target == "grid_timetable"
        elective = batch.target == "elective_course"
        entries_key = "courses" if grid else "groups" if elective else "rows"
        prepared = []
        for row in payload.get(entries_key, []):
            if batch.target == "timetable":
                course = academic.get_course_by_code(row["course_code"])
                course_code = row["course_code"]
            else:
                course = db.scalar(select(Course).where(Course.course_name == row["course_name"]))
                course_code = (
                    course.course_code
                    if course
                    else ("C_" + hashlib.md5(row["course_name"].encode()).hexdigest()[:8].upper())
                )
            class_code = row.get("class_code")
            if grid:
                ac = next(
                    (
                        c
                        for c in db.scalars(select(AdministrativeClass))
                        if normalize_class_name(c.class_name)
                        == normalize_class_name(payload["class_name"])
                        or c.class_code == payload["class_name"]
                    ),
                    None,
                )
                if ac is None:
                    issue("请先导入并核对该行政班与学生档案", row.get("source_row"))
                    continue
                class_code = f"{ac.class_code}_{course_code}"
            tc = (
                academic.get_teaching_class_by_key(batch.semester_id, course.id, class_code)
                if course
                else None
            )
            existing = (
                list(
                    db.scalars(
                        select(CourseSchedule).where(
                            CourseSchedule.teaching_class_id == tc.id,
                            CourseSchedule.status == "ACTIVE",
                        )
                    )
                )
                if tc
                else []
            )
            unchanged = False
            for schedule in existing:
                weeks = set(
                    db.scalars(
                        select(CourseScheduleWeek.week_no).where(
                            CourseScheduleWeek.schedule_id == schedule.id
                        )
                    )
                )
                if not weeks:
                    issue("已有课表缺少周次，请先核对修复，不能重复追加", row.get("source_row"))
                    continue
                if schedule.weekday != row["weekday"] or not weeks.intersection(row["weeks"]):
                    continue
                if (
                    schedule.start_period > row["end_period"]
                    or schedule.end_period < row["start_period"]
                ):
                    continue
                same = (
                    schedule.start_period == row["start_period"]
                    and schedule.end_period == row["end_period"]
                    and weeks == set(row["weeks"])
                    and (schedule.classroom or "") == (row.get("classroom") or "")
                    and (schedule.teacher or "") == (row.get("teacher") or "")
                )
                if same:
                    unchanged = True
                else:
                    issue(
                        "与现有课表重叠或时间地点不同，请先核对旧课次，不能猜测覆盖对象",
                        row.get("source_row"),
                    )
            key = (
                f"{class_code}/{course_code}/{row['weekday']}/"
                f"{row['start_period']}-{row['end_period']}"
            )
            change(
                "UNCHANGED" if unchanged else "CREATE",
                "schedule",
                key,
                row if unchanged else None,
                row,
                row.get("source_row"),
                row.get("source_sheet"),
                row.get("source_column"),
            )
            changes[-1]["schedule_scope"] = [class_code, course_code, row["weekday"]]
            if elective:
                old_nos = (
                    {s.student_no for s in academic.get_roster_students(tc.id)} if tc else set()
                )
                for no in row.get("student_nos", []):
                    source = row.get("student_sources", {}).get(no, {})
                    change(
                        "UNCHANGED" if no in old_nos else "CREATE",
                        "roster_member",
                        f"{class_code}/{no}",
                        {"present": no in old_nos},
                        {"present": True},
                        source.get("row"),
                        source.get("sheet"),
                    )
                row["schedule_unchanged"] = unchanged
                prepared.append(row)
            elif not unchanged:
                prepared.append(row)
        if grid and prepared and ac is not None:
            try:
                service._check_grid_target_empty(ac, batch.semester_id)
            except AppError as exc:
                issue(exc.message)
        if grid and prepared and any(c["action"] == "UNCHANGED" for c in changes):
            issue("该班已有部分有效课表，请先核对原课表；整张网格表不做隐式替换")
        payload[entries_key] = prepared
        payload["preserve_existing"] = True
    if changes and all(row["action"] == "UNCHANGED" for row in changes):
        payload["confirmation_skip"] = True
    return {"changes": changes, "issues": issues, "payload": payload}
