"""定位学校责任区原表表头，保持工号/姓名的后续匹配规则不变。"""


def responsibility_header_row(matrix: list[list[str]]) -> int | None:
    class_headers = {"行政班", "班级", "班级名称", "班级代码", "class_name", "class_code", "class"}
    duty_headers = {
        "班主任",
        "班主任姓名",
        "班主任工号",
        "head_teacher",
        "head_teacher_name",
        "head_teacher_staff_no",
        "辅导员",
        "辅导员姓名",
        "辅导员工号",
        "counselor",
        "counselor_name",
        "counselor_staff_no",
    }
    for index, row in enumerate(matrix[:15], 1):
        headers = {value.strip().lower() for value in row if value.strip()}
        if (
            headers & class_headers
            and headers & duty_headers
            and not headers & {"学号", "student_no", "studentno", "no"}
        ):
            return index
    return None
