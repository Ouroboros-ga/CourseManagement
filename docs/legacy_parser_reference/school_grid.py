"""学校方格课表（xls/xlsx 同版式）转标准班级课表长表。

只做预处理，不改核心导入合同。核心 read_workbook 仍只吃标准四表 xlsx。
本模块把学校导出的周课表习惯（时间段/节次/星期一..日 + 格子内
"课程◇X-Y周(单/双)(N-M节)◇地点◇教师◇选课人数"）转为标准模板字符串
（weeks 如 "1-11周"/"1-13单周"，period 如 "1-4节"，weekday 如 "周二"）。

xls 用 xlrd，xlsx 用 openpyxl，同版式复用 parse_cell_blocks。
"""

from __future__ import annotations

import re
import hashlib
import json


BLOCK_RE = re.compile(
    r"([^\r\n◇]+?)\s*\r?\n◇([^◇]+?)◇([^◇]*?)◇([^◇]*?)◇选课人数：(\d+)"
)
_PARENS = re.compile(r"\(([^)]+)\)")

WEEKDAY_BY_INDEX = {2: "周一", 3: "周二", 4: "周三", 5: "周四", 6: "周五", 7: "周六", 8: "周日"}
WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日",
                 "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

# 学校实际含晚上 11-12 小节；默认映射只到 10（大节 1..5）。
# 本批方格需扩展 11-12->6（大节 6），使用时须记入方案 Rules.slot_mapping 快照。
SCHOOL_SLOT_MAPPING: dict[int, int] = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5, 11: 6, 12: 6,
}


def normalize_weeks(raw: str) -> str:
    """'1-13周(单)'->'1-13单周'，'2-14周(双)'->'2-14双周'，其余去空格。"""
    s = (raw or "").replace("　", "").replace(" ", "").replace("\t", "")
    s = (s.replace("(单周)", "单周").replace("(双周)", "双周")
           .replace("(单)", "单周").replace("(双)", "双周"))
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


def parse_cell_blocks(cell_text: str) -> list[dict]:
    """解析一个格子内 1~N 个课程块。返回 course_name/weeks/period/location/teacher/count。"""
    out: list[dict] = []
    for m in BLOCK_RE.finditer(cell_text or ""):
        cname, wp, loc, teacher, cnt = [x.strip() for x in m.groups()]
        weeks, period = split_weeks_period(wp)
        out.append({
            "course_name": cname, "weeks": weeks, "period": period,
            "location": loc.strip(), "teacher": teacher.strip(), "count": cnt,
        })
    return out


def extract_class_id(header_texts: list[str]) -> str:
    """从表头 '机电2401课表' 提取 '机电2401'。找不到返回 ''。"""
    for t in header_texts:
        s = (t or "").strip()
        if "课表" in s:
            s = s.replace("课表", "").strip()
            # 取连续非空片段（如 '机电2401'）
            parts = [p for p in re.split(r"\s+", s) if p]
            for p in parts:
                if p and p not in ("2026-2027学年第1学期",):
                    # 常见 '机电2401课表' 已去课表即班级；若含学年则跳过
                    if "学年" in p or "学期" in p:
                        continue
                    return p
            if parts:
                return parts[0]
    return ""


def grid_to_rows(cells: list[tuple[str, str]]) -> list[dict]:
    """cells: [(weekday, cell_text)] -> 标准班级课表行（不含 course_id/class_id）。"""
    rows: list[dict] = []
    for weekday, text in cells:
        for b in parse_cell_blocks(text):
            rows.append({"weekday": weekday, **b})
    return rows


def _short_weekday(v: str) -> str | None:
    v = (v or "").strip()
    if v in WEEKDAY_NAMES:
        return {"星期一": "周一", "星期二": "周二", "星期三": "周三",
                "星期四": "周四", "星期五": "周五", "星期六": "周六",
                "星期日": "周日", "星期天": "周日"}.get(v, v)
    return None


