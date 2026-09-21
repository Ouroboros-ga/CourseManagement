"""课表/名单导入的轻量解析 DTO（技术方案 19）。

解析层只产出这些纯数据结构，不触碰数据库；Service 负责把 DTO 映射为 ORM。
所有业务编号（学号、班级号、课程号）一律以 ``str`` 承载，避免前导零丢失
（技术方案 8.1）。时间格统一用 :data:`Slot` = (周次, 星期 1-7, 标准大节 1-5)。

与遗留参考 ``docs/legacy_parser_reference/models.py`` 的差异：仅保留基础数据
导入所需的课程占用与结构化错误，删去排班/任务/个人修正等后续阶段对象，
不在此维护算法状态。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

# (周次, 星期 1-7, 标准大节 1-5)
Slot = tuple[int, int, int]


@dataclass(frozen=True)
class CourseOccurrence:
    """展开后的单条课程占用：一门课在某个具体时间格的一次出现。

    ``course_key`` 由班级、课程名、周集合、星期、大节集合、地点稳定派生
    （对文件行序不敏感），供上层据以去重与幂等落库。同一门课展开到多个
    周/节会共享同一 ``course_key``，``slot`` 各不同。
    """

    course_key: str
    class_code: str
    course_name: str
    weekday: int
    start_period: int
    end_period: int
    week_no: int
    location: str = ""


@dataclass(frozen=True)
class Issue:
    """结构化校验问题。不适用的定位字段为 None。

    ``severity`` 取 ``"error"``（阻断整批）或 ``"warning"``（不阻断，仅提示）。
    Service 将 error 汇总映射为 ``AppError(VALIDATION_ERROR, fieldErrors=...)``。
    """

    code: str
    message: str
    sheet: str | None = None
    row: int | None = None
    field: str | None = None
    severity: str = "error"


def make_course_key(
    class_code: str,
    course_name: str,
    weeks: Sequence[int],
    weekday: int,
    periods: Sequence[int],
    location: str,
) -> str:
    """由课程身份字段稳定派生 ``course_key``（哈希前缀 CK）。

    对内容敏感、对文件行序不敏感：同一输入重排顺序得到同一 key，
    保证重复导入 / 预览-确认两阶段的课程可稳定对齐。
    """
    identity = [
        class_code,
        course_name,
        sorted(set(weeks)),
        weekday,
        sorted(set(periods)),
        location,
    ]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"CK{digest[:20]}"
