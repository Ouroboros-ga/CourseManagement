"""导入权限与模板契约（PERMISSIONS.md 11.3/12.5）。

导入执行 = 目标资源 manage + import.execute 的组合：任一缺失即 403。
本模块集中"目标→管理权限"映射与三类导入模板的列定义，作为服务与
文档的单一真相源。列名支持中英文别名（见 each template 的 aliases）。
"""

from __future__ import annotations

from app.core.permissions import PermissionCode
from app.modules.importer.models import ImportTarget

# 目标类型 → 对应的资源 manage 权限（组合上再要求 import.execute）。
TARGET_MANAGE_PERMISSION: dict[str, str] = {
    ImportTarget.ROSTER.value: PermissionCode.STUDENT_MANAGE.value,
    ImportTarget.TIMETABLE.value: PermissionCode.COURSE_SCHEDULE_IMPORT.value,
    ImportTarget.VOLUNTEER.value: PermissionCode.VOLUNTEER_MANAGE.value,
    ImportTarget.ADMIN_ROSTER.value: PermissionCode.STUDENT_MANAGE.value,
    ImportTarget.GRID_TIMETABLE.value: PermissionCode.COURSE_SCHEDULE_IMPORT.value,
    ImportTarget.ELECTIVE_COURSE.value: PermissionCode.COURSE_SCHEDULE_IMPORT.value,
}

# 各模板需要的作用域参数（semester_id / teaching_class_id）。
TARGET_SCOPE_FIELDS: dict[str, tuple[str, ...]] = {
    ImportTarget.ROSTER.value: ("teaching_class_id",),
    ImportTarget.TIMETABLE.value: ("semester_id",),
    ImportTarget.VOLUNTEER.value: ("semester_id",),
    ImportTarget.ADMIN_ROSTER.value: (),
    ImportTarget.GRID_TIMETABLE.value: ("semester_id",),
    ImportTarget.ELECTIVE_COURSE.value: ("semester_id",),
}


class TemplateColumn:
    def __init__(self, key: str, header: str, aliases: tuple[str, ...], required: bool):
        self.key = key
        self.header = header
        self.aliases = aliases
        self.required = required

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "header": self.header,
            "aliases": list(self.aliases),
            "required": self.required,
        }


# 表头候选（含中文/英文/常见别名），read_tabular_rows 以原始表头为键，
# 服务用 pick(row, *aliases) 归一取值。
ROSTER_COLUMNS = [
    TemplateColumn("student_no", "学号", ("学号", "student_no", "studentno", "no"), True),
    TemplateColumn("name", "姓名", ("姓名", "name", "student_name"), False),
]

VOLUNTEER_COLUMNS = [
    TemplateColumn("student_no", "学号", ("学号", "student_no", "studentno", "no"), True),
    TemplateColumn("enabled", "是否启用", ("是否启用", "启用", "enabled", "enable"), False),
]

TIMETABLE_COLUMNS = [
    TemplateColumn("class_code", "教学班码", ("教学班码", "教学班", "class_code"), True),
    TemplateColumn("course_code", "课程代码", ("课程代码", "课程编码", "course_code"), True),
    TemplateColumn("course_name", "课程名称", ("课程名称", "课程", "course_name"), False),
    TemplateColumn("weekday", "星期", ("星期", "weekday", "周"), True),
    TemplateColumn("start_period", "开始大节", ("开始大节", "start_period", "起节"), True),
    TemplateColumn("end_period", "结束大节", ("结束大节", "end_period", "止节"), True),
    TemplateColumn("weeks", "周次", ("周次", "weeks", "上课周"), True),
    TemplateColumn("classroom", "上课地点", ("上课地点", "地点", "classroom"), False),
]

ADMIN_ROSTER_COLUMNS = [
    TemplateColumn("student_no", "学号", ("学号", "student_no", "studentno", "no"), True),
    TemplateColumn("name", "姓名", ("姓名", "name", "student_name"), True),
    TemplateColumn("class_name", "班级", ("班级", "班级名称", "行政班", "class_name", "class"), True),
    TemplateColumn("college", "学院", ("学院", "所属学院", "college", "department"), False),
    TemplateColumn("grade_year", "年级", ("年级", "入学年级", "grade_year", "grade"), False),
    TemplateColumn("class_code", "班级代码", ("班级代码", "班号", "class_code"), False),
]

