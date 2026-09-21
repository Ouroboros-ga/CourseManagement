"""学校方格课表（xlsx）→ 标准班级课表长表（自遗留参考移植）。

遗留参考 ``school_grid.py`` 支持 xls/xlsx；本工程按技术方案冻结口径 **只支持 .xlsx**
（openpyxl），xls 需另配 xlrd 依赖并经确认后再引入（DEVELOPMENT_PLAN §5、§6）。

格子文本约定（与遗留一致）：

``课程◇X-Y周(单/双)(N-M节)◇地点◇教师◇选课人数``

本模块把上述周课表习惯转为标准字符串（weeks 如 ``1-11周``/``1-13单周``、
period 如 ``1-4节``、weekday 如 ``周二``），再复用 :mod:`time_slots` 展开为
按周逐格的时间占用，产出 :class:`CourseOccurrence`（携带稳定 ``course_key``）。

纯函数不触库；xlsx 装载器返回 ``list[dict]``，Service 调 :func:`expand_grid_rows`
展开，再做 DTO→ORM。
"""

from __future__ import annotations

import io
import re

from app.common.parsing.dto import CourseOccurrence, make_course_key
from app.common.parsing.time_slots import parse_period, parse_weekday, parse_weeks

BLOCK_RE = re.compile(r"([^\r\n◇]+?)\s*\r?\n◇([^◇]+?)◇([^◇]*?)◇([^◇]*?)◇选课人数：(\d+)")
_PARENS = re.compile(r"\(([^)]+)\)")

# 学校实际含晚上 11-12 小节；默认映射只到 10（大节 1..5）。
# 使用本映射时须记入方案规则快照（技术方案 9.1 period_definition）。
SCHOOL_SLOT_MAPPING: dict[int, int] = {
    1: 1,
    2: 1,
    3: 2,
    4: 2,
    5: 3,
    6: 3,
    7: 4,
    8: 4,
    9: 5,
    10: 5,
    11: 6,
    12: 6,
}

WEEKDAY_NAMES = (
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)
_LONG_TO_SHORT = {
    "星期一": "周一",
    "星期二": "周二",
    "星期三": "周三",
    "星期四": "周四",
    "星期五": "周五",
    "星期六": "周六",
    "星期日": "周日",
    "星期天": "周日",
}


def normalize_weeks(raw: str) -> str:
    """'1-13周(单)'->'1-13单周'，'2-14周(双)'->'2-14双周'，其余去空格。"""
    s = (raw or "").replace("　", "").replace(" ", "").replace("\t", "")
    s = (
        s.replace("(单周)", "单周")
        .replace("(双周)", "双周")
        .replace("(单)", "单周")
        .replace("(双)", "双周")
    )
    s = s.replace("单周周", "单周").replace("双周周", "双周")
    return s


def split_weeks_period(wp: str) -> tuple[str, str]:
    """'1-11周(1-4节)'->('1-11周','1-4节')；找不到节次则 period 为 ''。"""
    groups = _PARENS.findall(wp or "")
    period = ""
    for g in groups:
        if "节" in g:
            period = g.strip()
    weeks = re.sub(r"\([^)]*节\)", "", wp or "").strip()
    return normalize_weeks(weeks), period.strip()


def parse_cell_blocks(cell_text: str) -> list[dict[str, str]]:
    """解析一个格子内 1~N 个课程块。返回 course_name/weeks/period/location/teacher/count。"""
    out: list[dict[str, str]] = []
    for m in BLOCK_RE.finditer(cell_text or ""):
        cname, wp, loc, teacher, cnt = [x.strip() for x in m.groups()]
        weeks, period = split_weeks_period(wp)
        out.append(
            {
                "course_name": cname,
                "weeks": weeks,
                "period": period,
                "location": loc.strip(),
                "teacher": teacher.strip(),
                "count": cnt,
            }
        )
    return out


