"""无持久化的文件识别；正式预览/保存仍使用原导入接口。"""

from app.common.parsing.xlsx_tabular import read_any_matrix
from app.core.exceptions import AppError, ErrorCode
from app.modules.importer.catalog import detect_target
from app.modules.importer.limits import MAX_ARCHIVE_BYTES
from app.modules.importer.zip_preview import MAX_FILE, expand_zip


def _inspect(content: bytes, name: str) -> dict:
    result = {"filename": name, "target": None, "blocked": False, "message": ""}
    try:
        from app.modules.importer.attendance_roster import inspect_attendance, read_sheets

        sheets = read_sheets(content)
        attendance = inspect_attendance(sheets)
        populated = [name for name, rows in sheets if any(any(row) for row in rows)]
        if attendance is None:
            if len(populated) > 1:
                raise ValueError("文件包含多个有内容的工作表，请拆成单独文件后导入，避免遗漏")
            if populated and populated[0] != sheets[0][0]:
                raise ValueError("数据不在第一个工作表，请将数据单独另存为一个文件")
        matrix = sheets[0][1] if sheets else read_any_matrix(content)
        if len(matrix) > 20000 or any(len(row) > 256 for row in matrix):
            raise ValueError("表格超过 20000 行或 256 列，请拆分文件")
        # 标准长表要求首行表头；旧花名册、网格原表另由既有格式解析器识别。
        target = (
            "admin_roster"
            if attendance
            else (detect_target([str(v) for v in matrix[0]], name) if matrix else None)
        )
        if attendance and attendance["ignored_sheets"]:
            result["message"] = (
                f"仅采用工作表 {attendance['source_sheet']} 的名单，其余工作表不导入"
            )
        if target is None:
            from app.common.parsing.grid import load_grid

            try:
                class_name, rows = load_grid(content)
                if rows and any(r.get("course_name") for r in rows):
                    target = "grid_timetable"
            except Exception:  # 非网格格式不是文件损坏，保留给用户选择原解析器。
                pass
        result["target"] = target
        if target is None:
            result["message"] = "未能唯一识别资料类型，请选择；读取预览后仍会校验文件内容"
    except Exception as exc:
        result.update(blocked=True, message=f"无法读取：{exc}")
    return result


def inspect_upload(content: bytes, filename: str) -> list[dict]:
    limit = MAX_ARCHIVE_BYTES if filename.lower().endswith(".zip") else MAX_FILE
    if len(content) > limit:
        raise AppError(ErrorCode.VALIDATION_ERROR, "ZIP 上限 50 MiB，单表格上限 10 MiB", 422)
    if filename.lower().endswith(".zip"):
        return [
            {**_inspect(data, name), "archive_member": name}
            for name, data in expand_zip(content, allow_template_notes=True)
        ]
    return [{**_inspect(content, filename), "archive_member": None}]