GRID_TIMETABLE_COLUMNS = [
    TemplateColumn("grid_file", "学校网格课表", ("课表", "网格课表", "grid"), True),
]

ELECTIVE_COURSE_COLUMNS = [
    TemplateColumn("course_name", "课程名称", ("课程名称", "课程", "course_name"), True),
    TemplateColumn("class_code", "教学班码", ("教学班码", "教学班", "class_code"), True),
    TemplateColumn("class_name", "教学班名", ("教学班名", "教学班名称", "class_name"), False),
    TemplateColumn("weekday", "星期", ("星期", "weekday", "周"), True),
    TemplateColumn("start_period", "开始大节", ("开始大节", "start_period", "起节"), True),
    TemplateColumn("end_period", "结束大节", ("结束大节", "end_period", "止节"), True),
    TemplateColumn("weeks", "周次", ("周次", "weeks", "上课周"), True),
    TemplateColumn("classroom", "上课地点", ("上课地点", "地点", "教室", "classroom"), False),
    TemplateColumn("student_no", "学号", ("学号", "选课学生学号", "student_no", "no"), True),
    TemplateColumn("student_name", "学生姓名", ("学生姓名", "姓名", "name"), False),
]

TEMPLATES: dict[str, list[TemplateColumn]] = {
    ImportTarget.ROSTER.value: ROSTER_COLUMNS,
    ImportTarget.VOLUNTEER.value: VOLUNTEER_COLUMNS,
    ImportTarget.TIMETABLE.value: TIMETABLE_COLUMNS,
    ImportTarget.ADMIN_ROSTER.value: ADMIN_ROSTER_COLUMNS,
    ImportTarget.GRID_TIMETABLE.value: GRID_TIMETABLE_COLUMNS,
    ImportTarget.ELECTIVE_COURSE.value: ELECTIVE_COURSE_COLUMNS,
}


def required_headers(target: str) -> list[str]:
    return [c.header for c in TEMPLATES.get(target, []) if c.required]


def template_spec(target: str) -> dict[str, object]:
    """返回模板描述：目标、作用域参数、列定义、示例行。"""
    examples = {
        ImportTarget.ROSTER.value: [{"学号": "20240001", "姓名": "张三"}],
        ImportTarget.VOLUNTEER.value: [{"学号": "20240001", "是否启用": "是"}],
        ImportTarget.TIMETABLE.value: [
            {
                "教学班码": "CS-2401-A",
                "课程代码": "C001",
                "课程名称": "高等数学",
                "星期": "周一",
                "开始大节": "1",
                "结束大节": "2",
                "周次": "1-16周",
                "上课地点": "A101",
            }
        ],
        ImportTarget.ADMIN_ROSTER.value: [
            {
                "学号": "0419260101",
                "姓名": "张三",
                "班级": "数据科学2601",
                "学院": "人工智能学院",
                "年级": "2026",
            }
        ],
        ImportTarget.GRID_TIMETABLE.value: [
            {"说明": "直接上传学校教务导出的班级网格课表（.xls 或 .xlsx）"}
        ],
        ImportTarget.ELECTIVE_COURSE.value: [
            {
                "课程名称": "微积分A1",
                "教学班码": "MATH101-01",
                "教学班名": "微积分A1(01班)",
                "星期": "周二",
                "开始大节": "1",
                "结束大节": "1",
                "周次": "1-17周",
                "上课地点": "教学楼3-203",
                "学号": "0419260101",
                "学生姓名": "毕卓凡",
            }
        ],
    }
    return {
        "target": target,
        "scope_fields": list(TARGET_SCOPE_FIELDS.get(target, ())),
        "columns": [c.as_dict() for c in TEMPLATES.get(target, [])],
        "example_rows": examples.get(target, []),
    }