def extract_class_id(header_texts: list[str]) -> str:
    """从表头 '机电2401课表' 提取 '机电2401'。找不到返回 ''。"""
    for t in header_texts:
        s = (t or "").strip()
        if "课表" in s:
            s = s.replace("课表", "").strip()
            parts = [p for p in re.split(r"\s+", s) if p]
            for p in parts:
                if p and "学年" not in p and "学期" not in p:
                    return p
            if parts:
                return parts[0]
    return ""


def grid_to_rows(cells: list[tuple[str, str]]) -> list[dict[str, str]]:
    """cells: [(weekday, cell_text)] -> 标准班级课表行（不含 class_id）。"""
    rows: list[dict[str, str]] = []
    for weekday, text in cells:
        for b in parse_cell_blocks(text):
            rows.append({"weekday": weekday, **b})
    return rows


def _short_weekday(v: str) -> str | None:
    v = (v or "").strip()
    if v in WEEKDAY_NAMES:
        return _LONG_TO_SHORT.get(v, v)
    return None


def _number_rows(base: list[dict[str, str]], class_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for i, b in enumerate(base, start=1):
        rows.append({"course_id": f"C{i:03d}", "class_id": class_id, **b})
    return rows


def expand_grid_rows(
    rows: list[dict[str, str]],
    total_weeks: int,
    slot_mapping: dict[int, int] | None = None,
) -> list[CourseOccurrence]:
    """标准课表行 → 展开为按周逐格的课程占用列表（不做志愿者/任务）。

    每行要求含 ``class_id``、``course_name``、``weeks``、``weekday``、``period``；
    解析任一字段失败抛 ``ValueError``（上层捕获为 Issue）。稳定 ``course_key``
    由课程身份派生，文件行序变化不改变关联。
    """
    occurrences: list[CourseOccurrence] = []
    for r in rows:
        class_id = r.get("class_id") or ""
        course_name = r.get("course_name") or ""
        if not class_id or not course_name:
            raise ValueError("班级和课程名称不能为空")
        weeks = parse_weeks(r["weeks"], total_weeks)
        wd = parse_weekday(r["weekday"])
        slots = parse_period(r["period"], slot_mapping)
        key = make_course_key(class_id, course_name, weeks, wd, slots, r.get("location", ""))
        for w in weeks:
            for p in slots:
                occurrences.append(
                    CourseOccurrence(
                        course_key=key,
                        class_code=class_id,
                        course_name=course_name,
                        weekday=wd,
                        start_period=p,
                        end_period=p,
                        week_no=w,
                        location=r.get("location", ""),
                    )
                )
    return sorted(occurrences, key=lambda c: (c.course_key, c.week_no, c.start_period))


def load_xlsx_grid(data: bytes, sheet_index: int = 0) -> tuple[str, list[dict[str, str]]]:
    """读取 xlsx 方格字节，返回 (class_id, 标准行列表含 course_id)。"""
    from openpyxl import load_workbook

    wb = load_workbook(filename=io.BytesIO(bytes(data)), data_only=True)
    try:
        ws = wb.worksheets[sheet_index]
        header_row = -1
        col_of_weekday: dict[int, str] = {}
        for r in range(1, min(ws.max_row + 1, 6)):
            vals = [str(ws.cell(row=r, column=c).value or "") for c in range(1, ws.max_column + 1)]
            if "星期一" in vals:
                header_row = r
                for c, v in enumerate(vals, start=1):
                    short = _short_weekday(v)
                    if short:
                        col_of_weekday[c] = short
                break
        if header_row < 0:
            raise ValueError("找不到星期头行（星期一..星期日）")
        header_texts = [
            str(ws.cell(row=r, column=c).value or "")
            for r in range(1, min(ws.max_row + 1, 3))
            for c in range(1, ws.max_column + 1)
        ]
        class_id = extract_class_id(header_texts)
        cells: list[tuple[str, str]] = []
        for r in range(header_row + 1, ws.max_row + 1):
            for c, wd in col_of_weekday.items():
                v = ws.cell(row=r, column=c).value
                if isinstance(v, str) and v.strip():
                    cells.append((wd, v))
        return class_id, _number_rows(grid_to_rows(cells), class_id)
    finally:
        wb.close()
