"""有界课表导出。只生成内存中的 XLSX，不建立永久下载文件。"""

from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ErrorCode, NotFoundError, PermissionDeniedError
from app.core.permissions import PermissionCode
from app.modules.academic.models import (
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    TeachingClass,
)
from app.modules.identity.repository import IdentityRepository

MAX_EXPORT_ROWS = 10000
HEADERS = ("教学班", "课程", "教师", "周次", "星期", "开始节次", "结束节次", "教室")
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _text(value: object) -> str:
    """所有文本格标记为字符串；Excel 不会把 =、+、-、@ 当作公式。"""
    return "" if value is None else str(value)


def build_workbook(rows: Iterable[tuple[object, ...]]) -> bytes:
    bounded_rows = []
    for row in rows:
        bounded_rows.append(row)
        if len(bounded_rows) > MAX_EXPORT_ROWS:
            raise ValueError("课表导出最多 10000 行")
    book = Workbook(write_only=True)
    sheet = book.create_sheet("课表")
    sheet.append(list(HEADERS))
    for row in bounded_rows:
        if len(row) != len(HEADERS):
            raise ValueError("课表导出列数不正确")
        from openpyxl.cell import WriteOnlyCell

        cells = []
        for index, value in enumerate(row):
            cell = WriteOnlyCell(sheet, value=value if index in (4, 5, 6) else _text(value))
            if index not in (4, 5, 6):
                cell.data_type = "s"
            cells.append(cell)
        sheet.append(cells)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


class CourseScheduleExportService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def export(
        self, actor_id: int, semester_id: int, teaching_class_ids: list[int] | None
    ) -> bytes:
        identity = IdentityRepository(self._session)
        if identity.get_user_by_id(actor_id) is None or (
            PermissionCode.COURSE_SCHEDULE_EXPORT.value
            not in set(identity.list_effective_permissions(actor_id))
        ):
            raise PermissionDeniedError()
        if self._session.get(Semester, semester_id) is None:
            raise NotFoundError("学期不存在")
        stmt = (
            select(CourseSchedule, TeachingClass, Course)
            .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
            .join(Course, Course.id == TeachingClass.course_id)
            .where(
                CourseSchedule.semester_id == semester_id,
                TeachingClass.semester_id == semester_id,
            )
            .order_by(CourseSchedule.id)
            .limit(MAX_EXPORT_ROWS + 1)
        )
        if teaching_class_ids is not None:
            if not teaching_class_ids:
                return build_workbook([])
            stmt = stmt.where(CourseSchedule.teaching_class_id.in_(set(teaching_class_ids)))
        records = self._session.execute(stmt).all()
        if len(records) > MAX_EXPORT_ROWS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "课表超过 10000 行，请缩小教学班范围后重试",
                http_status=422,
            )
        ids = [schedule.id for schedule, _, _ in records]
        weeks: dict[int, list[int]] = {schedule_id: [] for schedule_id in ids}
        if ids:
            for schedule_id, week_no in self._session.execute(
                select(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
                .where(CourseScheduleWeek.schedule_id.in_(ids))
                .order_by(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
            ):
                weeks[schedule_id].append(week_no)
        rows = [
            (
                teaching_class.class_name,
                course.course_name,
                "",  # 当前基础数据模型未保存任课教师。
                ",".join(str(week) for week in weeks[schedule.id]),
                schedule.weekday,
                schedule.start_period,
                schedule.end_period,
                schedule.classroom or "",
            )
            for schedule, teaching_class, course in records
        ]
        return build_workbook(rows)
