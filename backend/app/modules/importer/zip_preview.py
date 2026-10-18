"""有界解压 ZIP；只创建预览，正式保存仍走原确认集合。"""

import io
import stat
import unicodedata
import zipfile
from contextlib import suppress
from pathlib import PurePosixPath

from app.core.exceptions import AppError, ErrorCode

MAX_FILE = 10 * 1024 * 1024


def expand_zip(content: bytes) -> list[tuple[str, bytes]]:
    def invalid(message: str):
        raise AppError(ErrorCode.VALIDATION_ERROR, message, 422)

    if len(content) > MAX_FILE:
        invalid("ZIP 文件不能超过 10 MiB")
    members, names, total = [], set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if len(archive.infolist()) > 200:
                invalid("压缩包目录项超过 200 项，请只保留需要导入的表格")
            for info in archive.infolist():
                name = info.filename
                if not info.flag_bits & 0x800:
                    with suppress(UnicodeEncodeError, UnicodeDecodeError):
                        name = name.encode("cp437").decode("gbk")
                path = PurePosixPath(name.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
                    invalid("ZIP 包含不安全的成员路径")
                if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    invalid("请使用未加密且不包含链接的 ZIP 压缩包")
                if info.is_dir() or "__MACOSX" in path.parts or path.name.startswith("."):
                    continue
                if path.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
                    invalid(f"压缩包中的“{path.name}”不是表格，请移除后重试（不支持嵌套压缩包）")
                key = unicodedata.normalize("NFKC", str(path)).casefold()
                if key in names:
                    invalid("ZIP 包含重复的文件路径")
                names.add(key)
                total += info.file_size
                if len(members) >= 20 or info.file_size > MAX_FILE or total > 50 * 1024 * 1024:
                    invalid("每次最多 20 个表格，单文件 10 MiB，解压后合计不超过 50 MiB")
                if len(str(path)) > 255:
                    invalid("ZIP 内文件路径过长")
                with archive.open(info) as source:
                    data = source.read(MAX_FILE + 1)
                if len(data) > MAX_FILE:
                    invalid("ZIP 内单个文件超过 10 MiB")
                members.append((str(path), data))
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, EOFError) as exc:
        invalid(f"ZIP 无法读取，请重新压缩后上传（{type(exc).__name__}）")
    if not members:
        invalid("ZIP 中没有可导入的 Excel/CSV 表格")
    return members


def preview_zip(
    service,
    actor,
    content,
    *,
    target,
    semester_id=None,
    teaching_class_id=None,
    course_type_id=None,
    request_id=None,
):
    service._require_composite(actor.id, target)
    drafts, errors = [], []
    for name, data in expand_zip(content):
        try:
            draft = service.create_preview(
                actor,
                target=target,
                content=data,
                semester_id=semester_id,
                teaching_class_id=teaching_class_id,
                course_type_id=course_type_id,
                filename=name,
                replace=False,
                request_id=request_id,
            )
            drafts.append({**draft.model_dump(mode="json"), "filename": name})
        except AppError as exc:
            service._session.rollback()
            errors.append({"filename": name, "message": str(exc.message)})
    return {"files": drafts, "errors": errors, "business_data_applied": False}