def _number_rows(base: list[dict], class_id: str) -> list[dict]:
    rows: list[dict] = []
    for i, b in enumerate(base, start=1):
        rows.append({"course_id": f"C{i:03d}", "class_id": class_id, **b})
    return rows


def rows_to_snapshot(
    rows: list[dict],
    term_id: str,
    total_weeks: int,
    slot_mapping: dict[int, int] | None = None,
):
    """方格行（course_name/weeks/weekday/period）展开为 InputSnapshot（无志愿者/任务）。

    按课程内容生成稳定编号，文件顺序变化不会改变关联。
    """
    from models import CourseEntry, InputSnapshot
    from normalize import parse_period, parse_weekday, parse_weeks

    courses: list[CourseEntry] = []
    for r in rows:
        if not r.get('class_id') or not r.get('course_name'):
            raise ValueError('班级和课程名称不能为空')
        weeks = parse_weeks(r["weeks"], total_weeks)
        wd = parse_weekday(r["weekday"])
        slots = parse_period(r["period"], slot_mapping)
        identity = [r['class_id'], r['course_name'], weeks, wd, slots, r.get('location', '')]
        cid = 'C' + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
        for w in weeks:
            for p in slots:
                courses.append(CourseEntry(id=cid, class_id=r["class_id"],
                                           slot=(w, wd, p), course_name=r["course_name"],
                                           location=r.get('location', '')))
    courses_sorted = tuple(sorted(set(courses), key=lambda c: (c.id, c.slot)))
    return InputSnapshot(term_id=term_id, total_weeks=total_weeks,
                         volunteers=(), courses=courses_sorted, overrides=(), tasks=())


def load_xls_grid(data: bytes, sheet_index: int = 0) -> tuple[str, list[dict]]:
    """读取 xls 方格字节，返回 (class_id, 标准行列表含 course_id)。"""
    import xlrd  # xls 专用，核心仍只依赖 openpyxl

    bk = xlrd.open_workbook(file_contents=bytes(data))
    sh = bk.sheet_by_index(sheet_index)
    # 找星期头行
    header_row = -1
    col_of_weekday: dict[int, str] = {}
    for r in range(min(sh.nrows, 5)):
        vals = [str(sh.cell_value(r, c)) for c in range(sh.ncols)]
        if "星期一" in vals:
            header_row = r
            for c, v in enumerate(vals):
                short = _short_weekday(v)
                if short:
                    col_of_weekday[c] = short
            break
    if header_row < 0:
        raise ValueError("找不到星期头行（星期一..星期日）")
    header_texts = [str(sh.cell_value(r, c)) for r in range(min(sh.nrows, 2)) for c in range(sh.ncols)]
    class_id = extract_class_id(header_texts)
    cells: list[tuple[str, str]] = []
    for r in range(header_row + 1, sh.nrows):
        for c, wd in col_of_weekday.items():
            v = sh.cell_value(r, c)
            if isinstance(v, str) and v.strip():
                cells.append((wd, v))
    return class_id, _number_rows(grid_to_rows(cells), class_id)


def load_xlsx_grid(data: bytes, sheet_index: int = 0) -> tuple[str, list[dict]]:
    """读取同版式 xlsx 方格字节，返回 (class_id, 标准行列表含 course_id)。"""
    from openpyxl import load_workbook
    import io

    wb = load_workbook(filename=io.BytesIO(bytes(data)), data_only=True)
    ws = wb.worksheets[sheet_index]
    assert ws is not None
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
        for r in range(1, min(ws.max_row + 1, 3)) for c in range(1, ws.max_column + 1)
    ]
    class_id = extract_class_id(header_texts)
    cells: list[tuple[str, str]] = []
    assert ws.max_row is not None and ws.max_column is not None
    for r in range(header_row + 1, ws.max_row + 1):
        for c, wd in col_of_weekday.items():
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and v.strip():
                cells.append((wd, v))
    return class_id, _number_rows(grid_to_rows(cells), class_id)
