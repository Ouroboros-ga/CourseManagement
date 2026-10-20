"""初始化只提取责任区人员文字，档案匹配与任职仍由正式领域规则负责。"""

from app.common.parsing.xlsx_tabular import pick, read_any_matrix, read_tabular_rows
from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.importer.college_names import college_name_keys, normalize_college_name
from app.modules.importer.responsibility_format import responsibility_header_row


def responsibility_payload(db, college_id, content, filename):
    if len(content) > get_settings().file_max_bytes:
        raise ConflictError(message="责任表超过文件大小限制")
    header = responsibility_header_row(read_any_matrix(content))
    if header is None:
        raise ConflictError(
            message="未找到班级责任表表头，请使用班级、班主任、辅导员列；不接收学生花名册"
        )
    rows = read_tabular_rows(content, header_row=header, include_source=True)
    if len(rows) > get_settings().import_max_rows:
        raise ConflictError(message="责任表超过导入行数限制")
    _, college_names = college_name_keys(db, college_id)
    duties = []
    for row in rows:
        college = pick(row, "学院", "二级学院", "所属学院", "college")
        if college and normalize_college_name(college) not in college_names:
            raise ConflictError(message="责任表学院不能唯一对应当前工作区")
        class_name = pick(
            row, "行政班", "班级", "班级名称", "班级代码", "class_name", "class_code", "class"
        )
        duty = {
            "class_name": class_name,
            "source_row": int(row.get("_source_row", 0)),
            "source_sheet": row.get("_source_sheet"),
        }
        for field, names, numbers in (
            (
                "head_teacher",
                ("班主任", "班主任姓名", "head_teacher", "headteacher"),
                ("班主任工号", "班主任号", "head_teacher_staff_no", "head_teacher_no"),
            ),
            (
                "counselor",
                ("辅导员", "辅导员姓名", "counselor"),
                ("辅导员工号", "辅导员号", "counselor_staff_no", "counselor_no"),
            ),
        ):
            duty[field] = pick(row, *names)
            duty[f"{field}_staff_no"] = pick(row, *numbers)
        if not any(
            duty.get(field)
            for field in (
                "head_teacher",
                "head_teacher_staff_no",
                "counselor",
                "counselor_staff_no",
            )
        ):
            continue
        if not class_name:
            raise ConflictError(message="责任表存在人员但缺少班级，请核对原表")
        duties.append(duty)
    if not duties:
        raise ConflictError(message="责任表未包含有效人员来源")
    return {"class_duties": duties, "source_file": filename}
